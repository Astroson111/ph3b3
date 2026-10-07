"""Conditional tool exposure: every tool still reachable, mention never fires.

WHY. Measured 2026-10-04 against ph3b3-chat on Ollama 0.24.0, by
prompt_eval_count with and without the `tools` key: the 105 schemas cost
**9,010 tokens of a 16,384 window on every single turn**. Core alone is 1,819.
An over-long prompt is not refused — Ollama discards the START and still reports
done_reason 'stop' — so the first thing that bloat spends is her system prompt,
with no error. Cutting exposure is a correctness fix, not housekeeping.

WHAT THESE GUARD. Three things, in the brief's words: every tool reachable by its
intended trigger, false-trigger cases stay quiet, and self-knowledge stays whole
with groups unloaded. The third is the one that would be easy to break without
noticing, because nothing fails — she would simply start saying she cannot do
things she can.
"""
import ast
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))
import tool_groups as tg                                    # noqa: E402

SERVER = ROOT / "agent" / "server.py"


def _tools():
    """The table as the SERVER builds it, not as the literal reads.

    agent/server.py does `TOOLS += ATALANTA_TOOLS` and `TOOLS += CAMERA_TOOLS`
    after the literal. Parsing only the literal saw 105 tools while the running
    server advertised from 111, so six tools were ungrouped and silently riding
    every turn — and the LIVE LOG caught it, not this test. Any future `TOOLS +=`
    must be added here, which the count assertion below makes impossible to miss.
    """
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    found, appended = None, []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "TOOLS":
                    found = ast.literal_eval(n.value)
                elif isinstance(t, ast.Name) and t.id in ("ATALANTA_TOOLS", "CAMERA_TOOLS"):
                    appended.append(ast.literal_eval(n.value))
        # `TOOLS += X` — catch a new one rather than let it ride ungrouped.
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) \
                and n.target.id == "TOOLS" and isinstance(n.value, ast.Name):
            if n.value.id not in ("ATALANTA_TOOLS", "CAMERA_TOOLS"):
                raise AssertionError(
                    f"agent/server.py now does TOOLS += {n.value.id}; add it to "
                    "_tools() here and group its tools in modules/tool_groups.py")
    assert found is not None, "TOOLS literal not found in agent/server.py"
    for extra in appended:
        found = found + extra
    return found


TOOLS = _tools()
NAMES = frozenset(t["function"]["name"] for t in TOOLS)

# One phrase per group that a person would plausibly say. Doubles as the
# reachability table: if a group has no phrase here, the test below fails.
PHRASES = {
    "photo":    "crop this photo and export it",
    "resume":   "tidy up my resume for this job post",
    "network":  "scan the network and tell me who is on it",
    "security":  "check if that password was in a breach",
    "ghost":    "start a ghost investigation",
    "media":    "play some music on spotify",
    "stories":  "tell me a story from the shelf",
    "lookup":   "find me a recipe for soup",
    "machine":  "what's the gpu doing",
    "sports":   "what was the score in the game tonight",
    "camera_ctl": "pan the camera to the left",
    "translate": "translate thank you into Spanish",
    "capture":  "take a photo of the room",
    "memory":   "do you remember what I told you about the shed",
    "web":      "search the web for the latest news",
}


# ── completeness ─────────────────────────────────────────────────────────────

def test_every_tool_is_grouped_on_purpose():
    """An ungrouped tool is exposed always — safe, but it should be deliberate."""
    assert tg.ungrouped(NAMES) == set(), (
        "new tools are not in CORE or any group; they will ride every turn: "
        f"{sorted(tg.ungrouped(NAMES))}")


def test_no_group_names_a_tool_that_does_not_exist():
    claimed = set(tg.CORE)
    for names in tg.GROUPS.values():
        claimed |= names
    assert claimed - NAMES == set(), f"typos in tool_groups: {sorted(claimed - NAMES)}"


def test_every_group_has_a_trigger():
    assert set(tg.GROUPS) == set(tg.TRIGGERS), (
        "a group with no trigger can never load: "
        f"{set(tg.GROUPS) ^ set(tg.TRIGGERS)}")


# ── reachability: the brief's first verify item ──────────────────────────────

@pytest.mark.parametrize("group,phrase", sorted(PHRASES.items()))
def test_each_group_loads_on_its_phrase(group, phrase):
    assert group in tg.groups_for_turn(phrase), f"{phrase!r} did not load {group}"


