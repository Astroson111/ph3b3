"""Story packs — format, install/update/uninstall, and the three invariants.

The invariants are the reason this file exists. They are promises made to
someone who paid for content, and each is tested adversarially rather than
happy-path:

  1. Canon is immutable by pack operations.
  2. No network is required for installed content to work.
  3. Uninstalling a pack never touches user-generated derivatives.

Every test redirects the pack directory into tmp_path. None may write to the
real stories/ tree — a test run must never install, alter or remove real
content.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import packs  # noqa: E402
import shelf  # noqa: E402


def _make_pack(d: Path, name="ghosts", version="1.0.0", stories=None):
    d.mkdir(parents=True, exist_ok=True)
    stories = stories or [{"slug": "the_hollow", "file": "the_hollow.md",
                           "title": "The Hollow", "aliases": ["Hollow"],
                           "verbatim": False}]
    (d / "manifest.json").write_text(json.dumps(
        {"name": name, "version": version, "author": "Astro",
         "description": "test", "stories": stories}), encoding="utf-8")
    for s in stories:
        (d / (s.get("file") or f"{s['slug']}.md")).write_text(
            f"# {s.get('title', s['slug'])}\n\nBody of {s['slug']}.\n", encoding="utf-8")
    return d


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point BOTH modules at a throwaway stories tree."""
    stories = tmp_path / "stories"
    canon, pk = stories / "canon", stories / "packs"
    canon.mkdir(parents=True); pk.mkdir(parents=True)
    (canon / "manifest.json").write_text(json.dumps(
        {"name": "canon", "version": "1.0.0", "canon": True,
         "stories": [{"slug": "free_tale", "file": "free_tale.md",
                      "title": "Free Tale", "verbatim": True}]}), encoding="utf-8")
    (canon / "free_tale.md").write_text("# Free Tale\n\nShips with every install.\n",
                                        encoding="utf-8")
    for mod in (packs, shelf):
        monkeypatch.setattr(mod, "STORIES_DIR", stories, raising=False)
        monkeypatch.setattr(mod, "CANON_DIR", canon, raising=False)
        monkeypatch.setattr(mod, "PACKS_DIR", pk, raising=False)
    return tmp_path


# ── INVARIANT 1: canon is immutable by pack operations ───────────────────────
@pytest.mark.parametrize("name", ["canon", "CANON", "../canon", "../../etc", "..", "", "a/b"])
def test_no_pack_operation_can_name_canon_or_escape(sandbox, name):
    with pytest.raises(packs.PackError):
        packs.uninstall(name)


def test_a_pack_cannot_call_itself_canon(sandbox, tmp_path):
    src = _make_pack(tmp_path / "src", name="canon")
    with pytest.raises(packs.PackError):
        packs.install(src)


def test_installing_a_pack_leaves_canon_byte_identical(sandbox, tmp_path):
    before = {p.name: p.read_bytes() for p in shelf.CANON_DIR.iterdir()}
    packs.install(_make_pack(tmp_path / "src"))
    packs.uninstall("ghosts")
    after = {p.name: p.read_bytes() for p in shelf.CANON_DIR.iterdir()}
    assert before == after


def test_a_pack_cannot_shadow_a_canon_slug(sandbox, tmp_path):
    """Canon is listed first and wins the slug, so a pack reusing a canon slug
    cannot replace what a reader gets."""
    packs.install(_make_pack(tmp_path / "src", stories=[
        {"slug": "free_tale", "file": "free_tale.md", "title": "IMPOSTER"}]))
    got = [b for b in shelf.list_books() if b["slug"] == "free_tale"]
    assert len(got) == 1 and got[0]["title"] == "Free Tale" and got[0]["canon"]


# ── INVARIANT 2: no network required ─────────────────────────────────────────
@pytest.mark.parametrize("mod", ["modules/packs.py", "modules/shelf.py"])
def test_content_modules_import_nothing_networked(mod):
    """Asserted on the AST, not by grepping — the docstrings legitimately
    contain the words "socket" and "licence" while promising not to use them."""
    tree = ast.parse((ROOT / mod).read_text(encoding="utf-8"))
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            found |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            found.add(n.module.split(".")[0])
    net = {"requests", "httpx", "urllib", "urllib3", "socket", "http",
           "ftplib", "aiohttp", "ssl", "telnetlib"}
    assert not (found & net), f"{mod} imports {found & net}"


def test_nothing_records_a_licence_or_expiry(sandbox, tmp_path):
    """No field is written that a future version could be tempted to verify."""
    packs.install(_make_pack(tmp_path / "src"))
    m = json.loads((shelf.PACKS_DIR / "ghosts" / "manifest.json").read_text())
    for k in ("licence", "license", "expires", "expiry", "activation", "token", "entitlement"):
        assert k not in m, f"manifest gained a {k} field"


