"""
Thoth Rung 4 — the reader lane, verify suite.

No audio and no Piper: the speaker is a fake that records what it was asked to
say. What is actually under test is the lane's arithmetic — which address a
phrase resolves to, which verses land in which synthesis unit, when the marker
moves, and how long the speech lock is held.

Run:  .venv/bin/python -m pytest tests/test_thoth_reader.py -v
"""
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

from thoth import reader                                        # noqa: E402
from thoth.corpus import Corpus                                 # noqa: E402
from thoth.schema import (AddressScheme, CanonStatus, Passage,  # noqa: E402
                          Provenance, SourceSpec, Work)

HEBREW = "בְּרֵאשִׁ֖ית בָּרָ֣א אֱלֹהִ֑ים"


def _work(wid, title):
    return Work(id=wid, title=title, tradition="Testing",
                language_of_origin="English",
                canonicity=(CanonStatus(tradition="Testers", status="canonical"),),
                provenance=Provenance(license="public-domain", license_note="PD",
                                      completeness="complete", vendorable=True),
                address=AddressScheme(section_label="chapter", unit_label="verse"),
                source=SourceSpec(url="https://example.invalid/x", adapter="usfm"))


class CountingLock:
    """A real lock that remembers how often it was taken."""
    def __init__(self):
        self._lock = threading.Lock()
        self.acquisitions = 0

    def __enter__(self):
        self._lock.acquire()
        self.acquisitions += 1
        return self

    def __exit__(self, *a):
        self._lock.release()

    def locked(self):
        return self._lock.locked()


class FakeSpeaker:
    def __init__(self, mute: set[str] | None = None, speakable=True):
        self.speech_lock = CountingLock()
        self.spoken: list[str] = []
        self.mute = mute or set()
        self._speakable = speakable

    def available(self):
        return True

    def can_speak(self, text, voice=None):
        return self._speakable and not any(ord(c) > 0x24F for c in text)

    def synth_pcm(self, text, voice=None, length_scale=None, sentence_silence=None):
        if text in self.mute:
            return None
        self.spoken.append(text)
        return b"\x00\x01" * 8

    def play_pcm(self, pcm):
        assert self.speech_lock.locked(), "played without holding the speech lock"
        return True


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, "SETTING_PATH", tmp_path / "thoth_reader.json")
    c = Corpus(db_path=tmp_path / "t.db")
    c.sync_metadata([_work("web", "World English Bible"),
                     _work("jps1917", "JPS 1917"),
                     _work("wlc", "Westminster Leningrad Codex")])
    c.replace_passages("web", [
        Passage(work_id="web", book="John", section=3, unit=i,
                text=f"John three verse {i}, a line of some length to pack.",
                ordinal=i) for i in range(1, 13)]
        + [Passage(work_id="web", book="John", section=4, unit=i,
                   text=f"John four verse {i}.", ordinal=100 + i)
           for i in range(1, 4)]
        + [Passage(work_id="web", book="1 John", section=1, unit=1,
                   text="First John, one one.", ordinal=200)]
        + [Passage(work_id="web", book="Psalms", section=23, unit=1,
                   text="Yahweh is my shepherd.", ordinal=300)]
        + [Passage(work_id="web", book="Genesis", section=1, unit=1,
                   text="In the beginning.", ordinal=400)])
    c.replace_passages("jps1917", [
        Passage(work_id="jps1917", book="Genesis", section=1, unit=1,
                text="In the beginning God created.", ordinal=1)])
    c.replace_passages("wlc", [
        Passage(work_id="wlc", book="Genesis", section=1, unit=1,
                text=HEBREW, ordinal=1)])
    yield c
    c.close()


# ── parsing ──────────────────────────────────────────────────────────────────

def test_parse_pulls_apart_verb_book_chapter_and_edition():
    assert reader.parse("read John 3")[:3] == ("John", 3, None)
    assert reader.parse("Please read me Genesis 1 in the JPS")[:3] == ("Genesis", 1, "jps")
    assert reader.parse("recite chapter 4 of Psalms")[1] == 4
    assert reader.parse("read sura 112")[:2] == ("__quran__", 112)


