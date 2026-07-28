"""The roll floor — every D&D number is generated HERE, never by the model.

The hazard this closes is the same one Metis closes for search and Ariadne closes
for résumé keywords: asked to "roll a d20", a language model will cheerfully emit
a plausible number. It has no dice. It will also, over a session, drift toward
numbers that make the story nicer — which is precisely what a player is trusting
the DM not to do. A fudged roll is not a roll.

So the split is absolute:
  * this module PRODUCES numbers (real RNG, auditable, bounded)
  * the model NARRATES numbers it is handed, and never computes one

Every roll returns the individual dice, not just the total, so a player can always
see the 17 that the DM is describing. That transparency IS the feature — it is what
makes an AI DM trustworthy rather than merely fluent.

RNG: `random.SystemRandom` (os.urandom). Deliberately NOT seedable in normal use —
nobody, including the operator, can rig a session. Tests inject their own `rng`.

Notation supported (case-insensitive, whitespace ignored):
    d20  1d20  2d6+3  4d6kh3  2d20kh1  2d20kl1  1d8+1d6+2  d%  8-2
    kh/kl take an optional count (`kh` == `kh1`).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

# Abuse limits. A chat request must not be able to ask for 10^9 dice and stall the
# event loop; these ceilings are far above any real 5e expression (the largest
# common roll is disintegrate's 10d6+40, and a level-20 fireball upcast is 13d6).
MAX_DICE_PER_GROUP = 100
MAX_SIDES          = 1000
MAX_GROUPS         = 20

_SYS_RNG = random.SystemRandom()

# One term: optional count, 'd', sides (or '%'), optional keep-high/low with count.
_DIE_RE  = re.compile(r"^(\d*)d(\d+|%)(?:(kh|kl)(\d*))?$", re.I)
_FLAT_RE = re.compile(r"^\d+$")


class DiceError(ValueError):
    """Malformed or out-of-bounds expression. Always surfaced to the player as
    plain text — never silently coerced into some other roll."""


@dataclass
class DiceGroup:
    """One NdS term and everything that happened to it."""
    count: int
    sides: int
    rolls: list                      # every die as rolled, in order
    kept: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    keep_mode: str = ""              # "kh" | "kl" | ""
    sign: int = 1

    @property
    def subtotal(self) -> int:
        return self.sign * sum(self.kept)

    def describe(self) -> str:
        """e.g. '4d6kh3: [6, 5, 3, ~1~] = 14' — dropped dice shown, not hidden."""
        if self.dropped:
            shown = ", ".join(str(r) for r in self.kept) + ", " + \
                    ", ".join(f"~~{r}~~" for r in self.dropped)
        else:
            shown = ", ".join(str(r) for r in self.kept)
        label = f"{self.count}d{self.sides}{self.keep_mode or ''}"
        return f"{label}: [{shown}] = {sum(self.kept)}"


@dataclass
class Roll:
    """A completed roll. `total` is authoritative; `groups` is the audit trail."""
    expression: str
    groups: list
    modifier: int
    total: int
    crit: str = ""                   # "nat20" | "nat1" | "" — single-d20 checks only

    def describe(self) -> str:
        parts = [g.describe() for g in self.groups]
        if self.modifier:
            parts.append(f"modifier: {self.modifier:+d}")
        body = "  ·  ".join(parts)
        crit = {"nat20": "  **NATURAL 20**", "nat1": "  **NATURAL 1**"}.get(self.crit, "")
        return f"{self.expression} → **{self.total}**   ({body}){crit}"


def _roll_group(count: int, sides: int, keep_mode: str, keep_n: int,
                sign: int, rng) -> DiceGroup:
    rolls = [rng.randint(1, sides) for _ in range(count)]
    kept, dropped = list(rolls), []
    if keep_mode:
        n = max(0, min(keep_n, count))
        order = sorted(rolls, reverse=(keep_mode == "kh"))
        kept, dropped = order[:n], order[n:]
    return DiceGroup(count=count, sides=sides, rolls=rolls, kept=kept,
                     dropped=dropped, keep_mode=(f"{keep_mode}{keep_n}" if keep_mode else ""),
                     sign=sign)


def roll(expression: str, rng=None) -> Roll:
    """Evaluate a dice expression. Raises DiceError on anything malformed —
    never guesses at what the player meant, because a wrong guess silently
    changes the odds."""
    rng = rng or _SYS_RNG
    raw = (expression or "").strip()
    if not raw:
        raise DiceError("No dice expression given.")

    # Normalise: strip whitespace, make '-' a term separator we can carry a sign on.
    expr = re.sub(r"\s+", "", raw).lower()
    if not re.fullmatch(r"[0-9dkhl%+\-]+", expr):
        raise DiceError(f"'{raw}' isn't a dice expression I recognise.")

    # Structure check BEFORE tokenising. findall() silently skips a dangling or
    # doubled sign ("1d20+", "2d6++1"), which would mean quietly rolling something
    # the player did not write — the exact failure this module exists to prevent.
    if not re.fullmatch(r"[+-]?[^+-]+(?:[+-][^+-]+)*", expr):
        raise DiceError(f"'{raw}' isn't a dice expression I recognise.")

    tokens = re.findall(r"[+-]?[^+-]+", expr)
    if not tokens:
        raise DiceError(f"'{raw}' isn't a dice expression I recognise.")
    if len(tokens) > MAX_GROUPS:
        raise DiceError(f"That's {len(tokens)} terms; {MAX_GROUPS} is the limit.")

    groups, modifier = [], 0
    for tok in tokens:
        sign = -1 if tok.startswith("-") else 1
        body = tok.lstrip("+-")
        if not body:
            raise DiceError(f"'{raw}' has a dangling + or -.")

        if _FLAT_RE.match(body):
            modifier += sign * int(body)
            continue

        m = _DIE_RE.match(body)
        if not m:
            raise DiceError(f"I can't read '{body}' as dice.")
        count_s, sides_s, keep_mode, keep_n_s = m.groups()

        count = int(count_s) if count_s else 1
        sides = 100 if sides_s == "%" else int(sides_s)
        keep_mode = (keep_mode or "").lower()
        keep_n = int(keep_n_s) if keep_n_s else (1 if keep_mode else 0)

        if count < 1:
            raise DiceError("You need at least one die.")
        if count > MAX_DICE_PER_GROUP:
            raise DiceError(f"{count} dice is past the {MAX_DICE_PER_GROUP} limit.")
        if sides < 2:
            raise DiceError("A die needs at least 2 sides.")
        if sides > MAX_SIDES:
            raise DiceError(f"d{sides} is past the d{MAX_SIDES} limit.")
        if keep_mode and keep_n > count:
            raise DiceError(f"Can't keep {keep_n} of {count} dice.")

        groups.append(_roll_group(count, sides, keep_mode, keep_n, sign, rng))

    if not groups and modifier and not any(c.isalpha() for c in expr):
        # A bare number is a constant, not a roll — refuse rather than pretend.
        raise DiceError(f"'{raw}' is just a number, not a roll.")

    total = sum(g.subtotal for g in groups) + modifier

    # Crit only means something for a SINGLE d20 deciding a check — not for 8d6
    # damage that happens to contain a 20, and not for 2d20 before keep resolves.
    crit = ""
    d20s = [g for g in groups if g.sides == 20]
    if len(d20s) == 1 and len(d20s[0].kept) == 1 and len(groups) == 1:
        face = d20s[0].kept[0]
        crit = "nat20" if face == 20 else "nat1" if face == 1 else ""

    return Roll(expression=raw, groups=groups, modifier=modifier, total=total, crit=crit)


def check(modifier: int = 0, advantage: bool = False, disadvantage: bool = False,
          rng=None) -> Roll:
    """A d20 check. Advantage and disadvantage CANCEL (5e rule: they don't stack
    and one of each is a flat roll), so the caller can pass both without special-casing."""
    if advantage and disadvantage:
        advantage = disadvantage = False
    core = "2d20kh1" if advantage else "2d20kl1" if disadvantage else "1d20"
    expr = f"{core}{modifier:+d}" if modifier else core
    return roll(expr, rng=rng)
