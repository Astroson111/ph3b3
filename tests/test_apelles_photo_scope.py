"""Apelles cross-surface photo handoff — scope and expiry.

The panel confirms a photo under the FIXED session id "panel"; chat tools arrive
carrying the chat's own session id. Those never match, so the per-session lookup
never resolves across surfaces and a global fallback is what actually carries
"confirm it in the panel, then ask Phoebe to make it black and white".

That fallback is therefore load-bearing and must keep working — these tests pin
that first, so nobody later 'fixes' it by deleting it. What it must NOT do is
last forever: one confirmed photo staying silently actionable means a request
days later reaches for a picture nobody remembers opening.

Exercised against the real server-module state, driven through a stand-in for
_ap_photo's resolution order so the test does not need a live app.
"""
import time

import pytest


TTL = 1800


class Resolver:
    """Mirrors server._ap_photo's resolution: session first, then a time-bounded
    cross-surface fallback, with the clock restarting on use."""

    def __init__(self, ttl=TTL, clock=time.time):
        self.current = {}          # session_id -> file_id
        self.files = {}            # file_id -> exists?
        self.last = {}             # {"image_id", "ts"}
        self.ttl = ttl
        self.clock = clock

    def confirm(self, sid, fid):
        self.files[fid] = True
        self.current[sid] = fid
        self.last.update({"image_id": fid, "ts": self.clock()})

    def discard(self, fid):
        self.files.pop(fid, None)
        if self.last.get("image_id") == fid:
            self.last.clear()

    def _last_fresh(self):
        fid = self.last.get("image_id")
        if not fid:
            return None
        if self.clock() - self.last.get("ts", 0) > self.ttl:
            self.last.clear()
            return None
        return fid

    def photo(self, sid="default"):
        sid = sid or "default"
        fid = self.current.get(sid) or self._last_fresh()
        if not fid or not self.files.get(fid):
            if fid:
                self.current.pop(sid, None)
                if self.last.get("image_id") == fid:
                    self.last.clear()
            return None
        if self.last.get("image_id") == fid:
            self.last["ts"] = self.clock()
        return fid


@pytest.fixture
def r():
    return Resolver()


# ── the fallback is load-bearing — do not delete it ──────────────────────────

def test_panel_confirm_reaches_a_chat_session_with_a_different_id(r):
    """The whole point. Panel confirms under "panel"; chat asks under its own id.
    Without the fallback this returns nothing and photo editing from chat dies."""
    r.confirm("panel", "img1")
    assert r.photo("chat-abc123") == "img1"


def test_a_device_on_yet_another_session_reaches_it_too(r):
    """Iris or Dio speaking from another room carries its own session id."""
    r.confirm("panel", "img1")
    assert r.photo("stackchan") == "img1"


def test_session_scoped_photo_wins_over_the_fallback(r):
    """A session that confirmed its own photo must act on THAT one, not the
    most recent global confirm."""
    r.confirm("sessionA", "imgA")
    r.confirm("panel", "imgPanel")
    assert r.photo("sessionA") == "imgA"


# ── but it must not last forever ─────────────────────────────────────────────

def test_fallback_lapses_once_idle(r):
    r.confirm("panel", "img1")
    r.clock = lambda: time.time() + TTL + 1
    assert r.photo("chat") is None, "a forgotten photo must stop being actionable"


def test_expiry_clears_the_slot_rather_than_leaving_it_dangling(r):
    r.confirm("panel", "img1")
    r.clock = lambda: time.time() + TTL + 1
    r.photo("chat")
    assert r.last == {}


def test_use_restarts_the_clock_so_active_editing_never_expires(r):
    """An IDLE timeout, not an absolute one. Touching the photo every 20 minutes
    keeps it alive well past the 30-minute window."""
    now = [time.time()]
    r.clock = lambda: now[0]
    r.confirm("panel", "img1")
    for _ in range(5):                       # 100 minutes of steady use
        now[0] += TTL * 2 // 3
        assert r.photo("chat") == "img1"
    now[0] += TTL + 1                        # then walk away
    assert r.photo("chat") is None


# ── stale pointers ───────────────────────────────────────────────────────────

def test_discarded_photo_stops_being_the_fallback(r):
    r.confirm("panel", "img1")
    r.discard("img1")
    assert r.photo("chat") is None


def test_missing_file_clears_both_pointers(r):
    """The file vanished from disk. Neither the session slot nor the fallback
    should keep pointing at it."""
    r.confirm("panel", "img1")
    r.files["img1"] = False
    assert r.photo("panel") is None
    assert r.current.get("panel") is None
    assert r.last == {}


def test_a_newer_confirm_replaces_the_fallback(r):
    r.confirm("panel", "img1")
    r.confirm("panel", "img2")
    assert r.photo("chat") == "img2"


def test_no_photo_at_all_is_not_an_error(r):
    assert r.photo("chat") is None


# ── the collision the old shape allowed ──────────────────────────────────────

def test_a_session_named__last_cannot_collide_with_the_fallback(r):
    """The fallback used to live in the session dict under the key "_last", so a
    session with that id shared a slot with it. Separate storage now."""
    r.confirm("panel", "imgPanel")
    r.current["_last"] = "imgSession"
    r.files["imgSession"] = True
    assert r.photo("_last") == "imgSession"
    assert r.last["image_id"] == "imgPanel", "the fallback must be untouched"


# ── the stand-in above must not drift from the real thing ────────────────────
# Resolver mirrors server._ap_photo. Importing server.py costs ~11s, which is
# most of the suite's runtime, so these are STRUCTURAL checks on the source in
# the style of test_emotions — cheap, and enough to catch the real code and the
# model of it parting ways silently.

from pathlib import Path                                        # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")


def test_real_resolver_tries_session_before_the_fallback():
    assert "_apelles_current.get(sid) or _apelles_last_fresh()" in SRC, \
        "_ap_photo must resolve the session slot before the cross-surface fallback"


def test_real_fallback_is_ttl_bounded():
    assert "_APELLES_LAST_TTL_S" in SRC
    assert 'time.time() - _apelles_last.get("ts", 0) > _APELLES_LAST_TTL_S' in SRC, \
        "the fallback must expire on idle, not last forever"


def test_real_confirm_stamps_the_clock():
    assert '_apelles_last.update({"image_id": pend["image_id"], "ts": time.time()})' in SRC


def test_real_use_restarts_the_idle_clock():
    assert '_apelles_last["ts"] = time.time()' in SRC, \
        "using the photo must reset the idle clock or active editing expires mid-session"


def test_the_old_colliding_key_is_gone_from_live_code():
    """The fallback must no longer share a namespace with session ids. Comments
    mentioning the old shape are fine; live subscripts are not."""
    live = [ln for ln in SRC.splitlines()
            if "_last" in ln and not ln.lstrip().startswith("#")]
    offenders = [ln.strip() for ln in live
                 if '_apelles_current["_last"]' in ln or '_apelles_current.get("_last")' in ln]
    assert not offenders, f"old _last key still in use: {offenders}"
