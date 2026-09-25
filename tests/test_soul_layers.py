"""Her soul loads in two layers, and the operational rules are in the tracked one.

THE PROBLEM THIS CLOSES. soul/soul.md is gitignored — correctly, it is the
installation-specific layer — and its own header has promised since August that
"the live soul.md loaded at runtime will reflect the specific installation".
That promise went unmet for months: the loader read ONLY the ignored file, so
that file had to be a complete copy of the public text to work at all, and any
rule written into it lived nowhere else.

Measured 2026-09-25: the ignored soul.md differed from the tracked
soul_public.md by exactly ONE line — rule 9, written that afternoon, which had
measurably ended tool narration across four battery cells. One line of proven
operational behaviour, unversioned, unreviewed, and absent from every clone. A
commit message that day (7c59bee) claimed it shipped; it had not, because
`git add -A` cannot stage an ignored file.

So: base is tracked and carries the rules, personal is an optional overlay, and
a clone with no personal layer boots COMPLETE. That last case is the one that
had no test, which is why nobody noticed for months.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

from agent import server  # noqa: E402

RULE9 = "I must never narrate my own plumbing"


# ── durability: the rule may never retreat into ignored territory ────────────
def test_rule_nine_lives_in_the_TRACKED_layer():
    """THE durability test. Red if rule 9 ever moves back to the ignored file —
    which is where it spent its first afternoon, in no commit, on one disk."""
    assert server.SOUL_BASE.exists(), "the tracked base layer is missing"
    assert RULE9 in server.SOUL_BASE.read_text(encoding="utf-8"), \
        "rule 9 is not in the tracked soul — it has retreated to ignored territory"


def test_rule_nine_keeps_BOTH_halves():
    """Rule 9 governs manner and occasion, and it has two sides. Unscoped, it
    said only "never narrate my own plumbing" — which collides head-on with the
    Sept 23 inventory license in the derived block, where capability questions
    are commanded to get plain, deflection-free answers. An always-answer and a
    never-narrate cannot both be true in one prompt; an 8B model resolves that
    per-turn, unpredictably. And the operator explains her machinery to viewers
    on stream, so the collision is the format, not a corner case.

    Both halves are asserted because losing either one is a different fault:
    drop the fence and unsolicited tool narration returns (four battery cells
    measured it); drop the candor and she starts refusing to explain herself to
    a room of people who came to watch exactly that.
    """
    txt = server.SOUL_BASE.read_text(encoding="utf-8")
    assert "narrate my own plumbing unprompted" in txt, \
        "the UNPROMPTED fence is gone — unsolicited tool narration will return"
    assert "asked directly how I work" in txt and "explain gladly and plainly" in txt, \
        "the on-request CANDOR clause is gone — she will start refusing to explain herself"


def test_rule_nine_defers_to_the_derived_block_for_CONTENT():
    """One voice, one authority. The rule governs manner and occasion; what she
    can actually do is derived from config. A rule that started listing engines
    would be a third place for capability claims to drift."""
    txt = server.SOUL_BASE.read_text(encoding="utf-8")
    # Select the rule's own line. An earlier version sliced backwards from the
    # match and landed in rule 8.
    rule9 = next(l for l in txt.splitlines() if RULE9 in l)
    assert "from my own config" in rule9, \
        "rule 9 does not defer to the derived block for capability content"
    for claim in ("qwen", "sdxl", "engine", "watermark", "25 second", "video clip"):
        assert claim not in rule9.lower(), \
            f"rule 9 names a capability ({claim!r}) — content belongs in the derived block"


def test_the_tracked_layer_is_actually_tracked_by_git():
    """'Tracked' is a claim about git, so ask git."""
    out = subprocess.run(["git", "ls-files", "--error-unmatch",
                          str(server.SOUL_BASE.relative_to(ROOT))],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, f"{server.SOUL_BASE.name} is not tracked by git"


def test_the_hard_rules_survived_the_split():
    """The split is plumbing. Nothing may be lost in the move."""
    txt = server.SOUL_BASE.read_text(encoding="utf-8")
    for marker in ("## Hard Rules", "## Identity", "## What I Know About Myself",
                   "never fabricate what my camera sees", "never pretend to be human"):
        assert marker in txt, f"the tracked soul lost {marker!r}"


# ── the privacy boundary is itself under test ────────────────────────────────
def test_the_personal_layer_is_still_gitignored():
    """The one hard constraint: the personal layer must never touch git,
    including by classification error. Asserted, not assumed — and it holds for
    a path that does not currently exist, which is the state a clone is in."""
    rel = str(server.SOUL_LOCAL.relative_to(ROOT))
    out = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
    assert out.returncode == 0, f"{rel} is NOT gitignored — the personal layer is exposed"


def test_the_personal_layer_is_not_tracked():
    out = subprocess.run(["git", "ls-files", "--error-unmatch",
                          str(server.SOUL_LOCAL.relative_to(ROOT))],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode != 0, "the personal soul layer is tracked by git"


# ── assembly order, and the cloner case ──────────────────────────────────────
def test_order_is_tracked_then_personal(tmp_path, monkeypatch):
    base = tmp_path / "base.md"
    local = tmp_path / "local.md"
    base.write_text("BASE-RULES", encoding="utf-8")
    local.write_text("PERSONAL-VOICE", encoding="utf-8")
    monkeypatch.setattr(server, "SOUL_BASE", base)
    monkeypatch.setattr(server, "SOUL_LOCAL", local)
    out = server.load_soul()
    assert out.index("BASE-RULES") < out.index("PERSONAL-VOICE"), \
        "the personal layer is being read before the rules"


def test_a_clone_with_NO_personal_layer_boots_complete(tmp_path, monkeypatch):
    """THE test that did not exist, and whose absence let 'reflect the specific
    installation' go unmet for months. A fresh clone has no soul.md at all."""
    base = tmp_path / "base.md"
    base.write_text("BASE-RULES " + RULE9, encoding="utf-8")
    monkeypatch.setattr(server, "SOUL_BASE", base)
    monkeypatch.setattr(server, "SOUL_LOCAL", tmp_path / "does_not_exist.md")
    out = server.load_soul()
    assert "BASE-RULES" in out and RULE9 in out
    assert "You are Ph3b3, a local AI assistant" not in out, \
        "it fell back to the stub instead of loading the tracked soul"


def test_an_empty_personal_layer_adds_nothing(tmp_path, monkeypatch):
    base = tmp_path / "base.md"
    local = tmp_path / "local.md"
    base.write_text("BASE", encoding="utf-8")
    local.write_text("   \n\n  ", encoding="utf-8")
    monkeypatch.setattr(server, "SOUL_BASE", base)
    monkeypatch.setattr(server, "SOUL_LOCAL", local)
    assert server.load_soul() == "BASE"


def test_both_missing_still_yields_a_usable_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SOUL_BASE", tmp_path / "nope.md")
    monkeypatch.setattr(server, "SOUL_LOCAL", tmp_path / "also_nope.md")
    assert "Ph3b3" in server.load_soul()


# ── one voice: the split must not create a third home for capability claims ──
def test_the_tracked_soul_makes_no_capability_claims():
    """Capabilities are DERIVED (_self_knowledge_sections). A rule file that
    starts listing engines is a third place for them to drift."""
    txt = server.SOUL_BASE.read_text(encoding="utf-8").lower()
    for claim in ("qwen", "sdxl", "comfyui", "image engine", "25 seconds",
                  "watermark", "num_ctx", "ollama"):
        assert claim not in txt, \
            f"the tracked soul names a capability ({claim!r}) — that belongs in the derived block"
