"""Every HEAVY_MODEL call shares one context window. A second one costs a reload.

THE FAULT THIS CLOSES. Ollama cannot hold one model at two context sizes. Ask
for the same model at a different num_ctx and it tears the runner down and
rebuilds it — while the model stays "loaded", so `ollama ps` still shows it and
nothing looks wrong.

Measured 2026-10-04 from ollama's own log, on every single turn she answered:

    load KvSize:4096   -> loaded runners count=1     triage  (no num_ctx -> default)
    load KvSize:16384  -> loaded runners count=1     chat    (num_ctx 16384)
    load KvSize:4096   -> loaded runners count=1     triage
    load KvSize:16384  -> loaded runners count=1     chat

~1.25 s per rebuild, ~2.6 s per turn. Invisible until [gen] logged durations and
showed load=2.05s on the first generation of every turn.

It also produced the 114 TRIAGE_FAILOPEN_EVICTED events — triage is
resident-only and fails open when the model looks absent, and the chat call was
rebuilding the runner out from under it. Those were read as a VRAM shortage and
fed a "judge + chat = 16.1 GB on a 16 GB card" theory that was wrong at the
root: triage.py and server.py read the SAME env var, so the judge IS the chat
model and there were never two models to add up.

WHY A TEST AND NOT JUST A FIX. Five separate call sites had drifted to five
different windows (16384, 8192, 4096, triage's implicit 4096, and a 2048 on the
light model). Nothing failed when they drifted, and nothing would fail if they
drifted again — the cost is latency, which no assertion was watching.
"""
import ast
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))
import model_ctx                                            # noqa: E402

# Every file that asks Ollama to generate. NOT "every file that mentions
# PH3B3_HEAVY_MODEL" — that was the first version of this list and it missed
# modules/thoth, which resolves through PH3B3_LIGHT_MODEL and still lands on the
# same model. The env var is not the identity; the resolved name is.
WATCHED = [
    ROOT / "agent" / "server.py",
    ROOT / "modules" / "triage.py",
    ROOT / "modules" / "amphion.py",
    ROOT / "modules" / "morpheus.py",
    ROOT / "modules" / "screenshot_module.py",
    ROOT / "modules" / "thoth" / "service.py",
    ROOT / "modules" / "thoth" / "__main__.py",
]

# Sites that keep a private window, each with the reason it is allowed to.
# An allowlist is how this drifts back, so every entry says why, and the
# resolved-model test below checks the claim rather than trusting it.
ALLOWED_LITERALS = {
    2048: "goodbye expression: LIGHT_MODEL, and the call already picks "
          "CHAT_NUM_CTX when LIGHT_MODEL == HEAVY_MODEL",
    4096: "resume_module draft pass: input is capped at text[:4500] upstream, so "
          "the window cannot change what it reads",
    6144: "resume_module analysis and scam_detector: inputs capped at [:4500] "
          "and [:4000], both far below this window",
    8192: "resume_module job match: inputs capped at [:5000] + [:3000]",
}

# Modules whose generate calls are deliberately left unaligned, and the reason.
# Keyed by the module attribute that names the model, so the test can resolve it.
ALLOWLISTED_MODULES = {
    "resume_module":  "occasional lane, not per-turn; inputs capped well below "
                      "its window so alignment would change nothing it reads",
    "scam_detector":  "occasional lane, not per-turn; input capped at text[:4000]",
}


def test_the_shared_constant_exists_and_is_sane():
    assert model_ctx.NUM_CTX >= 8192, (
        "a window below 8192 cannot hold the tool schemas plus her soul; "
        "server.py's CHAT_NUM_CTX comment has the measurements")


@pytest.mark.parametrize("path", WATCHED, ids=lambda p: p.name)
def test_no_unexplained_num_ctx_literal(path):
    """A hardcoded num_ctx on a HEAVY_MODEL call is a per-turn runner rebuild."""
    src = path.read_text(encoding="utf-8")
    found = {int(m.group(1)) for m in re.finditer(r'"num_ctx"\s*:\s*(\d+)', src)}
    unexplained = found - set(ALLOWED_LITERALS)
    assert not unexplained, (
        f"{path.name} hardcodes num_ctx {sorted(unexplained)}; use the shared "
        "constant (CHAT_NUM_CTX / model_ctx.NUM_CTX) or add a reasoned entry to "
        "ALLOWED_LITERALS in this test")


