"""The bare phrasing "can you edit text?" is answered from her own config.

THE INCIDENT (2026-09-25, live, first turn of a session):

    > hey Phoebe, can you edit text?
    "Yes, I can edit text within an image. If you provide me with an image that
     contains text, I can modify or replace the existing text... please upload
     the image... you'll have options to make changes directly on the screen."

False twice: the trial flag is off, and there is no screen to make changes on.
The deterministic refusal from 485d6f3 did not fire because it requires BOTH a
text word and a picture word — deliberately, so that generation with readable
text (which works) is never swallowed by a refusal meant for editing. The bare
phrasing carries only the text word.

WHAT WAS MEASURED FIRST (chat logs + mnemosyne, every arrival to date):

    46 edit+text turns    44 name a picture   -> already refused deterministically
                           2 are the bare form -> reached the model, fabricated
                           0 name a file, paragraph, post or message

So the bare case is the only phrasing a human has actually typed here, and the
"text + some other artifact" bucket is, so far, hypothetical. It is still given
a route, because the answer to it must be "yes" and an interception there would
deny a real capability.

THE THREE ROUTES, and which module owns each:

    text + picture noun   apelles.blocked_request     refusal, unchanged
    text + NO artifact    self_knowledge.text_editing this file
    text + other artifact nobody                      flows to the work

The root cause was not the regex. Nothing in her prompt said she can edit PROSE,
so asked about editing text the only fact she had was the picture one. Both
halves now live in ONE derived section, and this route returns that section's
own answer verbatim — no sentence is written in the route, so it cannot drift
from what she reads, and when the trial flag flips the answer follows with no
code change.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import apelles                      # noqa: E402
import intent_registry              # noqa: E402
import morpheus                     # noqa: E402  (bare name — see conftest)
from agent import server            # noqa: E402


TRIAL_OFF = (False, "the trial for it hasn't finished, so it isn't switched on yet",
             "set PH3B3_QWEN_EDIT=on once the trial passes")


@pytest.fixture
def flags(monkeypatch):
    """Drive the switch the way production does: one reader, three flags."""
    def _set(qwen=True, qwen_edit=False, edit_lane=True):
        monkeypatch.setattr(morpheus, "qwen_open", lambda: qwen)
        monkeypatch.setattr(server, "QWEN_EDIT_ENABLED", qwen_edit)
        monkeypatch.setattr(server, "EDIT_LANE_ENABLED", edit_lane)
    return _set


def _route(text):
    """Which authority answers this turn, above the gate."""
    if apelles.blocked_request(text):
        return "refusal"
    claim = intent_registry.resolve(text)
    if claim is None:
        return "model"
    return f"{claim.module}.{claim.handler}"


# ── route B: the incident, inverted ──────────────────────────────────────────
BARE = [
    "can you edit text?",                    # the incident, stripped
    "hey Phoebe, can you edit text?",        # the incident, verbatim
    "are you able to edit text?",
    "do you do text editing?",
    "can you fix text?",
    "can you correct spelling?",
    "could you change the wording?",
    "do you offer proofreading?",
]


@pytest.mark.parametrize("text", BARE)
def test_the_bare_ask_is_claimed_not_left_to_the_model(flags, text):
    flags()
    assert _route(text) == "self_knowledge.text_editing", \
        f"{text!r} still reaches the model, which is what fabricated the answer"


@pytest.mark.parametrize("text", BARE)
def test_the_answer_is_the_sections_own_answer_verbatim(flags, text):
    """Derivation by identity — the strongest form of the one-voice rule.

    If the route ever composes, paraphrases or appends a sentence of its own,
    this goes red. That is the point: a hand-written capability sentence is how
    the block and the answer start disagreeing."""
    flags()
    section = {k: a for k, _t, _x, a in server._self_knowledge_sections()}
    assert server.text_editing_answer() == section["text_edit"]


def test_the_answer_states_both_halves(flags):
    flags(qwen_edit=False)
    a = server.text_editing_answer().lower()
    assert "i can edit and rewrite text you give me" in a, \
        "the prose half is missing — this is the fact she did not have"
    assert "picture" in a and ("can't" in a or "cannot" in a), \
        "the picture half is missing, so the false claim is still available"


def test_the_answer_never_offers_to_edit_text_in_a_picture(flags):
    """The exact sentence from the incident must be impossible while off."""
    flags(qwen_edit=False)
    a = server.text_editing_answer().lower()
    assert not re.search(r"\byes,?\s+i\s+can\s+edit\s+text\s+(?:with)?in\s+an?\s+image\b", a)
    assert "upload" not in a and "on the screen" not in a, \
        "it describes a UI gesture there is no UI for"


# ── the flag actually drives it ──────────────────────────────────────────────
def test_flag_on_flips_the_picture_half_with_no_code_change(flags):
    flags(qwen=True, qwen_edit=True, edit_lane=True)
    on = server.text_editing_answer().lower()
    assert "it works too" in on, f"the trial is ON and she still denies it:\n{on}"
    assert "can't do that one" not in on

    flags(qwen=True, qwen_edit=False, edit_lane=True)
    off = server.text_editing_answer().lower()
    assert "can't do that one" in off
    assert on != off, "the answer is the same in both switch states"


def test_each_off_reason_reaches_the_bare_answer(flags):
    """Three off-states, three different sentences — the same three the refusal
    gives, because both read the same function."""
    seen = set()
    for combo in [dict(qwen=False, qwen_edit=False, edit_lane=True),
                  dict(qwen=True, qwen_edit=False, edit_lane=False),
                  dict(qwen=True, qwen_edit=False, edit_lane=True)]:
        flags(**combo)
        seen.add(server.text_editing_answer())
    assert len(seen) == 3, "two different off-states produce the same sentence"


def test_the_refusal_and_the_bare_answer_cannot_disagree(flags):
    """One reader for one switch. The refusal's REASON must be the reason she
    gives when asked bare — otherwise the two answers to one question drift."""
    for combo in [dict(qwen=False, qwen_edit=False, edit_lane=True),
                  dict(qwen=True, qwen_edit=False, edit_lane=False),
                  dict(qwen=True, qwen_edit=False, edit_lane=True)]:
        flags(**combo)
        reason = apelles.text_edit_state()[1]
        assert reason in server.text_editing_answer(), \
            f"the bare answer omits the refusal's own reason: {reason!r}"


# ── route A is untouched ─────────────────────────────────────────────────────
# The four phrasings from 485d6f3's own list, plus the real 44x arrival.
STILL_REFUSED = [
    "Can you fix the text in an existing image?",
    "fix the text in this image",
    "can you correct the lettering in that picture",
    "the words in the poster came out wrong, can you fix them",
    "change the text in this photo",
    "replace the wording in this jpeg",
]


@pytest.mark.parametrize("text", STILL_REFUSED)
def test_the_picture_phrasings_still_get_the_refusal(flags, text):
    flags()
    assert _route(text) == "refusal", \
        f"{text!r} no longer reaches the deterministic refusal"


# ── route C flows, and generation is never swallowed ─────────────────────────
STILL_FLOWS = [
    "can you edit the text in this file?",
    "fix the wording in this paragraph",
    "rewrite the text of this message for me",
    "can you fix the typo in my commit message?",
    "proofread this paragraph for me",
    "make me a poster with readable text",
    "generate an image of a shop sign that says OPEN",
]


@pytest.mark.parametrize("text", STILL_FLOWS)
def test_a_real_request_reaches_the_work_not_a_capability_statement(flags, text):
    flags()
    assert _route(text) == "model", \
        (f"{text!r} was answered with a capability statement instead of being "
         "done — a deflection, which is the same failure pointing the other way")


def test_the_general_question_still_gets_the_general_inventory(flags):
    """Registered after capabilities on purpose: "what can you do" is not this."""
    flags()
    assert _route("what can you do?") == "self_knowledge.capabilities"
    assert _route("what can you do to photos?") == "apelles.photo_capabilities"


# ── teeth: the route cannot survive losing the section ───────────────────────
def test_removing_the_section_does_not_leave_it_improvising(flags, monkeypatch):
    """Mutation: delete the text_edit section and confirm the route falls back to
    the inventory rather than inventing a sentence of its own."""
    flags()
    real = server._self_knowledge_sections
    monkeypatch.setattr(server, "_self_knowledge_sections",
                        lambda: [s for s in real() if s[0] != "text_edit"])
    out = server.text_editing_answer()
    assert out == server.capability_answer(), \
        "with the section gone the route produced prose from somewhere else"


def test_no_hand_written_capability_sentence_in_the_route():
    """Collision grep, by AST. Every string literal in the route must be a short
    key, not prose — a sentence here is a second author for one fact, and the
    week's whole lesson is that two authors of one capability drift."""
    import ast
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "text_editing_answer")
    docnode = fn.body[0].value if isinstance(fn.body[0], ast.Expr) else None
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node is docnode:
                continue
            assert len(node.value) <= 12 and " " not in node.value, \
                f"the route writes its own prose: {node.value[:60]!r}"


