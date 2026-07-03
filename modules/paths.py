"""
paths.py — single source of truth for filesystem locations.

Everything derives from two roots so the project runs for anyone who clones it,
with no usernames baked into source:

  PH3B3_HOME  — the repo root. Defaults to the directory this file lives in
                (<repo>/modules/paths.py -> <repo>), so it is correct wherever
                the repo is cloned. Override with the PH3B3_HOME env var.
  PH3B3_DATA  — runtime data root (recipes.db, memory.json, voices, photos, …).
                Defaults to ~/ph3b3_data. Override with the PH3B3_DATA env var.

Most modules already build their paths from ~/ph3b3_data directly; new code
should import PH3B3_DATA from here instead.
"""
import os
from pathlib import Path

# Repo root: this file is at <repo>/modules/paths.py, so parents[1] is <repo>.
PH3B3_HOME = Path(os.getenv("PH3B3_HOME", str(Path(__file__).resolve().parents[1])))

# Runtime data root. Kept separate from the repo so data survives a re-clone.
PH3B3_DATA = Path(os.getenv("PH3B3_DATA", str(Path.home() / "ph3b3_data")))

# Morpheus keeps its own generated images + index alongside the repo checkout
# (historically <repo>/../ph3b3_v2_data). Deriving from PH3B3_HOME.parent keeps
# that exact location while removing the hardcoded home path.
MORPHEUS_DATA = Path(os.getenv("MORPHEUS_DATA", str(PH3B3_HOME.parent / "ph3b3_v2_data")))
