"""The output check must not be starved by the thing it guards.

Measured 2026-09-23 on the Qwen lane: comfy_free() returned before the driver
had reclaimed, llava got "cudaMalloc failed: out of memory", _minor_check failed
closed exactly as designed, that triggered the corroboration step, and the second
opinion false-positived on a sign reading FRESH BREAD DAILY. BREACH_LOG.txt
recorded `corroborated=True` against a bakery sign.

Two faults, two fixes:
  A  wait for the card after comfy_free, because the free is asynchronous
  B  an unavailable judge is a refusal but NOT a breach — the distinction
     source_minor_check has always made and output_minor_check discarded
"""
import ast
import asyncio
import pathlib

import pytest

import modules.morpheus as m

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = (REPO / "modules" / "morpheus.py").read_text()


def _fn_src(name):
    t = ast.parse(SRC)
    fn = next(n for n in ast.walk(t)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == name)
    return ast.unparse(fn)


# ---------- A: the settle-wait -------------------------------------------
def test_the_free_is_waited_for_before_the_judge():
    body = _fn_src("fetch_and_save")
    assert "wait_for_card" in body, "comfy_free is still not waited for"
    assert body.index("comfy_free") < body.index("wait_for_card"), \
        "waiting before freeing accomplishes nothing"
    assert body.index("wait_for_card") < body.index("_minor_check"), \
        "the wait must come BEFORE the judge, which is the point"


def test_wait_returns_as_soon_as_there_is_room(monkeypatch):
    calls = []
    monkeypatch.setattr(m, "JUDGE_NEED_MB", 5000)
    # morpheus does `import herakles`, which under this sys.path is a DIFFERENT
    # module object from `modules.herakles` — same file, two entries. Patch the
    # one the code under test will actually reach.
    import herakles as hk
    monkeypatch.setattr(hk, "free_mib", lambda: calls.append(1) or 9000)
    got = asyncio.run(m.wait_for_card(5000, timeout=5))
    assert got == 9000 and len(calls) == 1, "it kept polling past success"


def test_wait_gives_up_rather_than_hanging(monkeypatch):
    """A timeout must not cost the render — the check downstream is still
    fail-closed either way."""
    import herakles as hk
    monkeypatch.setattr(hk, "free_mib", lambda: 100)
    got = asyncio.run(m.wait_for_card(5000, timeout=0.6))
    assert got == 100, "it should return the figure it settled on, not raise"


def test_wait_never_raises_when_the_card_cannot_be_read(monkeypatch):
    import herakles as hk
    def boom(): raise RuntimeError("nvidia-smi gone")
    monkeypatch.setattr(hk, "free_mib", boom)
    assert asyncio.run(m.wait_for_card(5000, timeout=1)) == -1


# ---------- B: unavailable is not a breach -------------------------------
def _unavailable_branch():
    """The `if` whose CONDITION actually tests the unavailable reason.

    Structural, not textual. An earlier version of this test compared string
    positions in the unparsed source, and `if blocked and unavailable:` ->
    `if False:` sailed straight through, because the word still appeared in the
    assignment above. Position in a string is not a guard.
    """
    t = ast.parse(SRC)
    fn = next(n for n in ast.walk(t)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "fetch_and_save")
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            names = {x.id for x in ast.walk(node.test) if isinstance(x, ast.Name)}
            if "unavailable" in names:
                return node
    return None


def test_an_unavailable_judge_does_not_reach_the_breach_log():
    branch = _unavailable_branch()
    assert branch is not None, (
        "no branch actually TESTS the unavailable reason — an OOM and a child "
        "verdict are the same bit again, which is what recorded a breach "
        "against a bakery sign")
    inner = ast.unparse(ast.Module(body=branch.body, type_ignores=[]))
    for forbidden in ("output_corroborates", "log_breach", "handle_output_breach"):
        assert forbidden not in inner, (
            f"the unavailable branch reaches {forbidden} — an unrunnable judge "
            f"must not be recorded as a safety finding")


