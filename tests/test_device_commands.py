"""Device-command intent gate — parser tests (iris-track-playback-spec Phase 1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))
import device_commands as dc


def test_play_track_digits_and_words():
    assert dc.parse("play track 3") == {"action": "play_track", "index": 3}
    assert dc.parse("play track three") == {"action": "play_track", "index": 3}
    assert dc.parse("Play Track Seven") == {"action": "play_track", "index": 7}
    assert dc.parse("play track twenty") == {"action": "play_track", "index": 20}
    assert dc.parse("start track 12") == {"action": "play_track", "index": 12}
    assert dc.parse("play track number 5") == {"action": "play_track", "index": 5}


def test_wake_word_and_punctuation_stripped():
    assert dc.parse("Hey Ph3b3, play track 1.") == {"action": "play_track", "index": 1}
    assert dc.parse("Phoebe play track two") == {"action": "play_track", "index": 2}
    assert dc.parse("  play track 9!  ") == {"action": "play_track", "index": 9}


def test_natural_polite_phrasing():
    # Polite framing around the command must not defeat the match (live-voice cases).
    assert dc.parse("Hey Phoebe, can you play track one please?") == {"action": "play_track", "index": 1}
    assert dc.parse("Hey, can you play track one, please?") == {"action": "play_track", "index": 1}
    assert dc.parse("Could you play track 3 for me") == {"action": "play_track", "index": 3}
    assert dc.parse("please play track two") == {"action": "play_track", "index": 2}
    assert dc.parse("just play track five thanks") == {"action": "play_track", "index": 5}
    assert dc.parse("could you stop the music please") == {"action": "stop"}
    assert dc.parse("can you turn it up") == {"action": "volume_up"}
    assert dc.parse("would you turn it down please") == {"action": "volume_down"}


def test_stop():
    for u in ("stop the music", "stop playing", "pause the track", "stop", "pause the audio", "stop the song"):
        assert dc.parse(u) == {"action": "stop"}, u


def test_volume():
    for u in ("volume up", "louder", "turn it up"):
        assert dc.parse(u) == {"action": "volume_up"}, u
    for u in ("volume down", "quieter", "turn it down", "softer"):
        assert dc.parse(u) == {"action": "volume_down"}, u


def test_anchored_no_false_positives():
    # The command must be essentially the WHOLE utterance — extra words → no match.
    for u in (
        "tell me a story about a play track",
        "what track is playing",
        "can you play track 3 later maybe",
        "i want to play track three after dinner",
        "what's the weather like",
        "play some music",              # no 'track N'
        "play track",                   # no number
        "play track banana",            # unparseable number
        "the volume is up",
        "",
        "   ",
    ):
        assert dc.parse(u) is None, f"false positive: {u!r}"


def test_weather_is_not_a_command():
    assert dc.parse("Hey Ph3b3, what's the weather like") is None


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"ok  {fn.__name__}")
        except Exception:
            print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"{ok}/{len(fns)} passed")
