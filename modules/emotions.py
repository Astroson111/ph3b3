"""Emotional state registry — the single source of emotion terms for every consumer.

Supersedes modules/moods.py. The difference is not the vocabulary, it is the
lifetime. A mood was a property of ONE piece of work, chosen fresh and forgotten.
An emotion is a STANDING state: it holds until changed, it survives a restart,
and it is broadcast to the devices so Dio's face and Iris's UI wear it too.

Two pieces of state, and keeping them distinct is the whole design:

  selected — what the user picked in the panel. One of NONE, AUTO, or an id.
             Only a human changes this.
  resolved — the emotion actually in force right now. Equal to `selected` for a
             manual pick. Under AUTO it is whatever the last inference read from
             the conversation, and it moves on its own.

The selector keeps showing "Auto" while the resolved state drifts underneath it,
which is what "Auto overrides" has to mean — the user's choice of *how* the state
is decided is not silently rewritten into a fixed state the first time she reads
the room. Collapsing these two into one field is the bug this docstring exists to
prevent.

Registry is config/emotions.yaml, re-read on every lookup so edits apply without
a restart. On this box a restart of ph3b3 redeploys whatever branch is checked
out, so hot-reload is the cheaper and safer of the two options, not merely the
more convenient one. Runtime state persists to PH3B3_DATA/emotion.json, the same
split voices.py uses: repo config for the vocabulary, data dir for the choice.

FAILURE MODE IS "NO EMOTION". A missing, unreadable or malformed emotions.yaml
yields an empty registry, which makes every lookup behave exactly like NONE — the
zero-behaviour-change anchor. A broken data file must never break generation, and
must never leave her stuck wearing a state nobody can clear.

SAFETY: this module composes text only. It runs BEFORE the content floor and has
no knowledge of it. Terms from this file are appended to the prompt and the floor
then inspects the composed result exactly as it inspects any other prompt, so a
hostile edit to emotions.yaml is floored like any other input rather than smuggled
through. Nothing here may ever be given a floor bypass.

Alba is untouched. No value in this registry reaches TTS by any path. `cadence`
is the Iris UI's animation rate, never speech rate.
"""
import json
import logging
import threading
import time
from pathlib import Path

try:
    from paths import PH3B3_HOME, PH3B3_DATA
except ImportError:
    from modules.paths import PH3B3_HOME, PH3B3_DATA

log = logging.getLogger("ph3b3.emotions")

EMOTIONS_PATH = Path(PH3B3_HOME) / "config" / "emotions.yaml"
STATE_PATH = Path(PH3B3_DATA) / "emotion.json"      # runtime choice, not repo config

NONE = "none"    # explicit no-emotion; the regression anchor
AUTO = "auto"    # she reads the conversation and sets the state herself
DEFAULT = NONE

_lock = threading.Lock()

# Face states Dio's firmware actually has today (Ph3b3Face::State). A `base` in
# emotions.yaml outside this set is dropped rather than broadcast, so a typo in
# the table can never hand the firmware a state it will not recognise.
_DIO_BASES = {"IDLE", "THINKING", "FOCUSED", "LISTENING", "SPEAKING", "ERROR",
              "BOOT", "CONNECTING"}


