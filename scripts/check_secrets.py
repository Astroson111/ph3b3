#!/usr/bin/env python3
"""
check_secrets — last look at a diff before it leaves the machine.

    scripts/check_secrets.py                 # staged changes
    scripts/check_secrets.py origin/main..HEAD
    scripts/check_secrets.py --self-test

Exit 0 = nothing found, 1 = something to look at, 2 = the check itself failed.

── WHY IT IS NARROW ─────────────────────────────────────────────────────────
The version this replaces matched bare words — password, secret, token, key —
anywhere in an added line. On the Thoth resolver commit that flagged three
lines, all of them prose about parse tokens: "mangled token quoted back as
though it were a title". Nothing was wrong and the push went out anyway.

A check that cries wolf on comments is a check that gets waved through, and a
waved-through check is worse than no check, because it looks like coverage. So
this one wants a secret SHAPE, not a secret WORD: an assignment to a
secret-named thing with a literal on the right, or a credential format that is
unmistakable on sight.

── WHAT IT CANNOT DO ────────────────────────────────────────────────────────
It reads a diff. It cannot know that a 40-character hex string is a real key
rather than a test fixture, and it will not catch a secret pasted into prose
without an assignment. It is a tripwire on the obvious cases, not an audit —
the real protections are .gitignore and not putting secrets in the repo.
"""
from __future__ import annotations

import re
import subprocess
import sys

# Names that mean "this is a credential" when something is ASSIGNED to them.
_SECRET_NAME = (r"(?:pass(?:word|phrase)?|secret|api[_-]?key|apikey|auth[_-]?token|"
                r"access[_-]?token|refresh[_-]?token|bearer|private[_-]?key|"
                r"client[_-]?secret|session[_-]?key|encryption[_-]?key)")

# A literal on the right-hand side: quoted, or bare non-placeholder text.
# The name may be PREFIXED — PH3B3_PASSWORD has no word boundary before
# "PASSWORD" because underscore is a word character, so \b alone missed the one
# variable in this repo that actually holds one.
_ASSIGNED = re.compile(
    rf"(?:^|[^A-Za-z0-9])[A-Za-z0-9_.]*{_SECRET_NAME}\s*(?:=|:=|:|=>)\s*"
    rf"(?P<val>[\"'][^\"']{{6,}}[\"']|[^\s,;)}}\]]{{8,}})",
    re.I)

# Formats that are a credential whatever surrounds them.
_HARD = (
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "private key block"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "GitHub token"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "API key (sk- form)"),
    (re.compile(r"\bAuthorization\s*:\s*(?:Bearer|Basic)\s+[A-Za-z0-9+/=._-]{12,}", re.I),
     "inline Authorization header"),
)

# Right-hand sides that are not secrets: references, placeholders, empties.
_NOT_A_SECRET = re.compile(
    # The numeric case must be the WHOLE value. As a prefix it swallowed
    # "9f8c2b7ae41d0356bb" — a hex secret that merely starts with a digit.
    r"^[\"']?(?:\s*)?(?:\{\{|\$\{|<|\*{3,}|x{3,}|redacted|changeme|your[_-]?|"
    r"example|placeholder|none|null|true|false)|"
    r"^[\"']?\d+[\"']?\s*$|"
    r"(?:os\.)?getenv|environ|config\[|settings\.|\.get\(|input\(|prompt\(|"
    r"argv|args\.|body\.get|params\.get|_PATH|_FILE",
    re.I)

# Files whose JOB is to contain credential specimens. A tripwire that fires on
# its own fixtures is the cry-wolf failure this script exists to end — it flagged
# 14 lines on the very commit that introduced it, all of them fake keys written
# to prove the patterns work.
_SPECIMEN_FILES = ("scripts/check_secrets.py", "tests/test_check_secrets.py")

# An escape hatch for anywhere else a specimen is genuinely needed.
_ALLOW = re.compile(r"(?:pragma|noqa)\s*:\s*allowlist[ _-]?secret", re.I)

