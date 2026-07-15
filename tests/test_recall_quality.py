"""Tier 2 — Mnemosyne recall-QUALITY harness.

Smoke tests prove recall *runs*; this proves it's *accurate*. A labeled corpus
(~26 memories across topics/devices) is queried with known-relevant topics, and
we measure how well the right memories rank:

  - MRR            — mean reciprocal rank of the first relevant hit
  - precision@3    — fraction of the top-3 that are on-topic
  - separation     — relevant top score vs the best off-topic score
  - negative guard — an out-of-domain query must NOT return confident hits

Thresholds are lenient baselines for all-MiniLM-L6-v2; actual numbers are printed
so a regression (or a reason to try nomic-embed-text) is visible, not mysterious.

Run for the full report:  .venv/bin/python -m pytest tests/test_recall_quality.py -s
"""
import sys
import time
from pathlib import Path

# (topic, device, kind, text)
CORPUS = [
    ("drink",       "iris", "fact",         "The captain takes his coffee black, no sugar, first thing every morning."),
    ("drink",       "nyx",  "fact",         "He refills his black coffee about four times through the day."),
    ("food",        "iris", "fact",         "The captain's favorite dinner is a spicy Thai green curry."),
    ("food",        "nyx",  "observation",  "There is dark chocolate in the desk drawer for snacking."),
    ("story_state", "dio",  "state",        "Story state: chapter three — Lyra has just found the broken compass."),
    ("story_state", "dio",  "state",        "Current story progress: the party is entering the constellation's lair."),
    ("story_lore",  "dio",  "conversation", "In the tale, the villain is a jealous constellation who stole the north star."),
    ("story_lore",  "iris", "conversation", "Lyra is the young heroine searching the sky for the lost star."),
    ("story_lore",  "dio",  "conversation", "The broken compass is the magical artifact that points toward lost things."),
    ("festival",    "iris", "conversation", "The Nyx star festival is scheduled for this coming Friday night."),
    ("festival",    "nyx",  "fact",         "The festival will be held up at the hilltop observatory after sunset."),
    ("render",      "nyx",  "observation",  "Morpheus just finished rendering the moon-dish concept art on the GPU."),
    ("render",      "nyx",  "observation",  "A Wan text-to-video render is currently running on the RTX 4060 Ti."),
    ("render",      "nyx",  "fact",         "During image renders Ollama is evicted from the card to free VRAM."),
    ("people",      "nyx",  "fact",         "Astro is the captain and creator of the Ph3b3 constellation."),
    ("people",      "nyx",  "fact",         "Iris is the wearable combadge; Dio is the Stack-Chan desktop robot."),
    ("hardware",    "nyx",  "fact",         "The RTX 4060 Ti graphics card has sixteen gigabytes of VRAM."),
    ("hardware",    "nyx",  "fact",         "Nyx is powered by a Ryzen 9 7950X processor."),
    ("hardware",    "nyx",  "fact",         "Whisper handles speech-to-text on CUDA."),
    ("misc",        "nyx",  "fact",         "Piper synthesizes spoken replies in the Alba voice."),
    ("misc",        "nyx",  "fact",         "Spotify playback can be controlled by voice command."),
    ("misc",        "nyx",  "fact",         "The weather module reports the local daily forecast."),
    ("misc",        "nyx",  "fact",         "D&D lookups cover spells, monsters, and rules."),
    ("misc",        "nyx",  "fact",         "The karaoke library holds WAV tracks with synced LRC lyrics."),
    ("misc",        "nyx",  "fact",         "The network scanner maps LAN hosts by IP and MAC address."),
    ("misc",        "nyx",  "observation",  "Bluetooth scanning lists nearby discoverable devices."),
]

