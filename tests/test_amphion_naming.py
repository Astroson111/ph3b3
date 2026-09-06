"""
Amphion song naming — display title, derived slug, Hermes3 suggestions.

Run:  .venv/bin/python -m pytest tests/test_amphion_naming.py

No GPU, no ComfyUI and NO OLLAMA. run_generation is stubbed and every LLM call
is injected, because a test that needs the local model up would go green on the
one machine it was written on and be skipped everywhere else.

WHAT THIS FILE IS GUARDING, in order of how much it would hurt to lose:

  * The floor is NOT on the titling path. That is a deliberate invariant, not an
    oversight, and an invariant nobody tests is a comment. test_suggest_makes_no
    _floor_call spies on floor_check and FAILS if it is reached — and the test
    immediately after it proves the spy can actually see a call, so this cannot
    quietly become a test of nothing.
  * A suggestion never lands in the field by itself. The render path must not
    call the model, on any route, ever — a title that appeared without a press
    is a title nobody chose.
  * Nothing renders nameless, including when Ollama is face-down. The blank-title
    default is arithmetic on the seed and the date; it has no failure mode.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))       # for `import server`

import server                                  # noqa: E402
from fastapi.testclient import TestClient      # noqa: E402

morpheus = server.morpheus
amphion = server.amphion

import base64                                  # noqa: E402
client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_auth}"}


# ── Nothing here may reach a GPU. ────────────────────────────────────────────
async def _spy_run_generation(job_id, params):
    _rendered.append(dict(params))
    if job_id in amphion.jobs:
        amphion.jobs[job_id]["state"] = "done"
    return None


_rendered: list[dict] = []
amphion.run_generation = _spy_run_generation


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """A fresh songs/ per test and an empty reservation set.

    ~/ph3b3_data/songs is Astro's actual library. A naming test writes sidecars
    and probes for collisions, so it gets its own directory — the smoke-test rule
    from 15ea2bb applies here exactly: a test must not write to the store it is
    testing.
    """
    monkeypatch.setattr(amphion, "SONGS_DIR", tmp_path / "songs")
    amphion._reserved_slugs.clear()
    _rendered.clear()
    yield
    amphion._reserved_slugs.clear()


@pytest.fixture
def open_floor(monkeypatch):
    """Layer A and Layer B both pass, so a naming test measures naming. The floor
    has its own suite; borrowing it here would only make these tests slower and
    dependent on a judge being up."""
    monkeypatch.setattr(morpheus, "floor_check", lambda *a, **k: None)
    monkeypatch.setattr(morpheus, "_floor_judge", lambda template, text: "NO")
    monkeypatch.setattr(morpheus, "_floor_judge_ex", lambda template, text: ("NO", None))
    monkeypatch.setattr(amphion, "voice_clone_refusal", lambda *a, **k: None)
    monkeypatch.setattr(amphion, "copyright_refusal", lambda *a, **k: None)


def _generate(**kw):
    body = {"tags": "indie rock, warm analog", "lyrics": "", "seconds": 30}
    body.update(kw)
    return client.post("/amphion/generate", json=body, headers=HEADERS)


def _write_track(job_id, **side):
    """A finished track: the master plus its sidecar, as run_generation leaves them."""
    d = amphion._songs_dir()
    (d / f"{job_id}.flac").write_bytes(b"\x00")
    (d / f"{job_id}.json").write_text(json.dumps({"job_id": job_id, **side}))


# ══ 1. Slug derivation ═══════════════════════════════════════════════════════
@pytest.mark.parametrize("title,expected", [
    ("Blue Hour", "blue-hour"),
    ("  Blue   Hour  ", "blue-hour"),
    ("BLUE HOUR", "blue-hour"),
    ("Blue Hour!!!", "blue-hour"),
    ("Blue / Hour", "blue-hour"),
    ("Don't Look Back", "don-t-look-back"),
    ("Café Nocturne", "cafe-nocturne"),          # NFKD fold, not a dropped word
    ("Blue Hour 🌙", "blue-hour"),               # emoji has no ASCII to keep
    ("---Blue---Hour---", "blue-hour"),          # no leading/trailing/double hyphens
    ("Song #2", "song-2"),
])
def test_slugify(title, expected):
    assert amphion.slugify(title) == expected


def test_slug_is_trimmed_to_sixty_chars():
    s = amphion.slugify("word " * 40)
    assert len(s) <= amphion.SLUG_MAX
    assert not s.endswith("-") and not s.startswith("-")


def test_slugify_may_return_empty_and_says_so():
    """Pure function, empty result allowed — the FALLBACK is the caller's job.
    If this ever starts inventing a name, resolve_naming's fallback becomes dead
    code and nothing would notice."""
    assert amphion.slugify("🌙🌙🌙") == ""
    assert amphion.slugify("") == ""


# ══ 2. The untitled default — no model, no failure mode ══════════════════════
def test_untitled_is_seed_anchored_and_dated():
    when = datetime(2026, 9, 6, tzinfo=timezone.utc)
    assert amphion.untitled_name(4242, when) == "untitled-4242-20260906"


def test_untitled_is_deterministic():
    when = datetime(2026, 9, 6, tzinfo=timezone.utc)
    assert amphion.untitled_name(7, when) == amphion.untitled_name(7, when)


@pytest.mark.parametrize("blank", ["", "   ", None], ids=["empty", "spaces", "absent"])
def test_blank_title_resolves_to_the_untitled_form_in_both_fields(blank):
    # Parametrized rather than looped: each call RESERVES its slug, so three
    # resolves in one test would legitimately come back -2 and -3.
    when = datetime(2026, 9, 6, tzinfo=timezone.utc)
    n = amphion.resolve_naming(blank, 99, when)
    assert n["title"] == "untitled-99-20260906"
    assert n["slug"] == "untitled-99-20260906"


def test_a_title_of_pure_emoji_still_gets_a_filename():
    """The display title is kept verbatim; the slug falls through to the untitled
    form rather than to an empty filename."""
    when = datetime(2026, 9, 6, tzinfo=timezone.utc)
    n = amphion.resolve_naming("🌙🌙", 5, when)
    assert n["title"] == "🌙🌙"
    assert n["slug"] == "untitled-5-20260906"


# ══ 3. Collisions ════════════════════════════════════════════════════════════
def test_slug_collides_with_an_existing_file_and_suffixes():
    _write_track("aaa111", slug="blue-hour", title="Blue Hour")
    assert amphion.resolve_naming("Blue Hour", 1)["slug"] == "blue-hour-2"


def test_collisions_keep_counting():
    _write_track("aaa111", slug="blue-hour")
    _write_track("bbb222", slug="blue-hour-2")
    assert amphion.resolve_naming("Blue Hour", 1)["slug"] == "blue-hour-3"


def test_a_new_song_cannot_claim_a_pre_titling_track_s_export_name():
    """A track from before titling has no recorded slug, but it still EXPORTS
    under one. If the collision scan only looked at recorded slugs, a new song
    named to match would silently take the same filename."""
    _write_track("aaa111", seed=7, created_at="2026-08-01T10:00:00+00:00")
    assert amphion.slug_for("aaa111") == "untitled-7-20260801"
    assert amphion.resolve_naming("untitled-7-20260801", 1)["slug"] == "untitled-7-20260801-2"


def test_slugs_reserved_in_the_same_batch_do_not_collide():
    """Variations queue N jobs at once and no sidecar exists yet for any of them.
    The on-disk scan alone cannot see the siblings; the reservation set can."""
    got = [amphion.resolve_naming("Blue Hour", s)["slug"] for s in (1, 2, 3, 4)]
    assert got == ["blue-hour", "blue-hour-2", "blue-hour-3", "blue-hour-4"]
    assert len(set(got)) == 4


# ══ 4. The suggest path — and the floor that is NOT on it ════════════════════
def _fake_llm(payload):
    def _llm(prompt, temperature=0.0):
        return payload
    return _llm


def test_suggest_parses_a_plain_json_array():
    out = amphion.suggest_titles("some words", "indie", llm=_fake_llm('["Blue Hour","Low Sun","Ash"]'))
    assert out == ["Blue Hour", "Low Sun", "Ash"]


def test_suggest_strips_code_fences():
    raw = '```json\n["Blue Hour", "Low Sun", "Ash"]\n```'
    assert amphion.suggest_titles("w", "t", llm=_fake_llm(raw))[0] == "Blue Hour"


def test_suggest_salvages_an_array_wrapped_in_an_object():
    """{"titles": [...]} is the commonest way the model deviates from the contract.
    The titles in it are fine; only the packaging is wrong, so it is unwrapped
    rather than refused. This is a decision, not an accident — see _strip_fences."""
    raw = '{"titles": ["Blue Hour", "Low Sun", "Ash"]}'
    assert amphion.suggest_titles("w", "t", llm=_fake_llm(raw)) == ["Blue Hour", "Low Sun", "Ash"]


def test_suggest_survives_chatter_around_the_array():
    raw = 'Sure! Here are some titles:\n["Blue Hour","Low Sun","Ash"]\nHope that helps.'
    assert amphion.suggest_titles("w", "t", llm=_fake_llm(raw)) == ["Blue Hour", "Low Sun", "Ash"]


def test_suggest_caps_at_five_and_dedupes():
    raw = json.dumps(["A", "B", "C", "D", "E", "F", "a"])
    out = amphion.suggest_titles("w", "t", llm=_fake_llm(raw))
    assert len(out) == amphion.SUGGEST_MAX
    assert len({x.lower() for x in out}) == amphion.SUGGEST_MAX


@pytest.mark.parametrize("raw", ["not json at all", "{}", "[]", '[1, 2, 3]', "",
                                 '{"note": "no titles this time"}'])
def test_suggest_fails_loud_never_blank(raw):
    """Every unusable shape raises. It must never return [] — an empty list is
    what a caller would happily write into the field."""
    with pytest.raises(amphion.SuggestFailed):
        amphion.suggest_titles("w", "t", llm=_fake_llm(raw))


def test_suggest_raises_when_ollama_is_down():
    def _dead(prompt, temperature=0.0):
        raise ConnectionError("connection refused")
    with pytest.raises(amphion.SuggestFailed):
        amphion.suggest_titles("w", "t", llm=_dead)


def test_instrumental_names_from_the_style_tag_alone():
    seen = {}

    def _llm(prompt, temperature=0.0):
        seen["prompt"] = prompt
        return '["Slow Drift","Low Sun","Ash"]'

    out = amphion.suggest_titles("", "ambient, tape hiss", llm=_llm)
    assert out[0] == "Slow Drift"
    assert "ambient, tape hiss" in seen["prompt"]
    assert "instrumental" in seen["prompt"].lower()


def test_nothing_to_name_from_is_refused_before_the_model():
    called = {"n": 0}

    def _llm(prompt, temperature=0.0):
        called["n"] += 1
        return "[]"

    with pytest.raises(amphion.SuggestFailed):
        amphion.suggest_titles("", "", llm=_llm)
    assert called["n"] == 0


def test_suggest_asks_the_model_for_variety_not_determinism():
    """Temperature 0 would return the identical list on every press, which reads
    as a broken button."""
    seen = {}

    def _llm(prompt, temperature=0.0):
        seen["t"] = temperature
        return '["A","B","C"]'

    amphion.suggest_titles("w", "t", llm=_llm)
    assert seen["t"] > 0


def test_suggest_makes_no_floor_call(monkeypatch):
    """THE INVARIANT. Titles label lyrics that already passed the floor at render;
    floor_check gates what gets made, not what it is called."""
    def _boom(*a, **k):
        raise AssertionError("the floor was called on the titling path")

    monkeypatch.setattr(morpheus, "floor_check", _boom)
    monkeypatch.setattr(morpheus, "_floor_judge", _boom)
    monkeypatch.setattr(amphion, "voice_clone_refusal", _boom)
    monkeypatch.setattr(amphion, "copyright_refusal", _boom)
    monkeypatch.setattr(amphion, "suggest_titles", lambda l, t: ["Blue Hour", "Low Sun", "Ash"])

    r = client.post("/amphion/suggest_title",
                    json={"lyrics": "a minor, intimate", "tags": "A minor, breathy"},
                    headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["titles"][0] == "Blue Hour"


def test_the_floor_spy_can_actually_see_a_call(monkeypatch):
    """Guard the guard. If floor_check stopped being reachable from the generate
    route, the test above would pass for the wrong reason and keep passing."""
    def _boom(*a, **k):
        raise AssertionError("floor called")

    monkeypatch.setattr(morpheus, "floor_check", _boom)
    with pytest.raises(AssertionError, match="floor called"):
        _generate(title="Blue Hour")


def test_suggest_route_400s_with_nothing_to_name_from():
    r = client.post("/amphion/suggest_title", json={"lyrics": "", "tags": ""}, headers=HEADERS)
    assert r.status_code == 400


def test_suggest_route_reports_a_dead_model_visibly(monkeypatch):
    """Acceptance 5: Ollama killed mid-suggest. The failure must be SAYABLE — a
    503 carrying the message — not a 500 and not a silent empty list."""
    def _dead(lyrics, tags):
        raise amphion.SuggestFailed("suggestion failed — name it yourself")

    monkeypatch.setattr(amphion, "suggest_titles", _dead)
    r = client.post("/amphion/suggest_title", json={"lyrics": "w", "tags": "t"}, headers=HEADERS)
    assert r.status_code == 503
    assert "name it yourself" in r.json()["detail"]


def test_a_render_still_works_with_the_model_down(open_floor, monkeypatch):
    """The other half of acceptance 5. The render path must not touch the model
    at all, so killing it changes nothing about generating."""
    def _boom(*a, **k):
        raise AssertionError("the render path called the local model")

    monkeypatch.setattr(amphion, "suggest_titles", _boom)
    monkeypatch.setattr(amphion, "_default_llm", _boom)
    r = _generate(title="", seed=99)
    assert r.status_code == 200, r.text
    assert _rendered[0]["title"].startswith("untitled-99-")


# ══ 5. Titles through the render routes ══════════════════════════════════════
def test_generate_carries_the_title_and_slug_into_the_job(open_floor):
    assert _generate(title="Blue Hour").status_code == 200
    assert _rendered[0]["title"] == "Blue Hour"
    assert _rendered[0]["slug"] == "blue-hour"


def test_generate_keeps_punctuation_and_emoji_verbatim_but_slugs_clean(open_floor):
    """Acceptance 2. The display title is the user's; the filename is ASCII."""
    assert _generate(title="Don't Look Back 🌙!").status_code == 200
    assert _rendered[0]["title"] == "Don't Look Back 🌙!"
    assert _rendered[0]["slug"] == "don-t-look-back"


