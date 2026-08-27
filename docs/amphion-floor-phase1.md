# Amphion floor — Phase 1 (2026-08-27)

Phase 0 findings: `docs/amphion-floor-phase0.md`. This is what changed.

The lesson first, because it shaped every decision below: **the floor failed both
ways at once.** It over-refused on ordinary vocabulary while under-catching the
cases that matter, and the harness that should have shown the second half was
returning green on zero collected tests. Those are not two bugs. Both come from
asking an image floor a music question, and the silent harness is why only the
first half was ever noticed.

## 1. Layer B is wired to Amphion (ruling 1)

`_amphion_floor_gate` now mirrors `_morpheus_floor_gate` exactly:

    halt → Layer A (every field) → Layer B (composed) → interlock → profile

- `semantic_minor_check` and `real_person_compromised` run on the composed style
  tags + mood tags + lyrics, pre-lock. Both fail-closed: UNCERTAIN refuses, an
  empty verdict refuses, a timeout refuses, an unreachable judge refuses.
- `generation_halted()` is checked. An output-check hit that could not stop a
  song was a decoration.
- `explain_floor` logging: field, category, rule, matched term.
- **No waivers.** The artistic-reproduction and atrocity-documentary exceptions
  are deliberately absent — neither has a reading that applies to a song.
- The gate moved to `asyncio.to_thread` on all three HTTP paths. It was called
  inline; Layer B is two model calls and would have blocked the event loop.
  (Morpheus was moved in `389f9cb`; Amphion was missed.)
- The **chat tool** now calls the same gate instead of its own weaker pair, so
  the halt flag and both judges cover it too. It had been possible to get a
  refused song by asking Phoebe for it.

**Layer B asks the text question, not the image one.** This is the one place I
went past the literal ruling, and the reason is in the ruling itself: Amphion
renders nothing. The image prompt asks *"would the resulting IMAGE depict a
figure under 18"*, which applied to a lyric has no referent. A judge asked an
incoherent question does not fail safe, it answers erratically — and under a
fail-closed caller, erratic means refusing at random. So the text surface has its
own two prompts, fenced as untrusted input (lyrics are the one Layer B input that
is a document long enough to hide an instruction in). Strictness is unchanged;
only the question is.

## 2. The harness (ruling 2)

The probe files were never collected. Not "collected and skipped" — **not
matched**: they are `floor_*_probe.py`, pytest's default `python_files` is
`test_*.py`, and the repo had no pytest config at all. Commit `ecc16b3` claimed
to have fixed this and did not, and nothing caught it, because the symptom is a
green run.

- `pytest.ini` added: `python_files = test_*.py *_probe.py`
- All six probes converted to real parametrized tests; the report body moved to
  `def main()` so `python tests/<probe>.py` still works.
- `tests/test_floor_manifest.py`: every floor suite's case count is written down
  and a shortfall **fails**. It also shells out to a bare `pytest tests/` and
  reads back what was collected — because every other check in that file passes
  whether or not pytest can find the suites, which is the exact blind spot that
  let this ship.
- Layer B unavailable now **fails** the floor suites rather than skipping them
  (`PH3B3_FLOOR_ALLOW_NO_JUDGE=1` to downgrade deliberately). A fail-closed judge
  that is down scores a perfect refusal rate while the allow-set collapses; that
  is a meaningless pass.

**A landmine this exposed:** every probe called `logging.disable(logging.CRITICAL)`
at import — a global kill switch, harmless while nobody imported them, and it
silently broke four `test_triage_gate` assertions the moment they were collected.
Now scoped to `ph3b3.morpheus`.

Suite: **1031 → 1416 passing**, 2 pre-existing skips, 0 failures.

## 3. Refusal legibility (ruling 3)

`morpheus.FLOOR_CATEGORIES` is the single source of truth; nine rules map to six
categories.

| rule | shown as |
|---|---|
| `minor-sexual`, `child-depiction` | category 1: child sexualization |
| `real-person-compromising` | category 2: real-person likeness |
| `nonconsensual` | category 3: non-consent |
| `atrocity` | category 4: atrocity |
| `dehumanization`, `hate-glorification` | category 5: hate / dehumanization |
| `terror-instructional` | category 6: terror instruction |

- Category only. Never the rule, the matched span, or a line number — on **any**
  category, not just 1. A test asserts a category 1 refusal is exactly
  `"Refused — category 1: child sexualization."` and contains no token echo, no
  rephrase hint, and that the GPU lock was never acquired.