# (query, relevant_topics, is_negative)
QUERIES = [
    ("what does the captain like to drink?",              {"drink"},       False),
    ("his favourite hot beverage that he sips all day",   {"drink"},       False),  # paraphrase, no "coffee"
    ("where are we in the story right now?",              {"story_state"}, False),
    ("who is the antagonist of the tale?",                {"story_lore"},  False),
    ("when and where is the star festival happening?",    {"festival"},    False),
    ("is the graphics card busy with a render?",          {"render"},      False),
    ("how do I change a flat car tire?",                  set(),           True),   # out-of-domain
]

# Lenient baselines for MiniLM on short texts. Tighten as the corpus grows.
MIN_MRR      = 0.75
MIN_P_AT_3   = 0.45
NEG_MAX_SCORE = 0.40


def _seed(spine):
    for topic, device, kind, text in CORPUS:
        spine.remember(text, source_device=device, session_id=topic, kind=kind,
                       metadata={"topic": topic})


def _evaluate(spine, k=5):
    rows, mrr_sum, p3_sum, n_ranked = [], 0.0, 0.0, 0
    neg_ok = True
    for query, relevant, is_neg in QUERIES:
        hits = spine.recall(query, top_k=k)
        topics = [h["metadata"].get("topic") for h in hits]
        scores = [h["score"] for h in hits]
        if is_neg:
            top = max(scores) if scores else 0.0
            neg_ok = neg_ok and top < NEG_MAX_SCORE
            rows.append((query, "(negative)", f"max={top:.3f}",
                         "PASS" if top < NEG_MAX_SCORE else "FAIL"))
            continue
        rr = next((1.0 / i for i, t in enumerate(topics, 1) if t in relevant), 0.0)
        p3 = sum(1 for t in topics[:3] if t in relevant) / 3.0
        rel_score = next((s for s, t in zip(scores, topics) if t in relevant), 0.0)
        off_score = next((s for s, t in zip(scores, topics) if t not in relevant), 0.0)
        mrr_sum += rr; p3_sum += p3; n_ranked += 1
        rows.append((query, hits[0]["text"][:44] if hits else "-",
                     f"RR={rr:.2f} P@3={p3:.2f} sep={rel_score - off_score:+.3f}",
                     "ok" if rr >= 0.5 else "WEAK"))
    return rows, mrr_sum / n_ranked, p3_sum / n_ranked, neg_ok


def _report(spine):
    _seed(spine)
    # wait for every embedding to land
    deadline = time.time() + 30
    while time.time() < deadline:
        with spine._lock:
            if spine._db.execute("SELECT count(*) FROM vec_memories").fetchone()[0] >= len(CORPUS):
                break
        time.sleep(0.05)
    rows, mrr, p3, neg_ok = _evaluate(spine)
    print(f"\n  Mnemosyne recall quality — {len(CORPUS)} memories, {len(QUERIES)} queries")
    print("  " + "-" * 72)
    for q, top, metric, verdict in rows:
        print(f"  [{verdict:>4}] {q}")
        print(f"         top: {top}")
        print(f"         {metric}")
    print("  " + "-" * 72)
    print(f"  MRR={mrr:.3f} (>= {MIN_MRR})   mean P@3={p3:.3f} (>= {MIN_P_AT_3})   "
          f"negative-guard={'PASS' if neg_ok else 'FAIL'}")
    return mrr, p3, neg_ok


def test_recall_quality_baseline(spine):
    mrr, p3, neg_ok = _report(spine)
    assert mrr >= MIN_MRR, f"MRR {mrr:.3f} below baseline {MIN_MRR}"
    assert p3 >= MIN_P_AT_3, f"mean P@3 {p3:.3f} below baseline {MIN_P_AT_3}"
    assert neg_ok, "an out-of-domain query returned an over-confident hit"


if __name__ == "__main__":  # standalone: full readable report
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
    from memory_spine import MemorySpine
    s = MemorySpine(db_path=Path(tempfile.mkdtemp()) / "quality.db")
    s._model_ready.wait(30)
    mrr, p3, neg_ok = _report(s)
    s.close()
    raise SystemExit(0 if (mrr >= MIN_MRR and p3 >= MIN_P_AT_3 and neg_ok) else 1)
