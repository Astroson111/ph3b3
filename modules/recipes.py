# RecipeNLG dataset — non-commercial / research-educational licence only.
# This module must NEVER be bundled into a Ph3b3 Labs client deliverable.
# Personal/private use on Nyx only.

import json
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("ph3b3.recipes")

_MAX_PANTRY_CANDIDATES = 2000
_MAX_QUERY_TOKENS = 50   # cap OR-joined FTS query length for pantry mode


class RecipeStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._available = False

        if not Path(db_path).exists():
            log.warning(
                f"Recipe DB not found at {db_path!r} — run scripts/ingest_recipes.py first. "
                "find_recipe will return 'not available' until the DB is present."
            )
            return

        try:
            uri = f"file:{db_path}?mode=ro"
            self._con = sqlite3.connect(
                uri, uri=True, check_same_thread=False
            )
            self._con.row_factory = sqlite3.Row
            # Smoke-test
            self._con.execute("SELECT count(*) FROM recipes LIMIT 1").fetchone()
            row_count = self._con.execute("SELECT count(*) FROM recipes").fetchone()[0]
            self._available = True
            log.info(f"RecipeStore ready — {row_count:,} recipes  ({db_path})")
        except Exception as e:
            log.error(f"RecipeStore failed to open DB: {e}")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _sanitize(self, tokens: list[str], operator: str = "AND") -> str:
        """Build a safe FTS5 query from a list of ingredient strings.

        Each token is wrapped in double-quotes (FTS5 phrase match), with any
        internal double-quotes doubled per the FTS5 spec.  Multi-word tokens
        like 'brown sugar' are kept intact as a single quoted phrase.
        Tokens are joined with AND (strict) or OR (pantry).
        """
        phrases = []
        for t in tokens[:_MAX_QUERY_TOKENS]:
            cleaned = t.strip()
            if not cleaned:
                continue
            escaped = cleaned.replace('"', '""')
            phrases.append(f'"{escaped}"')
        if not phrases:
            return ""
        return f" {operator} ".join(phrases)

    def _parse_row(self, row: sqlite3.Row) -> dict:
        return {
            "title":       row["title"],
            "ingredients": json.loads(row["ingredients"] or "[]"),
            "directions":  json.loads(row["directions"]  or "[]"),
            "ner":         json.loads(row["ner"]         or "[]"),
            "link":        row["link"]   or "",
            "source":      row["source"] or "",
        }

    def _unavailable(self) -> list:
        return []

    # ── Public API ────────────────────────────────────────────────────────────

    def search_text(self, query: str, limit: int = 10) -> list[dict]:
        """Free-text FTS5 search over title and NER ingredient names."""
        if not self._available:
            return self._unavailable()
        query = query.strip()
        if not query:
            return []
        try:
            cur = self._con.execute(
                """
                SELECT r.id, r.title, r.ingredients, r.directions, r.ner, r.link, r.source
                FROM recipes_fts f
                INNER JOIN recipes r ON r.id = f.rowid
                WHERE f MATCH ?
                ORDER BY f.rank
                LIMIT ?
                """,
                (query, limit),
            )
            return [self._parse_row(row) for row in cur.fetchall()]
        except sqlite3.OperationalError as e:
            log.warning(f"FTS search_text error (query={query!r}): {e}")
            return []

    def search_by_ingredients(
        self,
        have: list[str],
        strict: bool = False,
        limit: int = 10,
    ) -> list[dict]:
        """Ingredient-based search.

        strict=True  — AND join: recipes that use ALL provided ingredients.
        strict=False — pantry mode: OR join to get candidates, then rank in Python
                       by (fewest missing, best coverage).  Each result carries
                       'missing' (list) and 'coverage' (float 0–1).
        """
        if not self._available:
            return self._unavailable()
        if not have:
            return []

        operator  = "AND" if strict else "OR"
        fts_query = self._sanitize(have, operator)
        if not fts_query:
            return []

        sql_limit = limit if strict else _MAX_PANTRY_CANDIDATES

        try:
            cur = self._con.execute(
                """
                SELECT r.id, r.title, r.ingredients, r.directions, r.ner, r.link, r.source
                FROM recipes_fts f
                INNER JOIN recipes r ON r.id = f.rowid
                WHERE f MATCH ?
                ORDER BY f.rank
                LIMIT ?
                """,
                (fts_query, sql_limit),
            )
            candidates = cur.fetchall()
        except sqlite3.OperationalError as e:
            log.warning(f"FTS search_by_ingredients error (query={fts_query!r}): {e}")
            return []

        if strict:
            return [self._parse_row(r) for r in candidates]

        # Pantry ranking: fewest missing first, then best coverage
        have_set = {h.lower() for h in have}
        ranked = []
        for row in candidates:
            parsed     = self._parse_row(row)
            ner        = {n.lower() for n in parsed["ner"]}
            missing    = sorted(ner - have_set)
            coverage   = len(ner & have_set) / max(len(ner), 1)
            ranked.append((len(missing), -coverage, parsed, missing, coverage))

        ranked.sort(key=lambda x: (x[0], x[1]))

        results = []
        for _, _, parsed, missing, coverage in ranked[:limit]:
            parsed["missing"]  = missing
            parsed["coverage"] = round(coverage, 3)
            results.append(parsed)
        return results

    def status(self) -> str:
        if self._available:
            try:
                n = self._con.execute("SELECT count(*) FROM recipes").fetchone()[0]
                return f"RecipeStore ready — {n:,} recipes"
            except Exception:
                pass
        return "RecipeStore unavailable — run scripts/ingest_recipes.py"