- One shape everywhere: `Refused — category N: name.` /
  `Refused — content profile: strict.` / `Refused — scope: no voice cloning.`
  The chat tool returns the identical string (it had a third wording).
- `panel.html` displays `d.detail`. It was ignoring it and printing its own
  constant, so a category computed on Nyx died one line before a human saw it.
- The two Amphion-authored checks are labelled **scope**, not category — they are
  July 25 product rulings, and filing them under a harm category is the same
  misattribution in the other direction.
- Morpheus's `_FLOOR_REFUSAL` constant is gone. Image floor **behaviour** is
  byte-for-byte unchanged; only what it says changed.

## 4. The right definition for the surface (ruling 4)

`floor_check(text, surface="text")`. One implementation, a parameter — not a
parallel floor.

- Category 1 on the text path: age term **AND** sexual signal. Layer B carries
  the rest, fail-closed.
- `held down` and `coerced into` need a second signal on the text path. Every
  other non-consent entry is standalone, because every other entry is a phrase
  that means only the one thing.
- `orphan` and bare `student` are dropped from the text path entirely. They are
  subject heuristics, and on a surface that depicts nobody they carry no signal.
- **The image path is untouched.** A test asserts the 2026-07-31 weld still fires
  on a bare minor subject, and that the text surface deliberately does not.

`baby`, `little one`, `minor key` and `D minor` now pass. A song that sexualizes
a child is refused, category stated.

## 5. Regression + parity (ruling 5)

- `tests/amphion_regression_lyrics.py` — all three versions plus the six
  standalone false positives, asserted through the real endpoint against the
  **real** judge. A regression that stubs the thing under test proves nothing.
- **What refused all three: `D minor`, in the STYLE TAG, not the lyrics.**
  `minor` → `minor-term` → `child-depiction`. A key signature read as a minor.
- Emotion table: every emotion's `amphion_terms` composes and passes the text
  floor (`minor key` is emotion vocabulary and was a category 1 term — Ph3b3's own
  registry could trip Ph3b3's own floor). Adversarial registry entry still refuses.

### On the parity target — it is the wrong measure, and here is why

Parity with Morpheus on the existing 151 is **not achievable and not desirable**,
and I want that on the record rather than buried in a number.

The six standing probes are an **image** corpus. Their own doctrine says so: the
image floor is subject-gated, so neutral descriptions of children are sufficient
and nothing explicit needs writing. Correct there — and it makes them unable to
measure a context-gated surface. Run against the Amphion gate they score 66/147,
and **all 81 passes are neutral child subjects**: "a third grader in a park", "a
lullaby", "a kid in a park" in nineteen languages. Under ruling 4 those are
songs, not category 1. Refusing them would be the `baby` bug again.

So the measure is a purpose-built text corpus, `tests/floor_text_surface_probe.py`
(gitignored with its siblings):

```
sexualized-minor cases (19)  : 19/19 refused   — Layer A 8, LAYER B 11
ordinary songs (17)          : 17/17 allowed   — lullabies, grief, growing up,
                                                 and the six false positives
                               0 leaks, 0 over-refusals
```

Layer B carries 11 of 19 — precisely the half that was missing. On the corpus
that *can* be compared like-for-like, the identity probe, the Amphion path now
scores **26/26 refuse** (was 22/26 — the mononym leaks are closed) and **18/20
allow**, matching the image path's two-signal property.

Every REFUSE case is a clinical, non-graphic description of a request. Nothing in
that file is lyrics and nothing describes an act.

## Open, not done

1. **`real_person_compromised` stayed fail-closed** — you withdrew the
   uncertain-is-a-pass ruling as moot, and it is: those four mononym leaks were
   the bug. Noting it because tuning that judge's prompt is what fixed two
   over-refusals, so it is the piece most likely to drift.
2. **`_OUTPUT_REFUSAL`** (`morpheus.py`) still reads "Refused by the child-safety
   floor." That one is accurate — the output judge is age-only — so I left it.
3. **GPU contention**: the floor suites now make ~280 judge calls. Run them while
   ComfyUI holds VRAM and Ollama can OOM mid-run; it surfaced as four unrelated
   triage failures. Not introduced by this change, but now much easier to hit.
4. **Two refused Aug 27 submissions were unrecoverable** — no sidecar for a
   refused job, refusal text never logged, stderr-only logging. The fixture file
   is how the regression set survives that, and it is the only reason it does.