def test_chat_num_ctx_is_the_shared_constant_not_a_second_read():
    """server.py must not read the env var again — two reads can disagree."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert "CHAT_NUM_CTX = model_ctx.NUM_CTX" in src, \
        "CHAT_NUM_CTX should alias the shared constant"
    assert 'getenv("PH3B3_CHAT_NUM_CTX"' not in src, \
        "server.py reads PH3B3_CHAT_NUM_CTX directly; model_ctx owns that now"


def test_triage_sends_a_num_ctx_at_all():
    """The original fault was an ABSENT num_ctx, which silently defaults to 4096
    and is therefore the one case a literal-scan cannot catch."""
    src = (ROOT / "modules" / "triage.py").read_text(encoding="utf-8")
    assert "model_ctx.NUM_CTX" in src, \
        "triage must set num_ctx explicitly or ollama defaults it to 4096"


def test_every_api_chat_payload_in_server_sets_a_window():
    """An options dict with no num_ctx is the silent-default case again."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    bad = []
    for m in re.finditer(r'"options"\s*:\s*\{([^}]*)\}', src):
        body = m.group(1)
        if "num_predict" in body and "num_ctx" not in body and "temperature" in body:
            line = src[:m.start()].count("\n") + 1
            bad.append(line)
    assert not bad, (
        f"options dicts without num_ctx at server.py lines {bad} — ollama will "
        "default the window and rebuild the runner for the next differing call")


def test_amphion_imports_the_constant_before_it_uses_it():
    """Caught in review: the import first landed at line ~1707 while the use was
    at ~508. That compiles and NameErrors at runtime — ast.parse is not a gate.
    """
    src = (ROOT / "modules" / "amphion.py").read_text(encoding="utf-8")
    lines = src.splitlines()
    imp = next((i for i, l in enumerate(lines) if "import model_ctx as _model_ctx" in l), None)
    use = next((i for i, l in enumerate(lines) if "_model_ctx.NUM_CTX" in l), None)
    assert imp is not None, "amphion no longer imports the shared constant"
    assert use is not None, "amphion no longer uses the shared constant"
    assert imp < use, f"import at line {imp+1} comes after use at line {use+1}"


# ── the resolved model, not the env var ─────────────────────────────────────
# WHY THIS SECTION EXISTS. The first version of this file keyed off
# PH3B3_HEAVY_MODEL and therefore missed modules/thoth entirely, which reads
# PH3B3_LIGHT_MODEL and still resolves to ph3b3-chat — the same model as chat.
# It cost three KvSize:4096 runner rebuilds in a 36-turn battery, found only by
# correlating ollama's log against the turn log.
#
# A LIMIT WORTH STATING. pytest does not load the systemd EnvironmentFile, so
# the names resolved here are DEFAULTS and may differ from the running server's.
# That makes this check advisory about values and authoritative about structure:
# it can prove two sites share a resolution chain, and it cannot prove what the
# deployed value is. The deployed floor judge was identified from the server's
# own log line instead — "[safety] Layer B judge warm (ph3b3-chat:latest)".

def _resolve(module_name: str, attr_suffix: str = "MODEL"):
    import importlib
    try:
        m = importlib.import_module(module_name)
    except Exception:                                      # noqa: BLE001
        pytest.skip(f"{module_name} not importable in a bare test env")
    for a in dir(m):
        if a.endswith(attr_suffix) and isinstance(getattr(m, a), str):
            return getattr(m, a)
    return None


@pytest.mark.parametrize("mod,reason", sorted(ALLOWLISTED_MODULES.items()))
def test_an_allowlisted_module_is_still_a_separate_model(mod, reason):
    """An allowlist entry is only valid while the site is NOT the chat model.

    If someone points one of these at the chat model, its private window becomes
    a runner rebuild per use and the exemption stops being harmless.
    """
    import os
    heavy = os.getenv("PH3B3_HEAVY_MODEL") or os.getenv("PH3B3_MODEL")
    got = _resolve(mod)
    if not heavy or not got:
        pytest.skip("cannot resolve both names in a bare test env")
    assert got.split(":")[0] != heavy.split(":")[0], (
        f"{mod} resolves to {got}, the same model as chat ({heavy}); its "
        f"allowlist reason no longer holds — {reason}")


def test_thoth_is_aligned_because_it_resolves_to_the_chat_model():
    """Thoth reads PH3B3_LIGHT_MODEL but lands on ph3b3-chat. Regression guard
    for the exact site the env-var-keyed version of this test missed."""
    src = (ROOT / "modules" / "thoth" / "service.py").read_text(encoding="utf-8")
    assert "_model_ctx.NUM_CTX" in src, \
        "thoth/service.py must use the shared window — it is the chat model"
    src2 = (ROOT / "modules" / "thoth" / "__main__.py").read_text(encoding="utf-8")
    assert "_model_ctx.NUM_CTX" in src2, "thoth/__main__.py too"


def test_the_warm_up_calls_set_a_window():
    """A one-token warm-up still seats the model at a context size. morpheus's
    await_brain had no num_ctx and was why ph3b3-chat sat at ctx=4096 seconds
    after a restart, before any turn had run."""
    src = (ROOT / "modules" / "morpheus.py").read_text(encoding="utf-8")
    assert '"num_predict": 1, "num_ctx": _model_ctx.NUM_CTX' in src, \
        "morpheus.await_brain must seat the model at the shared window"
