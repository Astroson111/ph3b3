"""Auth-table hygiene: sessions that expire, block tables that stay bounded.

Both were findings in the 2026-08-19 audit and both are the same shape — state
that only ever grew, because the thing that would have cleaned it up only ran on
traffic that, by definition, had stopped arriving.

Structural checks on server.py rather than a live import: server.py costs ~11s
to import, which is a third of the whole suite.
"""
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")


# ── session expiry (audit #4) ────────────────────────────────────────────────

class Sessions:
    """Mirror of server._session_user / _session_start."""

    def __init__(self, max_age=86400 * 7, clock=time.time):
        self.d = {}
        self.max_age = max_age
        self.clock = clock

    def start(self, token, user):
        self.d[token] = {"user": user, "exp": self.clock() + self.max_age}

    def user(self, token):
        if not token:
            return None
        st = self.d.get(token)
        if not st:
            return None
        if self.clock() >= st.get("exp", 0):
            self.d.pop(token, None)
            return None
        return st.get("user")


def test_live_token_resolves():
    s = Sessions(); s.start("t", "alex")
    assert s.user("t") == "alex"


@pytest.mark.parametrize("token", ["", None, "unknown"])
def test_absent_tokens_resolve_to_nobody(token):
    assert Sessions().user(token) is None


def test_token_expires_server_side():
    """The cookie's max_age is a hint to the browser. A token lifted out of one
    has to stop working because the SERVER says so."""
    now = [time.time()]
    s = Sessions(clock=lambda: now[0])
    s.start("t", "alex")
    now[0] += 86400 * 7 + 1
    assert s.user("t") is None


def test_expiry_drops_the_entry_rather_than_leaving_it():
    now = [time.time()]
    s = Sessions(clock=lambda: now[0])
    s.start("t", "alex")
    now[0] += 86400 * 7 + 1
    s.user("t")
    assert "t" not in s.d, "an expired session must not sit in the map forever"


def test_expiry_is_not_a_sliding_window():
    """Deliberately absolute, unlike the Apelles photo handoff: a login is good
    for seven days from the login, not seven days from the last click."""
    now = [time.time()]
    s = Sessions(clock=lambda: now[0])
    s.start("t", "alex")
    for _ in range(6):
        now[0] += 86400
        assert s.user("t") == "alex"
    now[0] += 86400 * 2
    assert s.user("t") is None


def test_sessions_are_independent():
    now = [time.time()]
    s = Sessions(clock=lambda: now[0])
    s.start("old", "alex")
    now[0] += 86400 * 6
    s.start("new", "alex")
    now[0] += 86400 * 2
    assert s.user("old") is None
    assert s.user("new") == "alex"


# ── block-table pruning (audit #2) ───────────────────────────────────────────

def test_blocked_entries_are_swept_when_the_table_is_under_pressure():
    """_auth_blocked is otherwise pruned only when that exact key is looked up
    again — and a blocked caller that never comes back is never looked up."""
    now = time.time()
    blocked = {f"peer:10.0.0.{i}": now - 1 for i in range(50)}      # all lapsed
    blocked["peer:10.0.1.1"] = now + 300                            # still live
    for k in [k for k, until in blocked.items() if until <= now]:
        blocked.pop(k, None)
    assert len(blocked) == 1
    assert "peer:10.0.1.1" in blocked, "a live block must survive the sweep"


# ── the real implementation ──────────────────────────────────────────────────

def test_server_uses_the_session_helpers_everywhere():
    """A bare `token in _sessions` would bypass the expiry check entirely."""
    assert "in _sessions:" not in SRC, \
        "membership test found — every read must go through _session_user()"
    assert "def _session_user(" in SRC
    assert "def _session_start(" in SRC


def test_server_stamps_an_expiry_on_every_new_session():
    assert '_sessions[token] = {"user": user, "exp": time.time() + _SESSION_MAX_AGE}' in SRC


def test_server_sweeps_the_block_table():
    assert "for k in [k for k, until in _auth_blocked.items() if until <= now]:" in SRC


def test_dead_forwarded_for_branch_is_gone():
    """It read X-Forwarded-For itself and looked like the protection. uvicorn had
    already resolved the header before it ran, so the branch was unreachable."""
    fn = SRC[SRC.index("def _auth_client_key("):SRC.index("def _auth_note_failure(")]
    assert '"fwd:"' not in fn
    assert "X-Forwarded-For" not in fn or "used to inspect" in fn


def test_proxy_header_settings_are_explicit():
    """The throttle's correctness depends on them, so they must not be defaults
    that can change under us."""
    assert "proxy_headers=True" in SRC
    assert 'forwarded_allow_ips="127.0.0.1"' in SRC


# ── the lock file (audit #10) ────────────────────────────────────────────────

def test_lock_file_exists_and_is_fully_pinned():
    lock = ROOT / "requirements.lock.txt"
    assert lock.exists()
    pins = [ln.strip() for ln in lock.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
    assert pins, "lock file has no entries"
    loose = [p for p in pins if "==" not in p]
    assert not loose, f"lock must pin exactly: {loose[:5]}"


def test_lock_file_is_portable():
    """A local build tag or a file:// path makes the lock useless on any other
    machine, which defeats the point of having one."""
    text = (ROOT / "requirements.lock.txt").read_text()
    for marker in ("@ file://", "-e ", "@ git+"):
        assert marker not in text, f"non-portable entry ({marker}) in the lock"


def test_lock_covers_every_package_the_spec_names():
    import re
    spec = set()
    for ln in (ROOT / "requirements.txt").read_text().splitlines():
        ln = ln.split("#")[0].strip()
        if not ln:
            continue
        spec.add(re.split(r"[><=\[]", ln)[0].strip().lower().replace("_", "-"))
    locked = {ln.split("==")[0].strip().lower().replace("_", "-")
              for ln in (ROOT / "requirements.lock.txt").read_text().splitlines()
              if "==" in ln and not ln.startswith("#")}
    assert spec <= locked, f"in the spec but not locked: {sorted(spec - locked)}"
