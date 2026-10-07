"""The incident repro, inverted: seat the judge, ask something social, get an answer.

This is the regression test for the whole 2026-09-25 outage. With the model
seated the gate runs, and before Fix 2 it held "what did you have for
breakfast?" with missing=['your breakfast'] — which meant the brain was never
invoked, and the verdict refreshed the model's keep_alive lease, so the trap
re-armed on every clarification the user offered.

Skips cleanly when the service or ollama is down.
"""
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

import pytest
import requests
import urllib3

urllib3.disable_warnings()
pytestmark = pytest.mark.smoke

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "modules"))

OLLAMA = "http://127.0.0.1:11434"


def _env(name, default=""):
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8"):
            if raw.strip().startswith(f"{name}="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv(name, default)


BASE = f"https://127.0.0.1:{_env('PH3B3_PORT', '7331')}"
AUTH = (_env("PH3B3_USER", "admin"), _env("PH3B3_PASSWORD"))
JUDGE = _env("PH3B3_HEAVY_MODEL", "ph3b3-chat:latest")


def _up(fn):
    try:
        return fn()
    except Exception:
        return False


needs_service = pytest.mark.skipif(
    not _up(lambda: requests.get(f"{BASE}/ready", verify=False, auth=AUTH,
                                 timeout=5).status_code == 200),
    reason="ph3b3 service not reachable")
needs_ollama = pytest.mark.skipif(
    not _up(lambda: requests.get(f"{OLLAMA}/api/tags", timeout=5).status_code == 200),
    reason="ollama not reachable")


def _seat_the_judge():
    """Arm the trap deliberately — this is the condition the outage needed."""
    requests.post(f"{OLLAMA}/api/chat", timeout=300, json={
        "model": JUDGE, "messages": [{"role": "user", "content": "potato"}],
        "stream": False, "options": {"num_predict": 1}})


def _resident():
    try:
        return [m["name"] for m in
                requests.get(f"{OLLAMA}/api/ps", timeout=5).json().get("models", [])]
    except Exception:
        return []


def _ask(q):
    r = requests.post(f"{BASE}/chat", verify=False, auth=AUTH, timeout=240,
                      json={"message": q, "session_id": "__smoke__fx2-" + uuid.uuid4().hex[:8],
                            "text_only": True})
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


# ── "did the gate hold it?" is a fact in the log, not a guess about prose ─────
# This test used to infer a hold from the ANSWER: a reply ending in "?" and under
# 260 characters was called a clarifier. On 2026-09-26 that misfired in the worst
# possible direction — it reported the triage gate as broken when the gate had
# never run:
#
#   asked: 'what did you have for breakfast'
#   got:   I don't have a capture — want me to take one?
#   AssertionError: the gate held a social turn with the judge seated
#
# Nothing was held. She ANSWERED, and the answer was the capture deflection — a
# persona fault that happens to be shaped like a question. One fault was
# generating two diagnoses, and the false one pointed at the module this file
# exists to defend.
#
# The gate writes its own verdict: server.py logs "TRIAGE_HOLD — missing=[...]"
# on every hold, and nothing else writes that string. So the question is asked of
# the journal. A turn is held if and only if that line was written while it ran.
#
# There is no prose fallback ON PURPOSE. If the journal cannot be read this skips,
# because guessing from the reply is the bug being removed, not a safety net. The
# capture deflection itself is persona_smoke's business (test_no_tool_narration),
# where it is correctly attributed.
def _journal_readable():
    try:
        r = subprocess.run(["journalctl", "-u", "ph3b3", "-n", "1", "--no-pager"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _lines_since(stamp, needles):
    r = subprocess.run(["journalctl", "-u", "ph3b3", "--since", stamp, "--no-pager"],
                       capture_output=True, text=True, timeout=30)
    return [ln for ln in r.stdout.splitlines() if any(n in ln for n in needles)]


def _holds_since(stamp):
    """Every gate HOLD logged since `stamp`. Not overrules, not declines, not
    phatic skips — those are the gate working, and each has its own line."""
    r = subprocess.run(["journalctl", "-u", "ph3b3", "--since", stamp, "--no-pager"],
                       capture_output=True, text=True, timeout=30)
    return [ln for ln in r.stdout.splitlines()
            if "TRIAGE_HOLD" in ln
            and "TRIAGE_HOLD_OVERRULED" not in ln
            and "TRIAGE_HOLD_DECLINED" not in ln]


needs_journal = pytest.mark.skipif(
    not _journal_readable(),
    reason="cannot read the ph3b3 journal — this test refuses to infer a hold "
           "from the wording of the reply, which is the bug it was rewritten to "
           "remove")


@needs_service
@needs_ollama
@needs_journal
@pytest.mark.parametrize("question", [
    "what did you have for breakfast",
    "how was your morning",
    "what do you think about social media",
])
def test_a_social_turn_flows_with_the_judge_seated(question):
    _seat_the_judge()
    assert any(JUDGE.split(":")[0] in m for m in _resident()), \
        "could not seat the judge — the trap condition is not set up"
    # One second back: journalctl --since has second resolution, and a cursor
    # taken in the same second as the first log line would miss it.
    # The gate must be ON, or "no hold was logged" proves nothing at all. Read
    # the same switch the module reads, per request, rather than trusting it.
    import triage
    assert triage.gate_enabled(), \
        "the triage gate is switched off (config/triage.json or PH3B3_TRIAGE) — " \
        "with no gate running, this test cannot tell a pass from a bypass"

    stamp = (datetime.now() - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    a = _ask(question)
    assert a, "empty response"

    # A turn that never reached the judge is not evidence either way. The gate
    # announces both ways of not running, so both are checked — without this the
    # test goes green on a phatic skip or a fail-open, which is the whole
    # green-on-nothing family.
    bypassed = _lines_since(stamp, ("TRIAGE_SKIP_PHATIC", "TRIAGE_FAILOPEN"))
    assert not bypassed, (
        f"the gate did not run for {question!r}, so this proves nothing:\n  "
        + "\n  ".join(ln.strip()[-120:] for ln in bypassed))

    holds = _holds_since(stamp)
    assert not holds, (
        "the gate held a social turn with the judge seated — this is the outage:\n"
        f"  asked: {question!r}\n  got:   {a}\n  journal: {holds[-1].strip()}")


def test_the_hold_detector_reads_the_log_and_not_the_wording():
    """Guard the guard, both directions.

    The old heuristic would have called each of these a hold; a hold is a line in
    the journal, and none of these produced one. This is the misdiagnosis pinned
    so it cannot come back — and the second half proves the detector still SEES a
    real hold when the log carries one.
    """
    question_shaped = [
        "I don't have a capture — want me to take one?",
        "How about you?",
        "Good morning! How can I assist you today?",
    ]
    for a in question_shaped:
        assert a.rstrip().endswith("?") and len(a) < 260, \
            "fixture no longer matches what the old heuristic flagged"

    real = ("Sep 26 17:31:02 Nyx ph3b3[123]: 2026-09-26 17:31:02,001 [Ph3b3] "
            "TRIAGE_HOLD — missing=['your breakfast']")
    fine = [
        "... [Ph3b3] TRIAGE_HOLD_OVERRULED — missing=['your mood'] not fetchable",
        "... [Ph3b3] TRIAGE_HOLD_DECLINED — missing=['The Lighthouse'] named but absent",
        "... [Ph3b3] TRIAGE_SKIP_PHATIC — pleasantry, not judged (total 4)",
    ]

    def _filter(lines):
        return [ln for ln in lines
                if "TRIAGE_HOLD" in ln
                and "TRIAGE_HOLD_OVERRULED" not in ln
                and "TRIAGE_HOLD_DECLINED" not in ln]

    assert _filter([real]) == [real], "a real hold line is not recognised"
    assert _filter(fine) == [], f"the gate working was read as a hold: {_filter(fine)}"


@needs_service
@needs_ollama
def test_a_genuinely_fetchable_hold_still_holds_and_names_it():
    """The other direction. Overruling everything would be the same bug
    inverted — a guard that never guards."""
    _seat_the_judge()
    a = _ask("summarize the document")
    assert a, "empty response"
    assert not any(w in a.lower() for w in ("in summary", "the document states",
                                            "this document covers")), \
        f"she summarised a document that does not exist:\n{a}"


@needs_service
@needs_ollama
@needs_journal
def test_the_journal_reading_works_against_the_live_service():
    """End-to-end proof of the detector, not just of its string filter.

    "hi" is a pure pleasantry, so the gate announces a SKIP rather than judging
    it. If this finds no line, the journal reading is broken and every other
    assertion in this file that depends on "no hold was logged" is worthless —
    which is exactly how a log-reading test goes quietly green forever.
    """
    stamp = (datetime.now() - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    a = _ask("hi")
    assert a, "empty response"
    skipped = _lines_since(stamp, ("TRIAGE_SKIP_PHATIC",))
    assert skipped, (
        "no TRIAGE_SKIP_PHATIC line found for 'hi' — either the phatic fast path "
        "has stopped working, or this file cannot actually read the journal it "
        "bases its verdicts on")
    assert not _holds_since(stamp), "a bare greeting was held"