def load_registry() -> dict:
    """Parse config/emotions.yaml → {id: {...}}. Reloaded per call so edits apply
    without a restart. Returns {} on any failure, which degrades to 'no emotion'."""
    try:
        import yaml
        with open(EMOTIONS_PATH, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        table = doc.get("emotions") or {}
        if not isinstance(table, dict):
            raise ValueError("'emotions' is not a mapping")
        return table
    except FileNotFoundError:
        log.warning("emotions.yaml not found at %s — emotion selector inert", EMOTIONS_PATH)
        return {}
    except Exception as e:
        log.warning("emotions.yaml load failed (%s) — emotion selector inert", e)
        return {}


def registry_stamp() -> float | None:
    """mtime of emotions.yaml, or None if absent. Surfaced by the API so a stale
    read is always visible rather than silent."""
    try:
        return EMOTIONS_PATH.stat().st_mtime
    except OSError:
        return None


def list_emotions() -> list[dict]:
    """[{id, label}] for the selector, sorted by label. The panel renders whatever
    this returns and hardcodes nothing, so a new emotion needs no UI change."""
    reg = load_registry()
    out = [{"id": k, "label": (v or {}).get("label") or k} for k, v in reg.items()]
    return sorted(out, key=lambda m: m["label"].lower())


def is_named(emotion_id: str | None) -> bool:
    """True only for an emotion that actually exists in the table. NONE, AUTO,
    None, and any unknown id are all False — unknown ids degrade to no-emotion
    rather than erroring, so a stale selector value or a retired entry cannot
    break generation."""
    if not emotion_id or emotion_id in (NONE, AUTO):
        return False
    return emotion_id in load_registry()


def is_selectable(emotion_id: str | None) -> bool:
    """True for anything the panel may POST: NONE, AUTO, or a real emotion."""
    return emotion_id in (NONE, AUTO) or is_named(emotion_id)


# ── Runtime state ────────────────────────────────────────────────────────────

def _read_state() -> dict:
    try:
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    selected = d.get("selected") or DEFAULT
    resolved = d.get("resolved") or NONE
    # Validate on READ, not only on write. The file outlives the table: an
    # emotion retired from emotions.yaml leaves a stale id on disk, and a state
    # nobody can name must not survive as a state she is stuck wearing.
    if not is_selectable(selected):
        selected = DEFAULT
    if selected == AUTO:
        if not is_named(resolved):
            resolved = NONE
    else:
        resolved = selected                    # manual pick: the two are the same
    return {"selected": selected, "resolved": resolved,
            "source": d.get("source") if d.get("source") in ("manual", "auto") else "manual",
            "since": d.get("since") or 0.0}


def _write_state(d: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(d), encoding="utf-8")
    except Exception as e:                     # a read-only data dir must not 500
        log.warning("emotion state save failed (%s) — holding in memory only", e)


def get_state() -> dict:
    """{selected, resolved, source, since} — never raises."""
    with _lock:
        return _read_state()


def set_selected(emotion_id: str) -> dict:
    """A human's pick. Resets `resolved` to match unless AUTO was chosen, in which
    case the next inference fills it in and NONE is worn until then."""
    if not is_selectable(emotion_id):
        raise ValueError(f"unknown emotion: {emotion_id!r}")
    with _lock:
        st = {"selected": emotion_id,
              "resolved": NONE if emotion_id == AUTO else emotion_id,
              "source": "manual", "since": time.time()}
        _write_state(st)
        return _read_state()


def set_resolved(emotion_id: str) -> dict:
    """Auto's read. IGNORED unless AUTO is selected — an inference must never be
    able to overwrite a state a human chose on purpose. That asymmetry is the
    whole contract of the selector: manual wins until manually changed."""
    with _lock:
        cur = _read_state()
        if cur["selected"] != AUTO:
            return cur
        if not is_named(emotion_id):
            emotion_id = NONE
        if cur["resolved"] == emotion_id:      # no churn, keep `since` meaningful
            return cur
        st = {"selected": AUTO, "resolved": emotion_id,
              "source": "auto", "since": time.time()}
        _write_state(st)
        return _read_state()


def active() -> str:
    """The emotion in force right now — an id, or NONE. This is what every
    consumer should ask for; nothing outside this module should reason about the
    selected/resolved split."""
    return get_state()["resolved"]


# ── Vocabulary ───────────────────────────────────────────────────────────────

def _terms(emotion_id: str, section: str, keys: tuple[str, ...]) -> str:
    entry = load_registry().get(emotion_id) or {}
    block = entry.get(section) or {}
    if not isinstance(block, dict):
        return ""
    vals = [str(block.get(k)).strip() for k in keys if block.get(k)]
    return ", ".join(v for v in vals if v)


def amphion_terms(emotion_id: str) -> str:
    """Key/mode, tempo range and arrangement for a song prompt."""
    return _terms(emotion_id, "amphion", ("key", "tempo", "arrangement"))


def morpheus_terms(emotion_id: str) -> str:
    """Palette, lighting and atmosphere for an image prompt."""
    return _terms(emotion_id, "morpheus", ("palette", "lighting", "atmosphere"))


def chat_terms(emotion_id: str) -> str:
    """One prose direction for chat, story and narrative tone."""
    entry = load_registry().get(emotion_id) or {}
    return str(entry.get("chat") or "").strip()


def compose(prompt: str, terms: str) -> str:
    """Append emotion terms to a prompt. Comma-joined because both the Amphion tag
    string and the Morpheus positive prompt are comma-separated term lists.

    Returns the prompt UNCHANGED when there are no terms — that identity is what
    makes NONE a true zero-behaviour-change path rather than a path that merely
    adds nothing visible.
    """
    prompt = (prompt or "").strip()
    terms = (terms or "").strip()
    if not terms:
        return prompt
    if not prompt:
        return terms
    return f"{prompt}, {terms}"


def label_of(emotion_id: str) -> str:
    entry = load_registry().get(emotion_id) or {}
    return entry.get("label") or emotion_id


# ── Device render parameters ─────────────────────────────────────────────────
# Clamped HERE rather than trusted from the table, because these cross a wire to
# firmware that will index arrays and scale pixels with them. A hand-edited
# emotions.yaml is a config file, not an attacker, but an out-of-range float that
# reaches a display driver is a crash on a device that is awkward to recover —
# and the flash cycle to fix it is the expensive part.

def _num(block: dict, key: str, lo: float, hi: float, default: float) -> float:
    try:
        v = float(block.get(key, default))
    except (TypeError, ValueError):
        return default
    if v != v:                                  # NaN
        return default
    return max(lo, min(hi, v))


def dio_params(emotion_id: str) -> dict | None:
    """Dio's face parameters, or None when the emotion contributes no face."""
    entry = load_registry().get(emotion_id) or {}
    block = entry.get("dio")
    if not isinstance(block, dict) or not block:
        return None
    base = str(block.get("base") or "").strip().upper()
    return {"base": base if base in _DIO_BASES else "IDLE",
            "bright": _num(block, "bright", 0.0, 1.0, 1.0),
            "mouth":  _num(block, "mouth", -1.0, 1.0, 0.0),
            "eyelid": _num(block, "eyelid", 0.0, 1.0, 0.3),
            "blush":  bool(block.get("blush"))}


def iris_params(emotion_id: str) -> dict | None:
    """Iris's UI parameters, or None when the emotion contributes no UI."""
    entry = load_registry().get(emotion_id) or {}
    block = entry.get("iris")
    if not isinstance(block, dict) or not block:
        return None
    return {"temp": _num(block, "temp", -1.0, 1.0, 0.0),
            "cadence": _num(block, "cadence", 0.5, 1.5, 1.0)}


def announce(emotion_id: str) -> str:
    """Auto's read, stated in her own voice. Short on purpose: it has to be
    objectable at a glance, and a wall of vocabulary is not."""
    if not is_named(emotion_id):
        return ""
    return f"feeling {label_of(emotion_id).lower()} — say otherwise"


def broadcast() -> dict:
    """The device payload. One shape, served to Dio and Iris alike; each reads
    the block it cares about and ignores the rest.

    `emotion` is always present and is NONE when nothing is set, so firmware can
    branch on one field without inspecting the sub-blocks. `stamp` lets a device
    skip redrawing when nothing has changed, which matters on a poll loop.
    """
    st = get_state()
    cur = st["resolved"]
    named = is_named(cur)
    return {"emotion": cur if named else NONE,
            "label": label_of(cur) if named else None,
            "selected": st["selected"],
            "source": st["source"],
            "dio": dio_params(cur) if named else None,
            "iris": iris_params(cur) if named else None,
            "stamp": st["since"]}
