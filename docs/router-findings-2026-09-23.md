# Router findings — 2026-09-23

Logged, not fixed. Neither is urgent; both are written down so they are not
rediscovered from scratch.

## 1. A long instructional paste fired the Thoth lane

`[thoth] scripture-intent → forced retrieval under the floor` at 12:17:05.

**Not reproduced, and the suspected cause is wrong.** The hypothesis was that
"claim" / "should and shouldn't" read as debate-mode bait, or that corpus work
names appearing in technical prose were enough. Tested directly against
`is_scripture_intent` with realistic pastes:

| probe | fires? | work-name words present |
|---|---|---|
| our actual brief prose (judges, numbers, jobs) | no | `judges`, `numbers` |
| plain technical prose (`mark`, `job`) | no | `job`, `mark` |
| numbered instructional doc (`claim`, `should and shouldn't`, `Acts`) | no | `acts`, `judges` |
| `What does Genesis 1:1 say?` | **yes** | `genesis` |

So work-name collision alone does **not** trigger it — the classifier also
requires an address or an asks-what-it-says phrase, which is the right shape.
Whatever fired at 12:17:05 is something else.

**Why it cannot be diagnosed from the logs:** the lane deliberately records no
prompt text. That is correct and should stay. To find the trigger, the cheap
move is to log *which pattern matched* — `_QUOTE_ME` / `_CORPUS_MARKER` /
`_ADDRESS` / `names_a_work` / `_CANON_QUESTION` — never the span. That is one
line and keeps the no-prompt-text rule intact.

A length/structure guard (multi-paragraph numbered documents are almost never
scripture queries) is a reasonable second layer, but it should be added knowing
what actually fired, not instead of finding out.

## 2. Thoth's semantic index is EMPTY

Found while chasing the above, and it matters more:

    status() -> {'works': 7, 'passages': 103156,
                 'indexed': 0, 'eligible': 73707, 'missing': 73707}

103,156 passages are in the corpus and **zero** are indexed. Every scripture
query retrieves nothing.

This is why the misroute at 12:17:05 failed safe — not because the guard worked,
but because there was nothing to retrieve. A guard that looks fine only because
the thing it guards is empty is not yet tested.

`thoth: library open — {'indexed': 0, ...}` appears at every boot on 2026-09-21
and 2026-09-23, so it has been in this state for at least two days and is not a
symptom of today's work.

Not fixed here: rebuilding the index is a decision about CPU time and when, not
a patch to slip into a prompt change.