# A value that is CODE rather than a literal: a call, an f-string, an expression.
_LOOKS_LIKE_CODE = re.compile(r"[(\[]|^re\.|^f[\"']")

# Comment openers per language. A secret in a comment is still a secret, but a
# WORD in a comment is what kept firing, so comments are held to the hard
# patterns only.
_COMMENT = re.compile(r"^\s*(?:#|//|/\*|\*|<!--|--)")


def findings(diff: str) -> list[tuple[int, str, str]]:
    """(line_no_in_diff, reason, text) for each added line worth a look."""
    out = []
    current = ""
    for i, raw in enumerate(diff.splitlines(), start=1):
        if raw.startswith("+++ "):
            current = raw[4:].lstrip("b/").strip()
            continue
        if not raw.startswith("+"):
            continue
        if any(current.endswith(f) for f in _SPECIMEN_FILES):
            continue
        line = raw[1:]
        if _ALLOW.search(line):
            continue
        for pat, why in _HARD:
            if pat.search(line):
                out.append((i, why, line.strip()[:160]))
                break
        else:
            if _COMMENT.match(line):
                continue          # prose: hard patterns only, checked above
            m = _ASSIGNED.search(line)
            val = m.group("val").strip() if m else ""
            if (m and not _NOT_A_SECRET.match(val)
                    and not _LOOKS_LIKE_CODE.search(val)):
                out.append((i, "literal assigned to a credential name",
                            line.strip()[:160]))
    return out


def _self_test() -> int:
    """The check has to be checked, or it is just a feeling.

    Cases are real: the three FLAGGED lines are the ones that cried wolf on the
    Thoth commit, and they must stay quiet now.
    """
    quiet = [
        "# mangled token quoted back as though it were a title — the failure mode",
        "        # Deliberately does NOT echo the phrase. Quoting the leftover token back",
        "    that was the bug: a mangled token echoed as a title reads as the library",
        'PASSFILE="/home/astroson/.config/rhea/passphrase"',
        "password = os.getenv('PH3B3_PASSWORD')",
        'api_key: str = ""',
        "# set your api_key here",
        'self.token = body.get("token")',
        "PH3B3_PASSWORD=<set>",
        "_NOT_A_SECRET = re.compile(",                  # a pattern, not a secret
        'API_KEY = os.environ["PH3B3_KEY"]',
        'password = f"{user}:{pw}"',
        'token = "xxxxxxxxxxxx"  # pragma: allowlist secret',
    ]
    loud = [
        'PH3B3_PASSWORD = "hunter2correcthorse"',
        'api_key = "sk-abcdefghijklmnopqrstuvwxyz012345"',
        "-----BEGIN RSA PRIVATE KEY-----",
        "AKIAIOSFODNN7EXAMPLE",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        'client_secret: "9f8c2b7ae41d0356bb"',
    ]
    bad = 0
    for line in quiet:
        if findings("+" + line):
            print(f"  FALSE POSITIVE: {line}"); bad += 1
    for line in loud:
        if not findings("+" + line):
            print(f"  MISSED:         {line}"); bad += 1
    print(f"  self-test: {len(quiet)} quiet, {len(loud)} loud, {bad} wrong")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _self_test()
    rng = argv[1] if len(argv) > 1 else None
    cmd = ["git", "diff", rng] if rng else ["git", "diff", "--cached"]
    try:
        diff = subprocess.run(cmd, capture_output=True, text=True,
                              check=True).stdout
    except subprocess.CalledProcessError as e:
        print(f"check_secrets: git failed — {e}", file=sys.stderr)
        return 2
    hits = findings(diff)
    if not hits:
        print(f"check_secrets: clean ({len(diff.splitlines())} diff lines)")
        return 0
    print(f"check_secrets: {len(hits)} line(s) to look at before this leaves the machine\n")
    for _n, why, text in hits:
        print(f"  [{why}]\n    {text}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