def test_blank_title_at_render_becomes_untitled_seed_date(open_floor):
    """Acceptance 3."""
    assert _generate(title="", seed=4242).status_code == 200
    assert _rendered[0]["title"] == _rendered[0]["slug"]
    assert _rendered[0]["title"].startswith("untitled-4242-")


def test_a_render_with_no_title_key_at_all_is_still_named(open_floor):
    """An older client, or the chat tool, sends no title field. Nothing ships nameless."""
    assert _generate().status_code == 200
    assert _rendered[0]["title"].startswith("untitled-")
    assert _rendered[0]["slug"]


def test_variations_share_a_title_and_get_distinct_slugs(open_floor):
    r = client.post("/amphion/variations",
                    json={"tags": "indie rock", "lyrics": "", "seconds": 30,
                          "count": 3, "seed": 100, "title": "Blue Hour"},
                    headers=HEADERS)
    assert r.status_code == 200, r.text
    titles = [p["title"] for p in _rendered]
    slugs = [p["slug"] for p in _rendered]
    assert titles == ["Blue Hour"] * 3
    assert len(set(slugs)) == 3 and slugs[0] == "blue-hour"


# ══ 6. The sidecar and the embedded metadata ═════════════════════════════════
def test_sidecar_records_title_and_slug(tmp_path):
    """The sidecar dict is a WHITELIST — a title passed in `p` and not named here
    would vanish silently and the metadata would fall back with nothing to show why."""
    path = amphion._songs_dir() / "abc123.flac"
    amphion._write_sidecar("abc123", {"title": "Blue Hour", "slug": "blue-hour",
                                      "tags": "indie", "seed": 7}, path)
    side = json.loads(path.with_suffix(".json").read_text())
    assert side["title"] == "Blue Hour"
    assert side["slug"] == "blue-hour"