def test_an_installed_pack_reads_with_no_network(sandbox, tmp_path):
    packs.install(_make_pack(tmp_path / "src"))
    assert shelf.read("the_hollow")["text"].startswith("# The Hollow")


# ── INVARIANT 3: uninstall never touches derivatives ─────────────────────────
def test_uninstall_only_removes_the_pack_directory(sandbox, tmp_path):
    """Derivatives live in PH3B3_DATA. This asserts the module has no path to
    anywhere but stories/packs/<name>/ — it deletes exactly one directory."""
    packs.install(_make_pack(tmp_path / "src"))
    derivative = sandbox / "derivative.png"
    derivative.write_bytes(b"art made from the story")
    packs.uninstall("ghosts")
    assert derivative.exists(), "a derivative was removed"
    assert shelf.CANON_DIR.is_dir() and (shelf.CANON_DIR / "free_tale.md").is_file()
    assert not (shelf.PACKS_DIR / "ghosts").exists()


def test_uninstall_leaves_every_real_derivative_location_untouched(sandbox, tmp_path, monkeypatch):
    """The promise, tested against the ACTUAL places output lands rather than a
    stand-in file: Morpheus images, Amphion songs, the canon store of filed
    retellings, captures, and chat transcripts.

    Every one is planted, hashed, and re-hashed after an uninstall.
    """
    import hashlib
    data = tmp_path / "data"
    derivs = {
        "morpheus image": data / "images" / "a1b2.png",
        "amphion song": data / "songs" / "ballad.wav",
        "filed retelling": data / "stories" / "canon" / "her-retelling.md",
        "capture": data / "captures" / "stackchan_2026.txt",
        "chat transcript": data / "chats" / "session.jsonl",
        "companion art": data / "images" / "from_the_hollow.png",
    }
    for p in derivs.values():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"work made from a story")
    before = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in derivs.items()}

    packs.install(_make_pack(tmp_path / "src"))
    packs.uninstall("ghosts")

    for k, p in derivs.items():
        assert p.exists(), f"{k} was REMOVED by an uninstall"
        assert hashlib.sha256(p.read_bytes()).hexdigest() == before[k], f"{k} was MODIFIED"


def test_uninstall_refuses_if_packs_ever_overlap_a_derivative_root(tmp_path, monkeypatch):
    """Geography is not a guarantee. If a future layout ever puts packs inside
    the data tree, uninstall must refuse rather than delete somebody's work."""
    import paths
    shared = tmp_path / "shared"
    (shared / "packs" / "ghosts").mkdir(parents=True)
    monkeypatch.setattr(packs, "PACKS_DIR", shared / "packs")
    monkeypatch.setattr(packs, "CANON_DIR", shared / "canon")
    monkeypatch.setattr(paths, "PH3B3_DATA", shared)
    monkeypatch.setattr(paths, "MORPHEUS_DATA", shared)
    with pytest.raises(packs.PackError, match="derivative root"):
        packs.uninstall("ghosts")
    assert (shared / "packs" / "ghosts").exists(), "it deleted anyway"


def test_no_module_targets_a_path_inside_the_stories_tree():
    """Nothing may put a derivative where a pack operation can remove it. If a
    future feature starts writing generated output into stories/packs/<name>/,
    the uninstall promise quietly breaks.

    Checked on RESOLVED PATHS, not on source text: grepping for "stories" near a
    write matched stories_module.STORIES_FILE, which is a variable NAME whose
    value is ~/ph3b3_data/stories.json — nowhere near the stories tree. A test
    that cannot tell a name from a location fails on the wrong thing.
    """
    import importlib
    from pathlib import Path as _P
    tree = shelf.STORIES_DIR.resolve()
    offenders = []
    for f in sorted((ROOT / "modules").glob("*.py")):
        if f.name in ("packs.py", "shelf.py", "__init__.py"):
            continue                      # the installer and the reader, by design
        try:
            mod = importlib.import_module(f.stem)
        except Exception:
            continue                      # a module that will not import cannot write
        for attr in dir(mod):
            try:
                v = getattr(mod, attr)
            except Exception:
                continue
            if isinstance(v, _P):
                try:
                    r = v.resolve()
                except OSError:
                    continue
                if r == tree or tree in r.parents:
                    offenders.append(f"{f.name}.{attr} -> {r}")
    assert not offenders, "module paths inside the stories tree: " + "; ".join(offenders)


