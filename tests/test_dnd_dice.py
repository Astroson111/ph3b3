"""The roll floor must be real, bounded, and auditable.

These tests exist because the whole point of dnd_dice is that numbers come from
Python and not from a model's imagination — so the parser has to be exactly right
about odds (keep-highest is not keep-lowest, advantage is not two separate rolls)
and has to REFUSE anything it can't read rather than quietly rolling something else.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules"))

import dnd_dice
from dnd_dice import DiceError, check, roll


class SeqRNG:
    """Deterministic stand-in: hands back a fixed sequence, clamped to the die."""
    def __init__(self, values):
        self.values = list(values)
        self.i = 0

    def randint(self, lo, hi):
        v = self.values[self.i % len(self.values)]
        self.i += 1
        return max(lo, min(hi, v))


# ── parsing + arithmetic ─────────────────────────────────────────────────────
def test_single_die_is_in_range():
    for _ in range(200):
        r = roll("d20")
        assert 1 <= r.total <= 20
        assert len(r.groups) == 1 and r.groups[0].count == 1


def test_count_sides_and_modifier():
    r = roll("2d6+3", rng=SeqRNG([4, 5]))
    assert r.total == 12                      # 4 + 5 + 3
    assert r.modifier == 3
    assert r.groups[0].rolls == [4, 5]


def test_negative_modifier_and_multiple_groups():
    r = roll("1d8+1d6-2", rng=SeqRNG([8, 6]))
    assert r.total == 12                      # 8 + 6 - 2
    assert r.modifier == -2
    assert len(r.groups) == 2


def test_subtracted_dice_group():
    r = roll("2d6-1d4", rng=SeqRNG([6, 6, 3]))
    assert r.total == 9                       # 12 - 3


def test_percentile():
    r = roll("d%", rng=SeqRNG([73]))
    assert r.groups[0].sides == 100 and r.total == 73


def test_whitespace_and_case_ignored():
    assert roll("  2D6 + 1 ", rng=SeqRNG([1, 1])).total == 3


# ── keep-highest / keep-lowest: the odds must be exact ───────────────────────
def test_keep_highest_drops_the_lowest():
    r = roll("4d6kh3", rng=SeqRNG([6, 1, 5, 3]))
    g = r.groups[0]
    assert sorted(g.kept, reverse=True) == [6, 5, 3]
    assert g.dropped == [1]
    assert r.total == 14


def test_keep_low_keeps_the_worst():
    r = roll("2d20kl1", rng=SeqRNG([19, 4]))
    assert r.total == 4


def test_bare_kh_means_keep_one():
    r = roll("2d20kh", rng=SeqRNG([7, 18]))
    assert r.total == 18


def test_dropped_dice_are_still_reported():
    # Auditability: a player must be able to see what was discarded.
    r = roll("4d6kh3", rng=SeqRNG([6, 1, 5, 3]))
    assert r.groups[0].rolls == [6, 1, 5, 3]
    assert "~~1~~" in r.groups[0].describe()


# ── advantage / disadvantage ─────────────────────────────────────────────────
def test_advantage_takes_the_higher():
    assert check(advantage=True, rng=SeqRNG([3, 17])).total == 17


def test_disadvantage_takes_the_lower():
    assert check(disadvantage=True, rng=SeqRNG([3, 17])).total == 3


def test_advantage_and_disadvantage_cancel():
    # 5e: one of each is a flat d20, not two rolls.
    r = check(advantage=True, disadvantage=True, rng=SeqRNG([11, 20]))
    assert r.total == 11
    assert r.groups[0].count == 1


def test_check_applies_modifier():
    assert check(modifier=5, rng=SeqRNG([10])).total == 15
    assert check(modifier=-2, rng=SeqRNG([10])).total == 8


# ── crits: meaningful only for a single deciding d20 ─────────────────────────
def test_natural_twenty_and_one():
    assert roll("1d20", rng=SeqRNG([20])).crit == "nat20"
    assert roll("1d20", rng=SeqRNG([1])).crit == "nat1"


def test_modified_d20_still_reports_the_natural_face():
    r = roll("1d20+7", rng=SeqRNG([20]))
    assert r.crit == "nat20" and r.total == 27


def test_damage_roll_containing_a_twenty_is_not_a_crit():
    r = roll("8d6", rng=SeqRNG([6]))
    assert r.crit == ""


def test_advantage_crit_reads_the_kept_die():
    assert check(advantage=True, rng=SeqRNG([1, 20])).crit == "nat20"
    assert check(disadvantage=True, rng=SeqRNG([1, 20])).crit == "nat1"


# ── refusal: never silently roll something else ──────────────────────────────
@pytest.mark.parametrize("bad", [
    "", "   ", "fireball", "d", "2d", "d0", "d1", "1d20+", "+", "2d6++1", "abc",
])
def test_malformed_expressions_are_refused(bad):
    with pytest.raises(DiceError):
        roll(bad)


def test_bare_number_is_not_a_roll():
    with pytest.raises(DiceError):
        roll("5")


def test_abuse_limits():
    with pytest.raises(DiceError):
        roll(f"{dnd_dice.MAX_DICE_PER_GROUP + 1}d6")
    with pytest.raises(DiceError):
        roll(f"1d{dnd_dice.MAX_SIDES + 1}")
    with pytest.raises(DiceError):
        roll("+".join(["1d6"] * (dnd_dice.MAX_GROUPS + 1)))


def test_cannot_keep_more_than_rolled():
    with pytest.raises(DiceError):
        roll("2d20kh3")


# ── the RNG is real ──────────────────────────────────────────────────────────
def test_default_rng_is_not_seedable_and_varies():
    # If this ever becomes constant, the floor has silently stopped being a floor.
    seen = {roll("1d1000").total for _ in range(60)}
    assert len(seen) > 5
