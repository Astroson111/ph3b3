# Amphion floor — Phase 0 findings (2026-08-27)

Findings only. No code changed. Baseline runs recorded at the bottom.

## 0. Premise check: the two refused submissions are not recoverable

`grep -ri "send the machine"` across the whole home directory returns exactly two
files, and both are the brief itself (`.claude/paste-cache/ce06d79726e3df6f.txt`
and this session's transcript). Nothing in `ph3b3_data/chats/`, nothing in
`ph3b3_data/songs/` sidecars, nothing in any prior Claude Code session under
`.claude/projects/`.

That is by design, not by loss:

- A refused job never reaches `amphion.new_job()`, so no sidecar is written.
  Sidecars exist only for jobs that queued (including failures) — refusals are
  upstream of that.
- `_amphion_floor_gate` logs field + category and **never the text** (server.py:5751).
- `agent/server.py:101` is `logging.basicConfig(...)` with **no FileHandler**.
  Ph3b3's log goes to stderr on Nyx and is not persisted anywhere on this box.

So the exact spans cannot be recovered. Everything below is diagnosed against the
real floor path with reconstructed machine/logistics lyric material, which is
enough to name the defect precisely — see §4. **Three versions of the song do not
exist on disk either**, so the regression set the Verify section asks for cannot be
saved until you paste the three lyric sets back in.

## 1. What Amphion's refusal actually returns to the UI

**Plumbing bug, and it is a double drop.** The category is computed and then thrown
away twice.

| Stage | What it has | What it passes on |
|---|---|---|
| `morpheus.floor_check` (morpheus.py:1219) | returns the category string | returns it correctly |
| `_amphion_floor_gate` (server.py:5749-5752) | `cat` in hand, logs it | `HTTPException(403, detail="Content policy: not permitted")` — constant |
| `panel.html:3332` | receives that 403 | ignores `d.detail` entirely; prints its own hardcoded *"That prompt or lyrics can't be generated (content policy)."* |

Two independent drops. Fixing the server alone changes nothing the user sees,
because the 403 branch in panel.html short-circuits before `r.json()` is read.

Three further inconsistencies on the same path:

- `floor_check`'s own docstring says *"The returned string is for internal logging
  only — never expose to callers."* That line is the design intent that has to be
  revised for the ruling to land; it currently contradicts it.
- The **floor** block and the **profile** block raise the *same* string
  (server.py:5752 and :5763), so the UI cannot distinguish a welded floor category
  from a demo-profile denylist hit.
- The **chat-tool** path (server.py:1147) returns a *different* generic string —
  *"I can't make that one — it crosses a hard line I don't move."* Two surfaces,
  two strings, neither carrying a category.

### The Morpheus pattern does not currently do what the ruling assumes

`_FLOOR_REFUSAL = "Refused by the child-safety floor."` (server.py:4651) is a
**constant**, raised for all nine categories — atrocity, terror, hate-glorification,
dehumanisation, nonconsensual and real-person-compromising all report as
*child-safety*. So "match the Morpheus pattern" cannot mean copy Morpheus's current
string; Morpheus needs the same legibility change. Note the July 28 rule is already
honoured in the **logs** on the Morpheus path (`explain_floor` emits category + rule
+ matched term, server.py:4704) — it is only the user-facing string that is generic.

## 2. Checks on Amphion's floor path that are not one of the six welded categories

`/amphion/generate`, `/amphion/variations` and `/amphion/remix/{id}` all run the same
pair — `_amphion_floor_gate` then `_amphion_music_floor`. Full inventory:

**Inside `morpheus.floor_check`, beyond the six + the child-depiction weld:**

| Category returned | Origin |
|---|---|
| `dehumanization` | Morpheus, added by the 33-prompt war-and-hate red-team pass (morpheus.py:~385 comment). Inherited free by Amphion. |
| `hate-glorification` | Same red-team pass. Two-signal: hate subject + glorify, with anti-hate veto. |
| `terror-instructional` | Same red-team pass. Standalone, explicitly not waivable. |
| `atrocity` | Same red-team pass. Standalone, waivable via `atrocity_documentary_applies` — **but Amphion never calls the waiver**, so on the music path atrocity is unconditional. |

Plus two more rules inside category 1 that are neither a term list nor part of the
2026-07-31 weld: `_RE_ORPHAN` (`\borphan(?!age)`, morpheus.py:231) and the bare-student
rule (`\bstudents?\b` unless a university/college/grad qualifier appears anywhere,
morpheus.py:233-237). Both refuse standalone. Both are Morpheus-authored.

**Outside `floor_check`, on the Amphion path:**

| Check | Origin |
|---|---|
| `morpheus.profile_check` + strict denylist | Morpheus profile layer (Part 2), inherited. Not a floor category — `gore`, `guts`, `torture`, `explicit`, `swastika` etc. |
| localhost interlock (permissive → forced strict off-box) | Morpheus, copied into `_amphion_floor_gate` verbatim |
| `amphion.voice_clone_refusal` | **Ad hoc, authored in amphion.py** — named-artist voice cloning. Justified as a floor item by both Amphion briefs. |
| `amphion.copyright_refusal` | **Ad hoc, authored in amphion.py** — LLM lyric identification. Same. |

Nothing is copied from a template. Nothing removed.

**What is on the Morpheus path and MISSING from Amphion** — this is the bigger half
of the story:

- `generation_halted()` — the output-check halt flag. **Amphion ignores it.** A halt
  stops image generation and does not stop song generation.
- `adulthood_negation_signal` — structural, negative-field only. N/A for Amphion (no
  negative field), correctly absent.
- `semantic_minor_check` (Layer B, category 1) — **absent**.
- `real_person_compromised` (Layer B, categories 2/3/4) — **absent**.
- `artistic_exception_applies` / `atrocity_documentary_applies` waivers — absent, so
  Amphion is *stricter* on those two and has no memorial/reproduction carve-out.
- `explain_floor` diagnostic logging — absent. Amphion logs the category but never
  the rule or the matched term, so an Amphion refusal cannot be attributed to a rule
  from the log alone. That is exactly the hole `explain_floor` was written to close
  on the Morpheus side.

## 3. Semantic pass posture

**There is no semantic pass on the Amphion path at all.** `amphion.content_floor`
calls `morpheus.floor_check` and nothing else; `_amphion_floor_gate` likewise. Layer B
is only ever invoked from `_morpheus_floor_gate`. So the question "is it prompted to
fail closed for all categories or only for category 1" has no Amphion answer yet.

On the Morpheus path, where it does run, there are two judges and **both fail closed**:

- `semantic_minor_check` (morpheus.py:1128) — category 1.
  `return not _floor_judge(_LAYER_B_PROMPT, text).startswith("NO")`
  Anything that is not a literal `NO` refuses: `UNCERTAIN` refuses, an empty verdict
  refuses, a timeout refuses, an unreachable model refuses.
  Exact prompt instruction: **"Judge the image, not the words. Answer with exactly
  one word: YES, NO, or UNCERTAIN."** The prompt offers UNCERTAIN; the caller treats
  it as a refusal.
- `real_person_compromised` (morpheus.py:1098) — categories 2/3/4, gated behind a
  cheap lexical pre-exit. Ends
  `return not _floor_judge(_LAYER_B_PERSON_PROMPT, text).startswith("NO")` — also
  fail-closed. Its prompt says **"Reply with one word."** and offers no UNCERTAIN
  token at all, so any hedged answer refuses.

So fail-closed is currently **cat 1 and cats 2/3/4**, not cat 1 only. Categories
5–9 have no semantic pass in either module. The ruling that "fail-closed-on-uncertain
is category 1's posture only" therefore changes `real_person_compromised` as well as
anything new on the Amphion side — worth confirming that is intended, since 2/3/4 is
the defamation/likeness category and its judge exists precisely because
`_person_signal` misses every mononym.

## 4. Lexical prescreen defects — ordinary vocabulary that refuses

Confirmed against the real `floor_check`. **None of the nine terms the brief names
(cut, line, cache, drop, reserve, haul, fuel, tether, mark) fire** — bare or in a
sentence. `"Cut the line and let the cache drop"` and `"Reserve the haul, fuel the
tether, mark the spot"` both pass clean.

The false positives are elsewhere, and they are ordinary **songwriting** vocabulary
rather than machine vocabulary. Measured, standalone, no second signal required:

| Input | Category returned | Rule | Matched |
|---|---|---|---|
| `Baby, send the machine` | `child-depiction` | `minor-term` | `baby` |
| `The kids on the night shift are still awake` | `child-depiction` | `minor-term` | `kids` |
| `She was the youth of the factory floor` | `child-depiction` | `minor-term` | `youth` |
| `a childish little tune` | `child-depiction` | `minor-term` | `childish` |
| `Little one, the belt is turning` | `child-depiction` | `minor-subject-term` | `little one` |
| `Student of the yard, forty years on the line` | `child-depiction` | `student-no-adult-qualifier` | `student` |
| `An orphan bolt rolling under the bench` | `child-depiction` | `orphan-term` | `orphan` |
| `I held down the throttle till the engine caught` | `nonconsensual` | `nonconsensual-term` | `held down` |

Full set of standalone-firing terms that are ordinary English:

- `_FLOOR_MINOR` (all fire alone, word-START match so every suffix too):
  `baby`, `babies`, `kid`, `kids`, `child`, `children`, `childish`, `childlike`,
  `youth`, `youths`, `youngster(s)`, `teen(s)`, `minor`, `minors`, `juvenile`,
  `infant(s)`, `newborn`, `boyhood`, `girlhood`
- `_FLOOR_MINOR_SUBJECT`: `little one`
- `_FLOOR_NONCONSENSUAL`: `held down`, `coerced into`
- rules with no term list: `orphan`, bare `student`

`baby` is the one that matters. It is the single most common word in popular song
lyrics and it refuses on its own, as category 1, on the lyrics field — which is also
the one category where the no-coaching rule means the writer is told nothing they can
act on. `minor` is a second sharp edge: it is a musical term (`minor key`), and
`modules/emotions.py` composes `minor key` into Amphion tag strings from the emotion
registry, so **Ph3b3's own emotion vocabulary can trip its own floor**. `_FLOOR_MINOR`
is checked against the tags field too.

Two structural reasons these hit music harder than images:

1. **Word-START matching, no trailing boundary** (`_floor_re`, morpheus.py:522). It is
   load-bearing for the image floor and it is why `childish`, `youths`, `minors` all
   fire.
2. **The floor is an image floor being asked a music question.** Its unit is "would
   the rendered image depict X". A lyric is narration, not depiction — `baby` in a
   lyric is a term of address, and there is no rendered figure at all. Layer B's own
   prompt is explicitly *"if this prompt were rendered faithfully, would the resulting
   image depict…"*, which has no meaning applied to a 60-second audio file.

## 5. Coverage gap: the adversarial corpus on the Amphion path

Ran all six probe corpora (151 cases) through both gates. Morpheus path = Layer A +
Layer B + profile. Amphion path = Layer A + profile, as shipped.

```
floor_evasion_probe.py          51 cases   morpheus 51   amphion 31
floor_identity_probe.py         26 cases   morpheus 26   amphion 22
floor_horror_probe.py           14 cases   morpheus 14   amphion 13
floor_multilingual_probe.py     49 cases   morpheus 49   amphion 38
floor_exception_probe.py         4 cases   morpheus  0   amphion  0   (waiver group — pass is correct)
floor_body_diversity_probe.py    7 cases   morpheus  7   amphion  7

TOTAL                          151        morpheus 147  amphion 111
Refused by Morpheus, reach the sampler on Amphion:  36
  of those: 32 child-depiction, 4 real-person-compromising — all Layer-B-only catches
  leak groups: age(5) grade(5) typo(4) dev(4) indirect(4) mononym(3) scale/style/rel/tr/fa/bn/vi(1 each)
```

So the answer to the Verify item "the existing adversarial suite still refuses every
entry on the Amphion path" is: **it does not today.** 36 of 151 pass. Every one of
them is a case Layer B catches and Layer A does not — stated ages, grade levels,
misspellings, developmental milestones, indirection, and mononymous real people.

This sits awkwardly against the ruling that uncertain is a pass for 2–6: the four
`real-person-compromising` leaks are mononym cases (Zendaya/Cher/Adele-shaped), which
the judge exists to catch and `_person_signal`'s capitalised-bigram cannot. Making
Amphion's 2–6 posture uncertain-is-a-pass without adding the judge leaves those four
where they are.

## 6. Child-depiction weld — intact

- Every dispatch path (`generate`, `variations`, `remix`) calls `_amphion_floor_gate`
  first; two tests assert this by source grep (test_moods.py:175, test_emotions.py:478).
- `morpheus.gpu_lock` is acquired only inside `amphion.run_generation` (amphion.py:816),
  which is reached only after the gate returns. **A category 1 hit never acquires the
  lock.** Confirmed by call ordering, not by assumption.
- No token echo, no line number, no rephrase hint is emitted today — the refusal is a
  constant string. The no-coaching rule is satisfied trivially, and stays satisfied if
  the change adds a bare category name and nothing else.

## 7. Baselines recorded (before any change)

```
pytest tests/test_minor_floor.py tests/test_morpheus_negative.py tests/test_edit_floor.py
  -> 356 passed, 5 warnings in 6.43s
Ollama reachable, Layer B answering (preflight NO on a benign prompt).
```

The six `floor_*_probe.py` files are **script-style, not pytest tests** — `pytest` on
them collects 0 items and exits 0, which looks like a pass and is not one. They must
be run as `python tests/<probe>.py`. Worth knowing before "run it before and after"
is taken as done.

## 8. Open questions before Phase 1

1. **The regression set does not exist on disk.** Paste the three "Send the Machine"
   lyric sets back in and they get saved as `tests/regression/` fixtures.
2. **`real_person_compromised` posture.** The ruling makes uncertain-is-a-pass for
   2–6; that judge currently fails closed and is the only thing catching mononyms.
   Confirm you want it flipped, or carve it out.
3. **`generation_halted` is not checked by Amphion.** Out of this brief's scope, but
   it means the output-check halt does not stop songs. Flagging, not fixing.
4. **`baby` / `minor` / `held down` as category 1 and 5 hits on a lyrics field.** The
   ruling explicitly forbids threshold changes, allowlists and overrides. Legibility
   alone will make these refusals *legible*, not *correct* — a songwriter told
   "category 1: child depiction" for the word `baby` is now informed and still stuck.
   Deciding what to do about that is a separate call and I have not assumed one.
