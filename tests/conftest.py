"""Shared fixtures for the Mnemosyne tests.

Both suites use the REAL all-MiniLM-L6-v2 model (recall quality is the whole
point of the Tier-2 harness), but load it ONCE per session and hand every
MemorySpine the same instance, so each test's store is a fresh isolated temp DB
that constructs instantly. Nothing here touches ~/ph3b3_data/mnemosyne.db.

Run:  .venv/bin/python -m pytest tests/test_memory_spine.py tests/test_recall_quality.py -v
"""
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

import memory_spine  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _shared_model():
    """Load MiniLM once; patch MemorySpine's loader to return the cached model."""
    model = SentenceTransformer(memory_spine.MODEL_NAME, device="cpu")
    orig = memory_spine.SentenceTransformer
    memory_spine.SentenceTransformer = lambda *a, **k: model
    yield model
    memory_spine.SentenceTransformer = orig


@pytest.fixture
def spine(tmp_path):
    """A fresh, isolated MemorySpine on a throwaway DB, model ready."""
    s = memory_spine.MemorySpine(db_path=tmp_path / "test.db")
    assert s._model_ready.wait(30), "embed model never became ready"
    yield s
    s.close()


@pytest.fixture
def wait_vec():
    """Return a helper that blocks until `n` vector rows have landed — the embed
    is fire-and-forget, so recall-dependent assertions must wait for it."""
    def _wait(spine, n, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with spine._lock:
                c = spine._db.execute("SELECT count(*) FROM vec_memories").fetchone()[0]
            if c >= n:
                return True
            time.sleep(0.05)
        return False
    return _wait