def test_metadata_carries_the_display_title_verbatim():
    """Acceptance 2, at the ffmpeg boundary: emoji and punctuation survive INTO
    the file even though the filename cannot hold them."""
    tags = amphion._tags_for("abc123", {"title": "Don't Look Back 🌙", "seed": 7}, "flac")
    assert "title=Don't Look Back 🌙" in tags


def test_metadata_and_filename_agree_for_a_track_from_before_titling():
    """A sidecar with no title at all. It used to read 'Amphion <job_id>' in the
    metadata while the file was named by the job id — now both say the same
    untitled- name, derived from the record that already exists."""
    _write_track("abc123", seed=7, created_at="2026-08-01T10:00:00+00:00")
    side = amphion._sidecar_for("abc123")
    assert amphion.slug_for("abc123", side) == "untitled-7-20260801"
    assert "title=untitled-7-20260801" in amphion._tags_for("abc123", side, "flac")


def test_library_reports_the_title(open_floor):
    _write_track("abc123", title="Blue Hour", slug="blue-hour", seed=7)
    r = client.get("/amphion/library", headers=HEADERS)
    song = next(s for s in r.json()["songs"] if s["job_id"] == "abc123")
    assert song["title"] == "Blue Hour" and song["slug"] == "blue-hour"


# ══ 7. The export filename ═══════════════════════════════════════════════════
def test_export_filename_is_the_slug(monkeypatch):
    """Acceptance 1: the name that lands in a Downloads folder. ffmpeg is stubbed
    — this is about the filename, not the transcode."""
    _write_track("abc123", title="Blue Hour", slug="blue-hour", seed=7)

    class _Ok:
        returncode, stdout, stderr = 0, "0", ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Ok())
    data, mt, filename = amphion.export_bytes("abc123", "mp3")
    assert filename == "blue-hour.mp3"


