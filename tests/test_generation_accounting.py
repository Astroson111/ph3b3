"""A cut reply is detected and never delivered as a complete one.

WHY THESE EXIST. Ollama returns done_reason, prompt_eval_count and eval_count on
every call and the chat path discarded all three, so a reply that stopped early
was indistinguishable from one that finished. 2,325 recorded replies could not be
audited for truncation because the evidence was thrown away at the source.

THE TWO CUT CONDITIONS ARE NOT THE SAME EVENT, measured on Ollama 0.24.0 with
ph3b3-chat on 2026-10-04:

  prompt-overflow  prompt_eval_count lands exactly ON num_ctx and the START of
                   the prompt is discarded — her system prompt first. done_reason
                   is 'stop'. A secret planted at the head of a 1,500-token
                   system message with num_ctx=512 was simply gone, silently.
                   A done_reason check alone CANNOT see this one, which is why
                   the ruling widened the condition.

  length           done_reason == 'length'. With num_ctx=256 and no num_predict
                   the model emitted 2,560 tokens, shifting the window, so this
                   arrives late and degraded rather than neatly truncated.

agent/server.py is not importable (module-level side effects), so the helpers are
extracted from the real source by AST. That is deliberate: these tests exercise
the shipped text, and a rename or a rewrite fails them loudly instead of leaving
a green copy of deleted logic behind.
"""
import ast
import pathlib

import pytest

SERVER = pathlib.Path(__file__).resolve().parents[1] / "agent" / "server.py"
WANTED = ("_gen_cut_reason", "_trim_for_retry")


def _load_helpers():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    found = {n.name: n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name in WANTED}
    missing = [w for w in WANTED if w not in found]
    assert not missing, f"helpers gone from agent/server.py: {missing}"
    ns = {}
    exec(compile(ast.Module(body=[found[w] for w in WANTED], type_ignores=[]),
                 "<server-helpers>", "exec"), ns)
    return ns


HELPERS = _load_helpers()
cut_reason = HELPERS["_gen_cut_reason"]
trim = HELPERS["_trim_for_retry"]


# ── the detector ─────────────────────────────────────────────────────────────

def test_prompt_overflow_is_caught_even_though_ollama_says_stop():
    """The dangerous case. done_reason lies by omission; the counter does not."""
    assert cut_reason({"done_reason": "stop", "prompt": 16384,
                       "eval": 120, "num_ctx": 16384}) == "prompt-overflow"


def test_prompt_overflow_caught_when_over_as_well_as_exactly_on():
    assert cut_reason({"done_reason": "stop", "prompt": 16400,
                       "num_ctx": 16384}) == "prompt-overflow"


def test_length_is_caught():
    assert cut_reason({"done_reason": "length", "prompt": 900,
                       "eval": 2560, "num_ctx": 16384}) == "length"


def test_a_clean_generation_is_not_flagged():
    assert cut_reason({"done_reason": "stop", "prompt": 11000,
                       "eval": 240, "num_ctx": 16384}) is None


def test_overflow_outranks_length_so_the_report_names_the_real_cause():
    assert cut_reason({"done_reason": "length", "prompt": 16384,
                       "num_ctx": 16384}) == "prompt-overflow"


def test_unknown_window_does_not_invent_an_overflow():
    """num_ctx missing means we cannot know; claiming overflow would be a guess."""
    assert cut_reason({"done_reason": "stop", "prompt": 11000, "num_ctx": 0}) is None


@pytest.mark.parametrize("meta", [{}, {"done_reason": None}, {"prompt": None, "num_ctx": None}])
def test_absent_fields_never_raise(meta):
    assert cut_reason(meta) is None


# ── the retry's message list ────────────────────────────────────────────────

BASE = [
    {"role": "system", "content": "SOUL"},
    {"role": "user", "content": "u1"},
    {"role": "assistant", "content": "a1"},
    {"role": "user", "content": "u2"},
    {"role": "assistant", "content": "a2"},
    {"role": "user", "content": "u3"},
]


def test_system_prompt_survives_the_trim_and_stays_first():
    """It is the thing overflow destroys; a retry without it repeats the fault."""
    out = trim(BASE)
    assert out[0]["role"] == "system" and out[0]["content"] == "SOUL"


def test_trim_actually_shortens():
    out = trim(BASE, keep=2)
    assert len(out) < len(BASE)
    assert out[-1]["content"] == "u3"          # the live question is kept


def test_no_tool_role_survives_so_the_retry_cannot_re_fire_a_tool():
    msgs = BASE + [{"role": "tool", "content": "weather: 9C"}]
    out = trim(msgs)
    assert all(m["role"] != "tool" for m in out)


def test_the_last_tool_result_is_carried_forward_as_text():
    """Retrying without what she looked up would answer from nothing, confidently."""
    msgs = BASE + [{"role": "tool", "content": "weather: 9C and raining"}]
    out = trim(msgs)
    assert any("9C and raining" in (m.get("content") or "") for m in out)


def test_the_live_question_stays_last_even_with_a_tool_result():
    msgs = BASE + [{"role": "tool", "content": "weather: 9C"}]
    out = trim(msgs)
    assert out[-1]["content"] == "u3"


def test_empty_history_does_not_explode():
    assert trim([]) == []
