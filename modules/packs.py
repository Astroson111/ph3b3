"""packs — install, update and remove Ph3b3 story packs.

Local operations on directories. There is no storefront here and no payment
code; a pack arrives as a directory or a zip and this manages it from there.

── WHAT A PACK IS ──────────────────────────────────────────────────────────
    <pack>/
      manifest.json     name, version, author, description, stories[]
      <story>.md        one file per story
      assets/           optional companion briefs (art prompts, music briefs)

    manifest.stories[] entry:
      slug        required, [a-z0-9_-], unique within the pack
      file        defaults to "<slug>.md"
      title       shown to a person
      aliases     how someone actually asks for it
      verbatim    true = told word for word; false/absent = she may perform it
      companion   optional art/music briefs, following the shape used by canon

── THE THREE INVARIANTS, AND HOW EACH IS ENFORCED ──────────────────────────
1. CANON IS IMMUTABLE BY PACK OPERATIONS.
   Enforced by construction: every path this module writes to or deletes is
   built as PACKS_DIR / <name>, resolved, and checked to still be inside
   PACKS_DIR. install() refuses the name "canon" outright. Nothing here can
   express a path into stories/canon/ — it is not a rule applied afterwards,
   it is a place this code cannot reach.

2. NO NETWORK IS REQUIRED FOR INSTALLED CONTENT.
   This module opens no sockets. No licence check, no activation, no expiry, no
   heartbeat. A pack installed once works on a machine that never goes online
   again. Nothing is written that could later be checked for validity, because
   the moment such a field exists someone will be tempted to verify it.

3. UNINSTALL NEVER TOUCHES DERIVATIVES.
   Everything Morpheus, Amphion or Dio makes from a story lives in PH3B3_DATA —
   images, songs, filed retellings — and uninstall only ever removes
   stories/packs/<name>/. It does not know where derivatives live and has no
   business knowing. Buying a pack, using it, and removing it leaves everything
   you made intact.

── UPDATES ARE ADDITIVE ────────────────────────────────────────────────────
update() writes new and changed story files and leaves everything else alone.
It does NOT remove stories dropped from the new manifest: a story you have read
and made art from does not vanish because a publisher reorganised a release.
Declining an update is always safe — an older pack keeps working forever, which
is what "buy once, keep forever" has to mean if it means anything.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import zipfile
from pathlib import Path

try:
    from paths import PH3B3_HOME
except ImportError:                                  # standalone / test import
    from modules.paths import PH3B3_HOME

log = logging.getLogger("ph3b3.packs")

STORIES_DIR = Path(PH3B3_HOME) / "stories"
CANON_DIR = STORIES_DIR / "canon"
PACKS_DIR = STORIES_DIR / "packs"
MANIFEST = "manifest.json"

_NAME_OK = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

RESERVED = {"canon"}          # the one name a pack may never take


class PackError(Exception):
    """Refused. The message is safe to show a person."""


def _pack_path(name: str) -> Path:
    """The only way this module names a location on disk.

    Every write and every delete goes through here, so "a pack operation cannot
    reach canon" is a property of the path construction rather than a check
    someone might forget to call."""
    if not name or not _NAME_OK.match(name):
        raise PackError(f"not a usable pack name: {name!r}")
    if name in RESERVED:
        raise PackError(f"{name!r} is reserved — canon is not a pack and cannot be replaced by one")
    p = (PACKS_DIR / name).resolve()
    if PACKS_DIR.resolve() not in p.parents:
        raise PackError("refusing a path outside the packs directory")
    if p == CANON_DIR.resolve() or CANON_DIR.resolve() in p.parents:
        raise PackError("refusing a path inside canon")
    return p


def validate(src: Path) -> dict:
    """Check a pack directory before it is installed. Returns the manifest.

    Everything is validated BEFORE anything is written, so a bad pack cannot
    leave a half-installed directory behind."""
    src = Path(src)
    if not src.is_dir():
        raise PackError("that is not a pack directory")
    try:
        m = json.loads((src / MANIFEST).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PackError("no manifest.json in that pack")
    except Exception as e:
        raise PackError(f"manifest.json is not readable JSON ({e})")

    if not isinstance(m, dict):
        raise PackError("manifest.json is not an object")
    name = str(m.get("name") or "").strip()
    if not _NAME_OK.match(name):
        raise PackError(f"manifest name is not usable: {name!r}")
    if name in RESERVED:
        raise PackError(f"{name!r} is reserved — canon cannot be shipped as a pack")
    stories = m.get("stories")
    if not isinstance(stories, list) or not stories:
        raise PackError("manifest lists no stories")

    seen = set()
    for st in stories:
        if not isinstance(st, dict):
            raise PackError("a story entry is not an object")
        slug = str(st.get("slug") or "").strip()
        if not _SLUG_OK.match(slug):
            raise PackError(f"not a usable story slug: {slug!r}")
        if slug in seen:
            raise PackError(f"duplicate story slug in manifest: {slug!r}")
        seen.add(slug)
        f = str(st.get("file") or f"{slug}.md")
        # A manifest is data from elsewhere. It does not get to name a path
        # outside its own directory.
        if "/" in f or "\\" in f or f.startswith("."):
            raise PackError(f"story file must be a plain filename: {f!r}")
        if not (src / f).is_file():
            raise PackError(f"manifest lists {slug!r} but {f} is not in the pack")
    m.setdefault("version", "0.0.0")
    return m


def _copy_stories(src: Path, dst: Path, m: dict) -> tuple[int, int]:
    """Copy manifest + story files + optional assets. Returns (added, updated)."""
    dst.mkdir(parents=True, exist_ok=True)
    added = updated = 0
    for st in m["stories"]:
        f = str(st.get("file") or f"{st['slug']}.md")
        s, d = src / f, dst / f
        if d.exists():
            if s.read_bytes() != d.read_bytes():
                shutil.copy2(s, d); updated += 1
        else:
            shutil.copy2(s, d); added += 1
    shutil.copy2(src / MANIFEST, dst / MANIFEST)
    if (src / "assets").is_dir():
        shutil.copytree(src / "assets", dst / "assets", dirs_exist_ok=True)
    return added, updated


def install(src: Path) -> dict:
    """Install a pack from a directory or a .zip. Refuses to overwrite."""
    src = Path(src)
    tmp = None
    try:
        if src.is_file() and src.suffix.lower() == ".zip":
            tmp = PACKS_DIR / f".unpack-{src.stem}"
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.mkdir(parents=True)
            with zipfile.ZipFile(src) as z:
                for n in z.namelist():
                    # Zip entries are attacker-controlled names. Refuse anything
                    # that climbs out of the extraction directory.
                    p = (tmp / n).resolve()
                    if tmp.resolve() not in p.parents and p != tmp.resolve():
                        raise PackError(f"refusing zip entry outside the pack: {n!r}")
                z.extractall(tmp)
            roots = [d for d in tmp.iterdir() if d.is_dir()]
            src = roots[0] if (len(roots) == 1 and not (tmp / MANIFEST).exists()) else tmp

        m = validate(src)
        dst = _pack_path(m["name"])
        if dst.exists():
            raise PackError(f"{m['name']!r} is already installed — use update()")
        added, _ = _copy_stories(src, dst, m)
        log.info("[packs] installed %s v%s (%d stories)", m["name"], m["version"], added)
        return {"ok": True, "name": m["name"], "version": m["version"], "added": added}
    finally:
        if tmp and tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def update(src: Path) -> dict:
    """Apply a newer version over an installed pack. ADDITIVE.

    New and changed story files are written. Stories the new manifest drops are
    LEFT IN PLACE — a story someone has read, and made art from, does not
    disappear because a publisher reorganised a release. Nothing a user
    generated is touched, because none of it lives here.
    """
    src = Path(src)
    m = validate(src)
    dst = _pack_path(m["name"])
    if not dst.exists():
        raise PackError(f"{m['name']!r} is not installed — use install()")
    before = _read_installed_manifest(dst)
    added, updated = _copy_stories(src, dst, m)

    # MERGE the manifests, do not replace them.
    #
    # Keeping the dropped story's FILE is not enough: discovery reads the
    # manifest, so a story absent from it is invisible even though its bytes are
    # right there. That is a deletion in every sense a reader cares about, and it
    # was the first thing the test caught.
    #
    # So an entry the new manifest dropped is carried forward whenever its file
    # is still present. The pack's own version becomes the new one; the story
    # list is the union.
    new_slugs = {x["slug"] for x in m["stories"]}
    kept = []
    for old in (before or {}).get("stories", []):
        slug = old.get("slug")
        if not slug or slug in new_slugs:
            continue
        f = old.get("file") or f"{slug}.md"
        if (dst / f).is_file():
            m["stories"].append(old)
            kept.append(slug)
    if kept:
        log.info("[packs] %s: %d story(ies) dropped upstream, kept and still "
                 "readable: %s", m["name"], len(kept), ", ".join(kept))
    merged = {k: v for k, v in m.items() if not k.startswith("_")}
    (dst / MANIFEST).write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return {"ok": True, "name": m["name"],
            "version": m["version"], "from": (before or {}).get("version"),
            "added": added, "updated": updated, "kept_removed_upstream": kept}


def _read_installed_manifest(d: Path) -> dict | None:
    try:
        return json.loads((d / MANIFEST).read_text(encoding="utf-8"))
    except Exception:
        return None


def _assert_disjoint_from_derivatives(target: Path) -> None:
    """Refuse to delete anything that is, or contains, a derivative root.

    The invariant is currently true by geography: packs live in the repo and
    everything generated lives in PH3B3_DATA and MORPHEUS_DATA, which are
    different trees. Geography is not a guarantee — someone sets PH3B3_HOME to
    the data directory, or a future layout puts them under one root, and a
    delete that was always safe silently stops being safe.

    So it is checked at the moment of deletion, against the actual configured
    roots, every time. Cheap, and it converts "these happen to be different
    places" into "this cannot run if they ever stop being".
    """
    roots = []
    try:
        from paths import PH3B3_DATA, MORPHEUS_DATA
    except ImportError:                                  # standalone / test import
        from modules.paths import PH3B3_DATA, MORPHEUS_DATA
    roots += [Path(PH3B3_DATA), Path(MORPHEUS_DATA)]
    t = target.resolve()
    for r in roots:
        try:
            r = r.resolve()
        except OSError:
            continue
        if t == r or r in t.parents or t in r.parents:
            raise PackError(
                "refusing to delete: the pack directory overlaps a derivative "
                f"root ({r}). Nothing a user generated may sit under a path a "
                "pack operation can remove.")


def uninstall(name: str) -> dict:
    """Remove an installed pack's directory. Nothing else.

    Derivatives are untouched and unreachable from here: images, songs and
    filed retellings live in PH3B3_DATA and MORPHEUS_DATA, this only removes
    stories/packs/<name>/, and it has no path to anywhere else.

    Removing a pack removes the STORIES. Everything made FROM them — art,
    songs, retellings she filed — is somebody's work and stays, whether or not
    the pack that inspired it is still installed.
    """
    dst = _pack_path(name)
    _assert_disjoint_from_derivatives(dst)
    if not dst.exists():
        raise PackError(f"{name!r} is not installed")
    shutil.rmtree(dst)
    log.info("[packs] uninstalled %s (derivatives untouched)", name)
    return {"ok": True, "name": name}


def installed() -> list[dict]:
    """Installed packs, newest-listed first by name. Canon is not a pack."""
    out = []
    if PACKS_DIR.is_dir():
        for d in sorted(p for p in PACKS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")):
            m = _read_installed_manifest(d)
            if m:
                out.append({"name": m.get("name", d.name), "version": m.get("version", "?"),
                            "author": m.get("author", ""), "stories": len(m.get("stories", []))})
    return out