def test_export_filename_for_a_track_from_before_titling(monkeypatch):
    class _Ok:
        returncode, stdout, stderr = 0, "0", ""

    _write_track("abc123", seed=7, created_at="2026-08-01T10:00:00+00:00")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Ok())
    assert amphion.export_bytes("abc123", "flac")[2] == "untitled-7-20260801.flac"


# ══ 8. Rename ════════════════════════════════════════════════════════════════
def test_rename_updates_the_title_and_leaves_the_file_alone():
    """Acceptance 6. Renaming the master would break every link, remix chain and
    download URL already in flight, to change a label."""
    _write_track("abc123", title="Blue Hour", slug="blue-hour", seed=7)
    before = sorted(p.name for p in amphion._songs_dir().iterdir())

    res = amphion.rename_song("abc123", "Low Sun")
    assert res["title"] == "Low Sun"
    assert res["slug"] == "blue-hour"                     # unchanged, on purpose
    assert amphion._sidecar_for("abc123")["title"] == "Low Sun"
    assert sorted(p.name for p in amphion._songs_dir().iterdir()) == before


def test_rename_changes_what_the_next_export_stamps(monkeypatch):
    """No separate metadata write exists, and none is needed: tags are built from
    the sidecar at export time. If that ever stops being true, this fails."""
    class _Ok:
        returncode, stdout, stderr = 0, "0", ""

    _write_track("abc123", title="Blue Hour", slug="blue-hour", seed=7)
    amphion.rename_song("abc123", "Low Sun")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Ok())
    side = amphion._sidecar_for("abc123")
    assert "title=Low Sun" in amphion._tags_for("abc123", side, "flac")
    assert amphion.export_bytes("abc123", "flac")[2] == "blue-hour.flac"


def test_rename_to_blank_falls_back_rather_than_leaving_it_nameless():
    _write_track("abc123", title="Blue Hour", slug="blue-hour", seed=7,
                 created_at="2026-08-01T10:00:00+00:00")
    assert amphion.rename_song("abc123", "   ")["title"] == "untitled-7-20260801"


def test_rename_route(open_floor):
    _write_track("abc123", title="Blue Hour", slug="blue-hour", seed=7)
    r = client.post("/amphion/song/abc123/title", json={"title": "Low Sun"}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["title"] == "Low Sun"


def test_rename_route_404s_on_an_unknown_track():
    r = client.post("/amphion/song/abcdef/title", json={"title": "X"}, headers=HEADERS)
    assert r.status_code == 404


def test_rename_route_rejects_a_bad_id():
    r = client.post("/amphion/song/..%2Fetc/title", json={"title": "X"}, headers=HEADERS)
    assert r.status_code in (400, 404)
