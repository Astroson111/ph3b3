#!/usr/bin/env python3
"""One-time ingest of the RecipeNLG dataset into SQLite + FTS5.

Usage:
    python scripts/ingest_recipes.py \
        --csv /path/to/RecipeNLG_dataset.csv \
        --db  /path/to/recipes.db \
        [--gathered-only]

--gathered-only filters to rows where source == 'Gathered' (~1.6M rows, cleaner
fractions — avoids the "12" for "1/2" OCR noise in the scraped subset).

Expected CSV columns (with header row):
    title, ingredients, directions, link, source, NER

'ingredients', 'directions', and 'NER' are stringified Python lists —
parsed with ast.literal_eval, NOT json.loads.
"""

import argparse
import ast
import csv
import json
import os
import sqlite3
import sys
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id          INTEGER PRIMARY KEY,
    title       TEXT,
    ingredients TEXT,
    directions  TEXT,
    ner         TEXT,
    link        TEXT,
    source      TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
    title, ner,
    content='recipes',
    content_rowid='id'
);
"""

BATCH = 10_000


def _safe_list(raw: str) -> list:
    """Parse a stringified Python list; return [] on failure."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        val = ast.literal_eval(raw)
        return val if isinstance(val, list) else []
    except Exception:
        return []


def ingest(csv_path: str, db_path: str, gathered_only: bool) -> None:
    print(f"Opening DB: {db_path}")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.executescript(SCHEMA)

    # Fast load settings — restored after commit
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=OFF")
    cur.execute("PRAGMA cache_size=-65536")   # 64 MB page cache
    cur.execute("PRAGMA temp_store=MEMORY")
    con.commit()

    recipe_buf = []
    fts_buf    = []
    total      = 0
    skipped    = 0
    t0         = time.monotonic()

    print(f"Streaming: {csv_path}")
    if gathered_only:
        print("Filter: source == 'Gathered' only")

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)       # skip header row
        if header is None:
            print("ERROR: CSV is empty.")
            sys.exit(1)

        # Detect column indices defensively
        try:
            h = [c.lower().strip() for c in header]
            i_title = h.index("title")
            i_ingr  = h.index("ingredients")
            i_dir   = h.index("directions")
            i_link  = h.index("link")
            i_src   = h.index("source")
            i_ner   = h.index("ner")
        except ValueError:
            # Fall back to positional (RecipeNLG default order)
            i_title, i_ingr, i_dir, i_link, i_src, i_ner = 0, 1, 2, 3, 4, 5

        row_id = 0
        for raw_row in reader:
            if len(raw_row) <= max(i_title, i_ingr, i_dir, i_link, i_src, i_ner):
                skipped += 1
                continue

            source = raw_row[i_src].strip()
            if gathered_only and source != "Gathered":
                skipped += 1
                continue

            title = raw_row[i_title].strip()
            ingr  = json.dumps(_safe_list(raw_row[i_ingr]))
            dirs  = json.dumps(_safe_list(raw_row[i_dir]))
            ner   = json.dumps(_safe_list(raw_row[i_ner]))
            link  = raw_row[i_link].strip()
            ner_terms = " ".join(_safe_list(raw_row[i_ner]))

            row_id += 1
            recipe_buf.append((row_id, title, ingr, dirs, ner, link, source))
            fts_buf.append((row_id, title, ner_terms))

            if len(recipe_buf) >= BATCH:
                cur.executemany(
                    "INSERT INTO recipes(id,title,ingredients,directions,ner,link,source) VALUES(?,?,?,?,?,?,?)",
                    recipe_buf,
                )
                cur.executemany(
                    "INSERT INTO recipes_fts(rowid,title,ner) VALUES(?,?,?)",
                    fts_buf,
                )
                con.commit()
                recipe_buf.clear()
                fts_buf.clear()

            total += 1
            if total % 100_000 == 0:
                elapsed = time.monotonic() - t0
                print(f"  {total:,} rows ingested ({elapsed:.0f}s)...")

    # Flush remainder
    if recipe_buf:
        cur.executemany(
            "INSERT INTO recipes(id,title,ingredients,directions,ner,link,source) VALUES(?,?,?,?,?,?,?)",
            recipe_buf,
        )
        cur.executemany(
            "INSERT INTO recipes_fts(rowid,title,ner) VALUES(?,?,?)",
            fts_buf,
        )
        con.commit()

    # Restore safe durability and optimise
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA optimize")
    con.commit()
    con.close()

    elapsed = time.monotonic() - t0
    size_mb = os.path.getsize(db_path) / (1024 ** 2)
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Rows ingested : {total:,}")
    print(f"  Rows skipped  : {skipped:,}")
    print(f"  DB size       : {size_mb:.0f} MB  ({db_path})")


def main():
    parser = argparse.ArgumentParser(description="Ingest RecipeNLG CSV into SQLite+FTS5")
    parser.add_argument("--csv", required=True, help="Path to RecipeNLG_dataset.csv")
    parser.add_argument("--db",  required=True, help="Output SQLite DB path")
    parser.add_argument("--gathered-only", action="store_true",
                        help="Only ingest rows where source == 'Gathered'")
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"ERROR: CSV not found: {args.csv}")
        sys.exit(1)

    if os.path.isfile(args.db):
        ans = input(f"DB already exists at {args.db}. Overwrite? [y/N] ")
        if ans.strip().lower() != "y":
            print("Aborted.")
            sys.exit(0)
        os.remove(args.db)

    ingest(args.csv, args.db, args.gathered_only)


if __name__ == "__main__":
    main()