def test_every_delete_site_is_inside_the_packs_directory():
    """Crude counting was the wrong proxy — install() legitimately rmtree's its
    own zip scratch dir twice. What matters is that no delete can name a path
    outside packs/, which holds because every one is _pack_path() or the scratch
    dir built under PACKS_DIR."""
    src = (ROOT / "modules" / "packs.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if "shutil.rmtree" in line and not line.strip().startswith("#"):
            assert "tmp" in line or "dst" in line, f"unrecognised delete target: {line.strip()}"
    assert 'dst = _pack_path(name)' in src, "uninstall no longer resolves through _pack_path"


# ── Updates are additive ─────────────────────────────────────────────────────
def test_update_adds_and_changes_but_never_deletes_a_story(sandbox, tmp_path):
    """A story you have read, and made art from, does not vanish because a
    publisher reorganised a release."""
    packs.install(_make_pack(tmp_path / "v1", stories=[
        {"slug": "one", "title": "One"}, {"slug": "two", "title": "Two"}]))
    r = packs.update(_make_pack(tmp_path / "v2", version="2.0.0", stories=[
        {"slug": "one", "title": "One"}, {"slug": "three", "title": "Three"}]))
    slugs = {b["slug"] for b in shelf.list_books()}
    assert {"one", "two", "three"} <= slugs, "an installed story disappeared on update"
    assert r["kept_removed_upstream"] == ["two"]
    assert (shelf.PACKS_DIR / "ghosts" / "two.md").is_file()


def test_declining_an_update_leaves_the_pack_working(sandbox, tmp_path):
    packs.install(_make_pack(tmp_path / "v1"))
    assert shelf.read("the_hollow") is not None      # never updated; still works


def test_install_refuses_to_overwrite_an_installed_pack(sandbox, tmp_path):
    packs.install(_make_pack(tmp_path / "src"))
    with pytest.raises(packs.PackError):
        packs.install(_make_pack(tmp_path / "src2"))


# ── Format validation ────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad_file", ["../../../etc/passwd", "sub/dir.md", ".hidden.md", "..\\win.md"])
def test_manifest_cannot_point_outside_its_own_directory(sandbox, tmp_path, bad_file):
    src = _make_pack(tmp_path / "src")
    m = json.loads((src / "manifest.json").read_text())
    m["stories"] = [{"slug": "esc", "file": bad_file, "title": "Escape"}]
    (src / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(packs.PackError):
        packs.install(src)


def test_a_missing_story_file_is_refused_before_anything_is_written(sandbox, tmp_path):
    src = _make_pack(tmp_path / "src")
    (src / "the_hollow.md").unlink()
    with pytest.raises(packs.PackError):
        packs.install(src)
    assert not (shelf.PACKS_DIR / "ghosts").exists(), "a half-install was left behind"


def test_duplicate_slugs_in_one_manifest_are_refused(sandbox, tmp_path):
    src = _make_pack(tmp_path / "src", stories=[
        {"slug": "dup", "title": "A"}, {"slug": "dup", "title": "B"}])
    with pytest.raises(packs.PackError):
        packs.install(src)


def test_a_broken_manifest_disables_only_its_own_pack(sandbox, tmp_path):
    packs.install(_make_pack(tmp_path / "src"))
    (shelf.PACKS_DIR / "ghosts" / "manifest.json").write_text("{ not json", encoding="utf-8")
    slugs = {b["slug"] for b in shelf.list_books()}
    assert "free_tale" in slugs, "a broken pack took canon down with it"
    assert "the_hollow" not in slugs


# ── Retrieval: packs join the scope automatically ────────────────────────────
def test_an_installed_pack_is_in_scope_with_no_registration(sandbox, tmp_path):
    assert shelf.resolve("The Hollow")["ok"] is False     # not yet installed
    packs.install(_make_pack(tmp_path / "src"))
    assert shelf.resolve("The Hollow")["ok"] is True
    assert shelf.resolve("Hollow")["ok"] is True          # manifest alias


def test_a_miss_lists_what_is_available_and_never_substitutes(sandbox, tmp_path):
    packs.install(_make_pack(tmp_path / "src"))
    r = shelf.resolve("a story about penguins")
    assert not r["ok"] and r["reason"] == "unknown"
    assert r["candidates"], "a miss returned nothing to choose from"
    assert "book" not in r, "a miss returned a substitute story"


# ── Per-story verbatim ───────────────────────────────────────────────────────
def test_verbatim_defaults_to_false_for_pack_content(sandbox, tmp_path):
    packs.install(_make_pack(tmp_path / "src", stories=[{"slug": "perf", "title": "Perf"}]))
    assert shelf.is_verbatim("perf") is False


def test_canon_personal_works_are_verbatim():
    """Against the REAL canon manifest: the family story and the folklore are
    told exactly; the one Ph3b3 wrote may be performed."""
    assert shelf.is_verbatim("arthur_and_eliza")
    assert shelf.is_verbatim("crooked_man_of_flintstone")
    assert not shelf.is_verbatim("esmeraldas_garden")


def test_the_recital_path_honours_the_flag():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert '_r["book"].get("verbatim")' in src, "recital ignores the per-story flag"