def test_parse_notes_when_the_genre_was_named():
    assert reader.parse("read the Gospel of John 3")[3] is True
    assert reader.parse("read John 3")[3] is False


# ── resolution: one question, never a silent guess ───────────────────────────

def test_an_ambiguous_book_name_asks_once(store):
    r = reader.resolve("read John 3", store, FakeSpeaker())
    assert not r.ok and r.question
    assert "1 John" in r.question and "John" in r.question
    assert r.question.count("?") == 1, "one question, not an interrogation"


def test_naming_the_book_precisely_does_not_ask(store):
    for phrase in ("read 1 John 1", "read the Gospel of John 3"):
        r = reader.resolve(phrase, store, FakeSpeaker())
        assert r.ok, phrase


def test_a_singular_plural_near_miss_is_not_an_ambiguity(store):
    """"Psalm 23" pulling in "Psalms" is not a question worth asking."""
    r = reader.resolve("read Psalm 23", store, FakeSpeaker())
    assert r.ok and r.reference.book == "Psalms"


def test_the_edition_is_chosen_and_announced_rather_than_asked(store):
    r = reader.resolve("read Genesis 1", store, FakeSpeaker())
    assert r.ok and r.reference.work_id == "web"
    assert r.note, "the reader must say which edition it picked"


def test_a_named_edition_wins(store):
    r = reader.resolve("read Genesis 1 in the JPS", store, FakeSpeaker())
    assert r.ok and r.reference.work_id == "jps1917"


def test_an_unspeakable_edition_is_refused_out_loud_not_played_as_silence(store):
    """_strip_for_piper drops every non-Latin codepoint, so Hebrew synthesises to
    nothing. A lane that does not check first reads a chapter as silence and
    looks like it worked."""
    r = reader.resolve("read Genesis 1 in the Hebrew", store, FakeSpeaker())
    assert not r.ok and not r.question
    assert "can't read" in r.refusal and "pronounce" in r.refusal
    assert "silence" in r.refusal


def test_an_unknown_book_says_what_is_available(store):
    r = reader.resolve("read Hezekiah 4", store, FakeSpeaker())
    assert not r.ok and "Hezekiah" in r.refusal and "Qur'an" in r.refusal


def test_a_missing_chapter_is_refused(store):
    """An unambiguous book — name ambiguity is settled before the chapter is
    looked up, so "John 99" would ask which John rather than get this far."""
    r = reader.resolve("read Psalms 99", store, FakeSpeaker())
    assert not r.ok and not r.question and "99" in r.refusal


# ── packing: verse atoms through the SHARED packer ───────────────────────────

def test_units_respect_verse_boundaries_and_cover_every_verse(store):
    ref = reader.Reference("web", "WEB", "John", 3)
    units = reader.chapter_units(store, ref, 3)
    assert units
    covered = set()
    for u in units:
        covered.update(range(u.first_unit, u.last_unit + 1))
        assert len(u.text) <= reader.UNIT_MAX_CHARS
    assert covered == set(range(1, 13)), "a verse was dropped or duplicated"


def test_resuming_skips_what_was_already_read(store):
    ref = reader.Reference("web", "WEB", "John", 3)
    part = reader.chapter_units(store, ref, 3, from_unit=8)
    assert part and part[0].first_unit == 9


def test_the_packer_is_the_shared_one_not_a_copy():
    """Astro's instruction: refactor tts_chunker's packer to take verse atoms
    rather than duplicating the loop. Both callers must use the same function."""
    import tts_chunker
    src = (REPO / "modules" / "thoth" / "reader.py").read_text(encoding="utf-8")
    assert "from tts_chunker import pack_units" in src
    assert tts_chunker.pack_units(["aa", "bb", "cc"], 5) == [("aa bb", 0, 1), ("cc", 2, 2)]
    # and the reply path still routes through it
    assert tts_chunker.split_for_tts("One. Two.") == ["One. Two."]


# ── the position marker ──────────────────────────────────────────────────────

def test_position_round_trips_and_clears(store):
    pos = reader.Position("web", "John", 3, 16)
    reader.save_position(store, pos)
    assert reader.load_position(store) == pos
    reader.clear_position(store)
    assert reader.load_position(store) is None