def test_the_section_is_unconditional():
    """The prose half has nothing to do with the image edit lane. It went missing
    for exactly that reason — the only text paragraph she had was gated behind a
    picture flag, so with the lane off she would have had nothing at all."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index('out.append(("text_edit"')
    # walk back to the nearest block statement and confirm it is not a flag test
    head = src[:i]
    for ln in reversed(head.splitlines()):
        s = ln.strip()
        if s.startswith("if ") or s.startswith("elif "):
            assert "ENABLED" not in s, \
                f"the text_edit section is gated behind a flag: {s}"
            break
        if s.startswith("out.append(") or s.startswith("return "):
            break


# ── no model is consulted, so the answer cannot depend on which brain is loaded ─
def test_the_dispatch_never_awaits_anything():
    """Structural proof of brain-independence: the branch that answers this is
    synchronous and reads config. ph3b3-chat invented the picture answer and
    hermes3 invents a breakfast; neither of them is asked here."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index('if claim.handler == "text_editing":')
    branch = src[i:src.index("\n", src.index("text_editing_answer()", i))]
    assert "await" not in branch, "the answer waits on something"
    assert "generate" not in branch and "ollama" not in branch.lower()


def test_the_claim_is_resolved_above_the_triage_gate():
    """It shares the early-claim hop with every other deterministic answer. Below
    the gate it would be held, which is how this week started."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert src.index("_early_claim = intent_registry.resolve(user_msg)") < \
           src.index("_triage = (_TriagePass()")


# ── live: the incident, through the real path ────────────────────────────────
pytestmark_smoke = pytest.mark.smoke


def _env(name, default=""):
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip().startswith(f"{name}="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def _live(question, sid):
    import requests
    import urllib3
    urllib3.disable_warnings()
    s = requests.Session()
    s.verify = False
    s.auth = (_env("PH3B3_USER", "admin"), _env("PH3B3_PASSWORD"))
    r = s.post(f"https://127.0.0.1:{_env('PH3B3_PORT', '7331')}/chat", timeout=120,
               json={"message": question, "session_id": sid, "text_only": True})
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


def _service_up():
    try:
        import requests
        import urllib3
        urllib3.disable_warnings()
        s = requests.Session()
        s.verify = False
        s.auth = (_env("PH3B3_USER", "admin"), _env("PH3B3_PASSWORD"))
        return s.get(f"https://127.0.0.1:{_env('PH3B3_PORT', '7331')}/ready",
                     timeout=5).status_code == 200
    except Exception:
        return False


def _service_predates_this_code():
    """A running service older than server.py cannot have this route in it.

    Without this the live probes go RED on a stale service, which reads as a
    regression in the code — the exact confusion that produced three false bug
    reports about routes "being broken". A stale service is a restart, not a
    defect, and the skip reason says so.
    """
    import subprocess
    try:
        pid = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value",
                              "ph3b3"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
        started = subprocess.run(["ps", "-o", "lstart=", "-p", pid],
                                 capture_output=True, text=True,
                                 timeout=10).stdout.strip()
        if not started:
            return False
        import time as _t
        from datetime import datetime
        boot = datetime.strptime(started, "%a %b %d %H:%M:%S %Y").timestamp()
        return boot < (ROOT / "agent" / "server.py").stat().st_mtime
    except Exception:
        return False


@pytest.mark.smoke
@pytest.mark.skipif(not _service_up(), reason="ph3b3 service not reachable")
@pytest.mark.skipif(_service_predates_this_code(),
                    reason="the running service predates this code — "
                           "sudo systemctl restart ph3b3, then rerun")
@pytest.mark.parametrize("text", ["can you edit text?",
                                  "hey Phoebe, can you edit text?"])
def test_live_the_incident_phrasing_gets_the_deterministic_answer(text):
    """Equality, not a grader. If one word differs, a model touched it."""
    got = _live(text, f"smoke-te-{abs(hash(text)) % 9999}")
    assert got == server.text_editing_answer(), (
        "the live answer is not the deterministic one — a model was consulted:\n"
        f"  got:      {got[:300]}\n  expected: {server.text_editing_answer()[:300]}")


# ── a staged document outranks the capability statement ──────────────────────
def test_a_staged_document_makes_it_stand_down(flags, monkeypatch):
    """"Can you fix the text?" with a PDF staged is a request about that PDF.

    The claim still fires — it is the right shape — but the dispatch returns None
    and the turn falls through to the document lane. Without this the route
    would answer a piece of work with a description of itself.
    """
    import asyncio

    flags()
    claim = intent_registry.resolve("can you fix the text?")
    assert claim is not None and claim.handler == "text_editing"

    monkeypatch.setattr(server.kadmos, "get_pending",
                        lambda sid: {"path": "/tmp/x.pdf"})
    got = asyncio.run(server._dispatch_claim(claim, "can you fix the text?", "s1"))
    assert got is None, "it answered with a capability statement over a staged document"

    monkeypatch.setattr(server.kadmos, "get_pending", lambda sid: None)
    got = asyncio.run(server._dispatch_claim(claim, "can you fix the text?", "s1"))
    assert got == server.text_editing_answer()


# ── over-claiming is the other failure ───────────────────────────────────────
# A claim that swallows real work is the same dishonesty pointing the other way:
# she would describe herself instead of doing the thing. Swept 2026-09-25.
NEVER_CLAIMED = [
    "fix the typo in my document",
    "proofread this for me",
    "rewrite this paragraph",
    "can you edit my resume?",
    "clean up the text in this file",
    "make me a poster with readable text",
    "write me a caption for this photo",
    "can you read the text in this image?",
    "what does the sign say in this photo?",
    "tell me a story about a sign painter",
    "can you edit a video?",
    "edit the code in this script",
    "change the words on the poster",
    "what's the weather like",
    "correct me if I'm wrong",
    "can you correct my pronunciation?",
]


@pytest.mark.parametrize("text", NEVER_CLAIMED)
def test_the_route_does_not_swallow_anything_else(flags, text):
    flags()
    claim = intent_registry.resolve(text)
    assert getattr(claim, "handler", None) != "text_editing", \
        f"{text!r} was answered with a capability statement about text editing"