def test_every_single_tool_is_reachable_by_some_trigger():
    """No tool may be unreachable. Core is always on; the rest need a phrase."""
    reachable = set(tg.CORE)
    for phrase in PHRASES.values():
        reachable |= tg.exposed_names(NAMES, phrase)
    assert NAMES - reachable == set(), f"unreachable: {sorted(NAMES - reachable)}"


@pytest.mark.parametrize("text", [
    "what is the capital of Peru?",
    "what does photosynthesis mean?",
    "how many days in February",
])
def test_a_plain_factual_question_gets_no_retrieval_tools(text):
    """The battery's finding, pinned.

    Asked for the capital of Peru with web_search and recall_memory in core,
    she chained recall_memory -> web_search -> recall_memory three passes out of
    three. A smaller menu makes what remains more salient, so retrieval has to
    be asked for. She knows what the capital of Peru is.
    """
    exposed = tg.exposed_names(NAMES, text)
    for tool in ("web_search", "recall_memory", "recall", "search_notes"):
        assert tool not in exposed, f"{tool} offered for {text!r}"


def test_she_can_still_be_asked_to_search_and_to_remember():
    assert "web_search" in tg.exposed_names(NAMES, "search the web for tide times")
    assert "recall_memory" in tg.exposed_names(
        NAMES, "do you remember what I said about the shed")


def test_storing_a_memory_never_needs_a_trigger():
    """Failing to keep something she was asked to keep is the worse error."""
    exposed = tg.exposed_names(NAMES, "anything at all")
    assert {"remember", "remember_fact", "add_note"} <= exposed


def test_core_rides_a_bare_social_turn():
    exposed = tg.exposed_names(NAMES, "how was your morning")
    assert (tg.CORE & NAMES) <= exposed
    assert len(exposed) < len(NAMES)          # and it is actually a reduction


# ── the brief's second verify item: mention must not fire ───────────────────

@pytest.mark.parametrize("text", [
    "I did a web search yesterday",
    "I ran a network scan last week",
    "yesterday I edited a photo of the dog",
    "we played some music earlier",
    "I already checked the gpu",
    "I tried a recipe the other day",
    "last night I read a story to my niece",
    "I used nmap a while back",
])
def test_talking_about_a_capability_does_not_load_it(text):
    assert tg.groups_for_turn(text) == set(), f"{text!r} fired {tg.groups_for_turn(text)}"


@pytest.mark.parametrize("text,group", [
    ("scan the network", "network"),
    ("did you scan the network?", "network"),
    ("can you crop this photo", "photo"),
    ("play some music", "media"),
])
def test_an_actual_request_still_fires_even_in_past_tense(text, group):
    """The veto needs a first-person or past-TIME frame. "did YOU scan" is a
    request about her, not the user narrating themselves, and must still load."""
    assert group in tg.groups_for_turn(text)


def test_ui_state_is_a_fact_and_ignores_the_veto():
    """A photo really is open. The sentence cannot talk it closed."""
    g = tg.groups_for_turn("I edited a photo yesterday", {"photo_open": True})
    assert "photo" in g


def test_unknown_tab_contributes_nothing_rather_than_guessing():
    assert tg.groups_for_turn("", {"tab": "not-a-real-tab"}) == set()


# ── the brief's third verify item: self-knowledge is independent ────────────

def test_self_knowledge_never_reads_the_exposed_set():
    """She must not claim she lacks a capability because its group is unloaded.

    Static check on the source: the self-knowledge builders must not reference
    the per-turn exposure at all. One voice, from live config.
    """
    src = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    guarded = {"_self_knowledge_sections", "_self_knowledge",
               "_fleet_self_block", "_self_vocabulary"}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in guarded:
            body = ast.dump(node)
            for forbidden in ("tools_for_turn", "exposed_names", "groups_for_turn",
                              "ALL_TOOL_NAMES"):
                assert forbidden not in body, (
                    f"{node.name} reads {forbidden} — self-knowledge must come "
                    "from live config, not from this turn's tool exposure")


def test_the_exposure_module_is_not_consulted_for_capability_claims():
    """tool_groups must not be imported by anything that composes self-claims."""
    assert "tool_groups" not in (ROOT / "modules" / "no_access.py").read_text()


# ── budget, so a regression in schema size is visible ───────────────────────

def test_core_is_a_small_fraction_of_the_table():
    size = {t["function"]["name"]: len(json.dumps(t)) for t in TOOLS}
    total = sum(size.values())
    core = sum(size[n] for n in tg.CORE & NAMES)
    assert core / total < 0.30, (
        f"core has grown to {core/total:.0%} of the schema table; the measured "
        "win was core=19% (1,819 tokens vs 9,010)")
