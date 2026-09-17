"""
The secrets tripwire, checked — because a guard nobody guards is a feeling.

The false-positive cases are the ones that matter. The version this replaced
matched bare words and fired on three lines of prose about parse tokens; the
push went out anyway, which is precisely what a noisy check buys you. If this
starts crying wolf again these tests fail before a human learns to ignore it.

Run:  .venv/bin/python -m pytest tests/test_check_secrets.py -v
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import check_secrets as cs  # noqa: E402


QUIET = [
    # the three that cried wolf on the Thoth resolver commit
    "# mangled token quoted back as though it were a title",
    "        # Deliberately does NOT echo the phrase. Quoting the leftover token back",
    "    that was the bug: a mangled token echoed as a title",
    # real lines from this repo that must never flag
    'PASSFILE="/home/astroson/.config/rhea/passphrase"',
    "password = os.getenv('PH3B3_PASSWORD')",
    'self.token = body.get("token")',
    "PH3B3_PASSWORD=<set>",
    "    # the TEXT is not logged",
    "_MAGIC = 0xA511",
    "    tokens = {t for t in re.split(r'[^a-z0-9]+', title)}",
]

LOUD = [
    'PH3B3_PASSWORD = "hunter2correcthorse"',
    'api_key = "sk-abcdefghijklmnopqrstuvwxyz012345"',
    "-----BEGIN RSA PRIVATE KEY-----",
    "AKIAIOSFODNN7EXAMPLE",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    'client_secret: "9f8c2b7ae41d0356bb"',
]


@pytest.mark.parametrize("line", QUIET)
def test_ordinary_code_and_prose_do_not_flag(line):
    assert not cs.findings("+" + line), f"cried wolf on: {line}"


@pytest.mark.parametrize("line", LOUD)
def test_a_real_credential_shape_flags(line):
    assert cs.findings("+" + line), f"missed: {line}"


def test_removed_lines_are_never_flagged():
    """A diff that DELETES a secret is the fix, not the problem."""
    assert not cs.findings('-PH3B3_PASSWORD = "hunter2correcthorse"')


def test_the_script_runs_and_its_self_test_passes():
    """The self-test is the script's own guard; if it stops passing, the tripwire
    has drifted and this fails in the ordinary suite rather than at a push."""
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "check_secrets.py"),
                        "--self-test"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 wrong" in r.stdout


def test_it_stays_quiet_across_this_repos_own_recent_history():
    """The strongest evidence available: real commits, no findings."""
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "check_secrets.py"),
                        "4ba392f..HEAD"], capture_output=True, text=True, cwd=REPO)
    if "unknown revision" in (r.stderr or ""):
        pytest.skip("history not present in this checkout")
    assert r.returncode == 0, r.stdout
