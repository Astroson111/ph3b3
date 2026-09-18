"""
Thoth's command line.

    .venv/bin/python -m thoth list                    what the library holds
    .venv/bin/python -m thoth ingest --all            fetch + parse + store
    .venv/bin/python -m thoth index                   build the vector index
    .venv/bin/python -m thoth search "the flood"      retrieval only, no model
    .venv/bin/python -m thoth ask "what does …"       the full lane, with the floor
    .venv/bin/python -m thoth debate on|off|status    Rung 3's mode (default OFF)
    .venv/bin/python -m thoth read "John 3"           read aloud on the Nyx speaker
    .venv/bin/python -m thoth resume                  pick the reading back up
    .venv/bin/python -m thoth position                where the last reading got to

`ask --session X` keeps a debate stance across turns, so she can be held to a
position she took earlier in the same conversation.

`search` exists so retrieval can be judged on its own. When an answer is wrong
it is usually retrieval that was wrong, and a lane that only ever speaks through
a model makes that impossible to see.

`ask` calls the local model with NO tools key — the Kadmos injection firewall.
Retrieved scripture is untrusted input full of second-person imperatives, and a
tools-enabled completion would give "go and do likewise" something to reach.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

from . import debate as debate_mod
from . import lane
from . import reader as reader_mod
from .corpus import Corpus, load_manifest
from .index import Index
from .ingest import main as ingest_main

OLLAMA = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.getenv("PH3B3_LIGHT_MODEL", "ph3b3-chat:latest")


def _generate(prompt: str) -> str:
    """One tools-disabled completion. There is deliberately no `tools` key."""
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.3}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r).get("response", "")


def _ref(h) -> str:
    return f"{h.book} {h.section}:{h.unit}" if h.book else f"{h.section}:{h.unit}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="thoth", description="Thoth sacred-text library")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="corpus state")
    p_ix = sub.add_parser("index", help="build the vector index")
    p_ix.add_argument("--work", action="append", default=[])
    p_ix.add_argument("--prune", action="store_true",
                      help="drop embeddings for works no longer eligible")
    p_se = sub.add_parser("search", help="retrieval only")
    p_se.add_argument("query")
    p_se.add_argument("-k", type=int, default=8)
    p_as = sub.add_parser("ask", help="the full lane, floor included")
    p_as.add_argument("query")
    p_as.add_argument("-k", type=int, default=8)
    p_as.add_argument("--session", default="", help="keep a debate stance across turns")
    p_as.add_argument("--debate", dest="debate", action="store_true", default=None,
                      help="force debate mode on for this turn")
    p_db = sub.add_parser("debate", help="the debate-mode switch")
    p_db.add_argument("state", choices=["on", "off", "status"], nargs="?", default="status")
    p_rd = sub.add_parser("read", help="read aloud on the Nyx speaker")
    p_rd.add_argument("query")
    p_rd.add_argument("--chapters", type=int, default=None,
                      help="stop and offer to go on after N chapters, this "
                           "reading only (0 = never stop)")
    p_cf = sub.add_parser("reader-continue",
                          help="persist the default chapter limit (0 = never ask)")
    p_cf.add_argument("n", type=int, nargs="?", default=None)
    p_rs = sub.add_parser("resume", help="resume the last reading from its marker")
    p_rs.add_argument("--chapters", type=int, default=None,
                      help="stop after N chapters, this reading only")
    sub.add_parser("position", help="show the saved reading marker")
    args, rest = ap.parse_known_args(argv)

    if args.cmd == "list":
        return ingest_main(["--list"])

    if args.cmd == "debate":
        if args.state in ("on", "off"):
            debate_mod.set_enabled(args.state == "on")
        print(f"debate mode: {'ON' if debate_mod.enabled() else 'OFF'}")
        return 0

    corpus = Corpus()
    works, failures = load_manifest()
    for ident, why in failures:
        print(f"  MANIFEST REJECTED  {ident}: {why}", file=sys.stderr)
    corpus.sync_metadata(works, allow_drop=True)   # the CLI loads the complete manifest
    index = Index(corpus)

    if args.cmd == "index":
        if args.prune:
            print(f"pruned {index.prune_ineligible()} ineligible embeddings")
        before = index.stats()
        print(f"eligible {before['eligible']:,}  indexed {before['indexed']:,}  "
              f"missing {before['missing']:,}")

        def show(done, total):
            if done % 12800 == 0 or done == total:
                print(f"  {done:,}/{total:,}", flush=True)
        added = index.build(work_ids=args.work or None, progress=show)
        print(f"added {added:,} — now {index.stats()}")
        return 0

    if args.cmd == "search":
        hits = index.search(args.query, k=args.k)
        if not hits:
            print("nothing retrieved")
            return 1
        for h in hits:
            print(f"  {h.score:.3f}  {h.work_id:16s} {_ref(h):24s} {h.text[:70]}")
        return 0

    if args.cmd == "reader-continue":
        if args.n is not None:
            reader_mod.set_continue_after_chapters(args.n)
        n = reader_mod.continue_after_chapters()
        print(f"continue prompt after {n} chapters" if n else
              "no continue prompt — readings run until stopped")
        return 0

    if args.cmd in ("read", "resume", "position"):
        from tts_module import TTSModule
        speaker = TTSModule()
        if args.cmd == "position":
            pos = reader_mod.load_position(corpus)
            print(f"position: {pos.spoken()} in {pos.work_id}" if pos else "no saved position")
            return 0 if pos else 1

        if args.cmd == "resume":
            pos = reader_mod.load_position(corpus)
            if not pos:
                print("nothing to resume — no saved position")
                return 1
            title = corpus._db.execute("SELECT title FROM works WHERE id=?",
                                       (pos.work_id,)).fetchone()
            ref = reader_mod.Reference(work_id=pos.work_id,
                                       work_title=title[0] if title else pos.work_id,
                                       book=pos.book, section=pos.section)
            from_unit = pos.unit
        else:
            res = reader_mod.resolve(args.query, corpus, speaker)
            if res.question:
                print(res.question)
                return 2
            if not res.ok:
                print(res.refusal)
                return 1
            ref, from_unit = res.reference, 0
            if res.note:
                print(f"(reading the {res.note})")

        if not speaker.available():
            print("no voice model — nothing to read with")
            return 1

        def on_event(kind, detail):
            if kind in ("start", "stop", "error", "unspoken"):
                print(f"[{kind}] {detail}", flush=True)
        reading = reader_mod.Reading(corpus, speaker, on_event)
        print(f"reading {ref.spoken()} — {ref.work_title}   (ctrl-c to stop)")
        try:
            reading.start(ref, from_unit=from_unit, block=True,
                          continue_after=getattr(args, "chapters", None))
        except KeyboardInterrupt:
            pos = reading.stop()
            print(f"\nstopped at {pos.spoken() if pos else 'the start'}")
        return 0

    if args.cmd == "ask":
        answer = lane.ask(args.query, _generate, corpus, index, k=args.k,
                          session_id=args.session, debating=args.debate)
        print(f"\n{answer.text}\n")
        if answer.citations:
            print("Cited:")
            for r in answer.references():
                print(f"  {r}")
        if answer.stance:
            print(f"Position held: {answer.stance.position}")
        if answer.violations:
            print("Floor:", ", ".join(sorted({v.kind for v in answer.violations})))
        print(f"\n[retrieved {answer.retrieved}"
              f"{', debating' if answer.debate else ''}]")
        return 0 if answer.ok else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