def test_only_one_position_is_kept(store):
    reader.save_position(store, reader.Position("web", "John", 3, 1))
    reader.save_position(store, reader.Position("web", "John", 3, 9))
    assert reader.load_position(store).unit == 9
    n = store._db.execute("SELECT count(*) FROM reading_position").fetchone()[0]
    assert n == 1


# ── the reading ──────────────────────────────────────────────────────────────

def _read(store, speaker, section=3, **kw):
    ref = reader.Reference("web", "World English Bible", "John", section)
    r = reader.Reading(store, speaker)
    r.start(ref, block=True, **kw)
    return r


def test_a_reading_announces_each_chapter(store):
    spk = FakeSpeaker()
    _read(store, spk)
    assert "Chapter 3." in spk.spoken
    assert "Chapter 4." in spk.spoken, "no announcement at the chapter boundary"


def test_a_reading_runs_on_past_the_chapter_it_started_at(store):
    spk = FakeSpeaker()
    _read(store, spk)
    assert any("John four" in t for t in spk.spoken)


def test_a_chapter_limit_stops_it_and_offers_to_go_on(store):
    spk = FakeSpeaker()
    _read(store, spk, continue_after=1)
    assert not any("John four" in t for t in spk.spoken)
    assert any("keep reading" in t for t in spk.spoken)


def test_the_speech_lock_is_taken_per_unit_not_per_reading(store):
    """Astro's ruling. Holding it for a whole chapter would block every other
    thing Phoebe says for minutes."""
    spk = FakeSpeaker()
    _read(store, spk)
    assert spk.speech_lock.acquisitions >= 4, spk.speech_lock.acquisitions
    assert spk.speech_lock.acquisitions == len(spk.spoken)
    assert not spk.speech_lock.locked(), "the lock outlived the reading"


def test_the_marker_advances_by_verse_and_lands_at_the_end(store):
    spk = FakeSpeaker()
    r = _read(store, spk)
    assert r.position() == reader.Position("web", "John", 4, 3)
    assert reader.load_position(store) == r.position()


def test_an_announcement_does_not_move_the_marker(store):
    spk = FakeSpeaker()
    r = _read(store, spk, continue_after=1)
    assert r.position().section == 3 and r.position().unit == 12


def test_a_unit_that_will_not_speak_is_reported_never_skipped_silently(store):
    ref = reader.Reference("web", "WEB", "John", 3)
    units = reader.chapter_units(store, ref, 3)
    spk = FakeSpeaker(mute={units[0].text})
    events = []
    r = reader.Reading(store, spk, on_event=lambda k, d: events.append((k, d)))
    r.start(ref, block=True, continue_after=1)
    assert any(k == "unspoken" for k, _d in events), \
        "a silent unit vanished without a word — the exact failure this lane guards"


def test_stopping_leaves_a_marker_to_resume_from(store):
    spk = FakeSpeaker()
    ref = reader.Reference("web", "WEB", "John", 3)
    spoke = threading.Event()
    r = reader.Reading(store, spk,
                       on_event=lambda k, d: spoke.set() if k == "verse" else None)
    r.start(ref)
    assert spoke.wait(timeout=10), "the reading never reached a verse"
    pos = r.stop()
    assert not r.is_running()
    assert pos is not None
    assert reader.load_position(store) == pos


# ── settings ─────────────────────────────────────────────────────────────────

def test_no_continue_prompt_by_default(store):
    assert reader.continue_after_chapters() == 0


def test_a_broken_settings_file_reads_as_the_default(store, tmp_path):
    (tmp_path / "thoth_reader.json").write_text("{ not json")
    assert reader.continue_after_chapters() == 0


def test_the_setting_round_trips_and_is_bounded(store):
    reader.set_continue_after_chapters(5)
    assert reader.continue_after_chapters() == 5
    reader.set_continue_after_chapters(9999)
    assert reader.continue_after_chapters() == 50


def test_a_per_reading_limit_does_not_rewrite_the_setting(store):
    """A flag on one invocation should not quietly change the configured
    default — it did, until this was caught."""
    reader.set_continue_after_chapters(0)
    _read(store, FakeSpeaker(), continue_after=1)
    assert reader.continue_after_chapters() == 0
