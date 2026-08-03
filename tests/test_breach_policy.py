"""Output-breach policy — a refused render must not become a subsystem outage.

The rule these lock down: a corroborated output-check hit DESTROYS the render
(no off switch, asserted here) but does NOT halt the generator by default. The
sticky global halt is opt-in, because this check's false-positive rate makes a
lone hit much likelier to be a misfire than a bypass — and the old unconditional
halt turned one misfire into a total lockout of txt2img, edit and video at once.

Every test redirects BREACH_FLAG / BREACH_LOG into tmp_path. None of these may
read or write the real ~/Desktop/ph3b3_v2_data breach files — a test run must
never halt the live generator, and must never clear a halt a human set.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import morpheus  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point every breach artefact at tmp_path, and stub the vision calls so no
    test needs a GPU or a model."""
    monkeypatch.setattr(morpheus, "BREACH_FLAG", tmp_path / "BREACH_HALT")
    monkeypatch.setattr(morpheus, "BREACH_LOG", tmp_path / "BREACH_LOG.txt")
    monkeypatch.setattr(morpheus, "AUTO_PURGE", False)
    monkeypatch.setattr(morpheus, "purge_library",
                        lambda *a, **k: pytest.fail("a test triggered a real library purge"))
    return tmp_path


def _breach(monkeypatch, corroborated=True, halt_on_breach=False, halt_any=False):
    monkeypatch.setattr(morpheus, "HALT_ON_BREACH", halt_on_breach)
    monkeypatch.setattr(morpheus, "HALT_ON_ANY_HIT", halt_any)
    morpheus.handle_output_breach(b"", "deadbeef-0000-0000-0000-000000000000",
                                  corroborated=corroborated)


# ── The default: refuse the render, keep the machine running ─────────────────
def test_corroborated_breach_does_not_halt(sandbox, monkeypatch):
    _breach(monkeypatch, corroborated=True)
    assert morpheus.generation_halted() is None, \
        "one corroborated hit locked the whole generator — the outage this policy exists to prevent"


def test_uncorroborated_breach_does_not_halt(sandbox, monkeypatch):
    _breach(monkeypatch, corroborated=False)
    assert morpheus.generation_halted() is None


def test_repeated_breaches_still_do_not_halt(sandbox, monkeypatch):
    """Even a cluster does not lock by default. The cluster is made VISIBLE
    instead — halting is a policy the operator opts into, not a surprise."""
    for _ in range(6):
        _breach(monkeypatch, corroborated=True)
    assert morpheus.generation_halted() is None
    assert morpheus.recent_breaches(hours=24) == 6


# ── The opt-in: old behaviour is still reachable without a code change ───────
def test_halt_on_breach_restores_the_lock(sandbox, monkeypatch):
    _breach(monkeypatch, corroborated=True, halt_on_breach=True)
    assert morpheus.generation_halted() is not None


def test_halt_on_any_hit_locks_even_uncorroborated(sandbox, monkeypatch):
    _breach(monkeypatch, corroborated=False, halt_any=True)
    assert morpheus.generation_halted() is not None


def test_halt_on_breach_does_not_fire_on_uncorroborated(sandbox, monkeypatch):
    _breach(monkeypatch, corroborated=False, halt_on_breach=True)
    assert morpheus.generation_halted() is None


# ── The record that replaced the halt ────────────────────────────────────────
def test_every_hit_is_recorded(sandbox, monkeypatch):
    _breach(monkeypatch, corroborated=True)
    _breach(monkeypatch, corroborated=False)
    lines = (sandbox / "BREACH_LOG.txt").read_text().strip().splitlines()
    assert len(lines) == 2
    assert "corroborated=True" in lines[0]
    assert "corroborated=False" in lines[1]


def test_breach_log_never_records_prompt_text(sandbox, monkeypatch):
    """The log accumulates forever. It must never become a store of what people
    typed — only timestamps, job ids and the verdict."""
    _breach(monkeypatch, corroborated=True)
    line = (sandbox / "BREACH_LOG.txt").read_text().strip()
    ts, job, verdict = line.split("\t")
    datetime.fromisoformat(ts)                      # parses → it really is a timestamp
    assert job == "deadbeef" and verdict.startswith("corroborated=")


def test_recent_breaches_counts_only_corroborated_by_default(sandbox, monkeypatch):
    _breach(monkeypatch, corroborated=True)
    _breach(monkeypatch, corroborated=False)
    assert morpheus.recent_breaches(hours=24) == 1
    assert morpheus.recent_breaches(hours=24, corroborated_only=False) == 2


def test_recent_breaches_ignores_old_entries(sandbox, monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    (sandbox / "BREACH_LOG.txt").write_text(f"{old}\tcafebabe\tcorroborated=True\n")
    assert morpheus.recent_breaches(hours=24) == 0


def test_recent_breaches_survives_a_corrupt_log(sandbox, monkeypatch):
    (sandbox / "BREACH_LOG.txt").write_text("not a real line\n\t\t\nnope\n")
    assert morpheus.recent_breaches(hours=24) == 0     # degrades, never raises


def test_recent_breaches_with_no_log_is_zero(sandbox):
    assert morpheus.recent_breaches(hours=24) == 0


# ── The part that has no off switch ──────────────────────────────────────────
def test_the_render_is_destroyed_regardless_of_halt_policy():
    """The refusal is the protection, and it lives on the fetch path — the
    flagged bytes are never written to IMAGE_DIR whatever the halt policy says.
    Structural: fetch_and_save raises before it ever reaches path.write_bytes."""
    src = (ROOT / "modules" / "morpheus.py").read_text(encoding="utf-8")
    start = src.index("async def fetch_and_save(")
    body = src[start:start + 2500]
    refuse_at = body.index("raise RuntimeError(_OUTPUT_REFUSAL)")
    write_at = body.index("path.write_bytes(raw)")
    assert refuse_at < write_at, \
        "a corroborated render could reach the library — the refusal must precede the write"


def test_halt_policy_is_opt_in_not_default():
    """Both halt switches must default OFF in source. A future edit that flips a
    default back to on reinstates the lockout silently."""
    src = (ROOT / "modules" / "morpheus.py").read_text(encoding="utf-8")
    for var in ("PH3B3_HALT_ON_BREACH", "PH3B3_HALT_ON_ANY_HIT"):
        assert f'os.getenv("{var}", "0")' in src, f"{var} no longer defaults to off"