def test_unavailable_still_refuses():
    """Fail-closed is untouched. These bytes already rendered; there is no
    'try again' to offer."""
    branch = _unavailable_branch()
    assert branch is not None
    assert any(isinstance(n, ast.Raise) for n in ast.walk(branch)), \
        "an unavailable judge stopped refusing"


def test_the_two_refusals_say_different_things():
    """One says a judge looked and objected. The other says none could look."""
    assert m._OUTPUT_REFUSAL != m._OUTPUT_UNAVAILABLE
    assert "child-safety" in m._OUTPUT_REFUSAL
    assert "child" not in m._OUTPUT_UNAVAILABLE.lower(), \
        "an unavailable judge must not be phrased as a child-safety finding"
    assert "could not run" in m._OUTPUT_UNAVAILABLE


def test_source_and_output_now_agree_that_unavailable_is_distinct():
    """source_minor_check always raised SafetyCheckUnavailable. The output path
    discarded the reason, and that asymmetry was the latent bug."""
    assert "unavailable" in _fn_src("source_minor_check")
    assert "unavailable" in _fn_src("fetch_and_save")


def test_a_real_child_verdict_still_corroborates_and_logs():
    """The fix must not make a genuine finding quieter."""
    body = _fn_src("fetch_and_save")
    assert "output_corroborates" in body and "handle_output_breach" in body
    assert "log_breach" in body


# ---------- the exit exam is not skippable -------------------------------
# Herakles v1.1 evicts EVERY Ollama model before a render, and llava and
# ph3b3-chat are the floor's judges. So the output check must now reload a ~5 GB
# judge into a card still carrying ComfyUI's tail. The sequence is load-bearing:
#   drop the tail -> wait for the driver -> judge -> stamp -> write
def test_the_sequence_is_tail_then_wait_then_judge_then_stamp_then_write():
    body = _fn_src("fetch_and_save")
    order = ["comfy_free", "wait_for_card", "_minor_check", "maybe_stamp",
             "write_bytes"]
    pos = [body.index(x) for x in order]
    assert pos == sorted(pos), (
        "the post-render sequence is out of order: "
        + ", ".join(f"{n}@{p}" for n, p in zip(order, pos)))


def test_nothing_is_stamped_before_it_is_judged():
    """A flagged render must be destroyed before anything is written onto it."""
    body = _fn_src("fetch_and_save")
    assert body.index("_minor_check") < body.index("maybe_stamp"), \
        "the watermark goes on before the exit exam"


def test_the_only_write_is_after_the_check():
    """One write, and it is downstream of the gate. A second write path would
    be a way for an unjudged render to reach disk."""
    t = ast.parse(SRC)
    fn = next(n for n in ast.walk(t)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "fetch_and_save")
    writes = [n for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "write_bytes"]
    assert len(writes) == 1, f"fetch_and_save has {len(writes)} write paths"


def test_the_check_returns_a_verdict_rather_than_being_assumed():
    """_minor_check's result must actually be consumed — both halves of it."""
    body = _fn_src("fetch_and_save")
    assert "blocked, unavailable" in body, \
        "the check's verdict is no longer unpacked; something is assuming it"
    assert "if blocked" in body, "the verdict is computed and ignored"


def test_evicting_the_judges_is_survivable_by_design():
    """Herakles evicts llava and ph3b3-chat with everything else. That is fine
    ONLY because the judge reloads after the tail is dropped — this test exists
    so the coupling is written down where someone changing either side sees it."""
    hk_src = (REPO / "modules" / "herakles.py").read_text()
    assert "evict_ollama_all" in hk_src, \
        "the eviction tier changed; re-check that the judge can still reload"
    body = _fn_src("fetch_and_save")
    assert "wait_for_card" in body, \
        "the judges are evicted pre-render and nothing waits for room to reload one"
