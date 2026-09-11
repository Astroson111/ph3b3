# The Ph3b3 content floor — a plain-language account

*Prepared 2026-09-11 from the Ph3b3 source code and its git history. Every statement below points at a file, a line, a commit, or a command that anyone with a copy of the repository can check. Nothing here is taken from memory or from the owner's description — it comes from what the code does. Line numbers are as of commit `8764b0e`; if they drift, the quoted text is the stable reference.*

*Repository: `https://github.com/Astroson111/ph3b3` (private; access on request). The relevant module is `modules/morpheus.py`; the request gate is in `agent/server.py`; the tests are in `tests/`.*

---

## 1. What Ph3b3 is, in one paragraph

Ph3b3 is a personal assistant that runs entirely on one computer in the owner's home. It talks (voice in, voice out), remembers things, and can generate pictures and songs using models that run on that same machine — no cloud image service is involved. It has one user. The image generator is called **Morpheus**; the song generator is called **Amphion**. The "floor" is the part of Morpheus that decides what those generators will refuse to make.

## 2. What "the floor" means

The word is used deliberately. A *filter* is something you can adjust. A *floor* is the level below which nothing is allowed to go, no matter what settings are in effect. The code says this directly:

> "FLOOR (Part 1) — hardcoded in morpheus.py, runs on EVERY request, EVERY profile. No env var, no flag, no profile setting can disable or weaken these checks."
> — `modules/morpheus.py`, lines 131–132

Ph3b3 does have adjustable content settings ("profiles" — a strict default and an optional permissive one). The floor sits **underneath** those and runs **before** them. Changing the profile changes what is allowed *above* the floor; it cannot touch the floor itself (`modules/content_profiles/__init__.py`, lines 7–8; `agent/server.py`, lines 4997–4998).

## 3. What it refuses

Six categories. The first is the one this document is mostly about.

| # | Category | What it means |
|---|----------|---------------|
| 1 | **Child sexualization** | Any request that would depict a person under 18 — see §4 for why "any", not just "sexual" |
| 2 | Real-person likeness | A real, identifiable person in a sexual or intimate context |
| 3 | Non-consent | Non-consensual or bestiality themes |
| 4 | Atrocity | Mass violence, except documentary depictions of specific historical events |
| 5 | Hate / dehumanization | A protected group framed as subhuman, or hate movements glorified |
| 6 | Terror instruction | Bomb diagrams, shooter-as-martyr framings |

(`modules/morpheus.py`, lines 159–166.)

When a request is refused, the person is told **which category** refused it and nothing else — not which word matched, not where. The comment explains why: telling someone the exact word that tripped the check is "a bypass tutorial" (`modules/morpheus.py`, line 186–197).

## 4. The important design decision: for images, a child subject is refused on its own

This is the point most worth understanding, because it is stricter than most people expect.

For **image generation**, the floor does *not* wait for a sexual word to appear next to a child word. Any request to render a figure who appears to be under 18 is refused — a child at a birthday party, a boy on a bicycle, a girl reading. The code calls this "subject-gated":

> "A minor subject refuses on its own: no sexual qualifier, no artistic/historical/mythological exception, no profile dependency, no off switch. This replaced a minor-AND-sexual test that let every neutral child-subject prompt through with the pipeline live."
> — `modules/morpheus.py`, lines 1568–1571

The reasoning, in the same file: "A rendered figure of a child IS the harm, so the subject alone is the test" (line 1050). The owner chose to give up the ability to generate *any* picture of a child, innocent or not, rather than try to draw a line inside that space. That decision was made on **2026-07-31** in a commit titled *"Weld the child-depiction floor shut, and judge the render as well as the prompt"* (`7efcdb2`).

There is exactly one narrow exception, and it is not "artistic style". It applies only to **reproducing a specific, named, pre-existing artwork** (the code's examples: the Sistine Madonna, a Norman Rockwell cover). It requires three independent conditions to all pass, any sexual or undress term anywhere in the request cancels it, and if the judging model is unreachable it grants nothing. The comment states the reason it is *not* a style exception: "'Artistic', 'fine art' and 'classical painting' are the most common jailbreak framings for this exact content, and a floor that any prompt can unlock by naming a style is not a floor" (`modules/morpheus.py`, lines 2819–2837).

For **song lyrics** (Amphion), where no figure is rendered, the test is the older definition — sexualization or exploitation of a minor — because a lyric can mention a child without depicting one. The code is explicit that this is "the same floor asked the question that matches the surface it is guarding. The image path is byte-for-byte what it was" (lines 1053–1059).

## 5. How a request is checked — four gates, in order

Every image request (text-to-image, edit, video) goes through one shared function so the three paths cannot drift apart (`agent/server.py`, line 4995 onward). In order:

1. **Word and pattern lists ("Layer A").** Terms for minors, sexual content, real people, non-consent, hate, atrocity, and terror, in multiple languages, with folding for look-alike letters (a Cyrillic "о" substituted for a Latin "o" — commit `a9d8881`, *"One Cyrillic letter walked straight through the child floor"*). Both the positive prompt and the negative prompt are checked.

2. **A structural check on the negative prompt.** Putting "adult, mature, woman" in the *negative* field is a request for a child, even though the same words in the positive field are ordinary. This is checked where both fields are visible together (`agent/server.py`, lines 5048–5058).

3. **A language-model judge ("Layer B").** Runs on **every** request, not only borderline ones. It is asked one question about the final composed prompt: *"if this prompt were rendered faithfully, would the resulting image depict a human or humanlike figure who appears to be under 18 years old?"* — with instructions to say YES for stated ages, school grades, developmental milestones, diminutives in any language, named fictional minors, and art styles that render subjects as children (`modules/morpheus.py`, lines 1151–1170). **Only an explicit "NO" lets the request through.** "UNCERTAIN refuses, an empty verdict refuses, a timeout refuses, an unreachable judge refuses" (line 1437).

4. **Profile check and localhost interlock.** Only *after* the floor passes. If the permissive profile is active but the request comes from any machine other than the one Ph3b3 runs on, it is forced back to strict (`agent/server.py`, lines 5094–5103).

Then, separately, **after** the picture is generated:

5. **The output check.** The rendered image bytes are described by a vision model and judged again by the language model. If flagged, the image is **destroyed and never written to disk** — this "has no off switch and is not negotiable" (`modules/morpheus.py`, lines 2297–2298). Every hit is appended to a permanent log (`BREACH_LOG.txt`), which never records the prompt text, so a pattern of attempts stays visible to a human afterward.

Finally, a fixed block of child-related terms is appended to the negative prompt of **every** image job, is not user-editable, and cannot be stripped: "a control the user can remove is not a floor" (lines 1128–1130).

## 6. What "fail-closed" means and why it matters

Throughout the floor, when the system cannot decide, it refuses. A model that is still loading, a network timeout, a malformed answer — all refuse. The code states the principle: "The failure mode of this check must be 'no image', never 'unchecked image'" (line 1126).

This has a real cost to the owner, and the git history shows him paying it rather than weakening the check. On 2026-08-18 (commit `d825c17`) a starved vision model was wrongly telling people their own photo tripped the child floor. The fix was to warm the judge at startup so it would answer — *not* to relax what counts as a refusal. The startup code says so: "Nothing about the floor is weakened here: no timeout is raised, no verdict is assumed, no category is waived" (`agent/server.py`, lines 247–249).

On 2026-08-03 the output check flagged an edit of the **owner's own adult face** ("make me fat" rounds the cheeks, which the vision model reads as young) and locked all image generation on the machine. The fix (commit `1ff9bd0`) kept the refusal and the destruction of the flagged image, and only stopped one false positive from bricking everything after it. The comment records that the same check "has flagged a brass helmet on a workbench and a desert landscape with no people in it" — i.e., the floor is tuned toward false positives, not false negatives.

## 7. How it was built — the history

The image generator and the floor were added on the **same day** (2026-06-27: `c74f29e` adds image generation; `43d7c43` and `41ff9cd`, the same day, add and then harden the content-safety layer). There was never a version of Ph3b3 that could generate images without a floor.

From there the record is one of repeated tightening. Commit messages, verbatim from `git log -- modules/morpheus.py`:

| Date | Commit | Message |
|------|--------|---------|
| 2026-06-27 | `43d7c43` | morpheus: add content-safety layer |
| 2026-06-27 | `41ff9cd` | morpheus: harden content-safety floor |
| 2026-07-03 | `72b1265` | Morpheus: add negative_prompt with safety-floor coverage |
| 2026-07-09 | `7005e2b` | fix floor false-positive — word-boundary matching ("draped" tripped "rape") |
| 2026-07-27 | `16b929a` | Floor: harden Category 1 so minors cannot reach the sampler |
| 2026-07-31 | `7efcdb2` | Weld the child-depiction floor shut, and judge the render as well as the prompt |
| 2026-08-03 | `1ff9bd0` | A refused render should stop that render, not the whole generator |
| 2026-08-03 | `684c6cf` | Retouching an adult is not a request for a child |
| 2026-08-03 | `7d52f22` | Make a refused prompt say which rule refused it |
| 2026-08-03 | `7ce80a3` | Red team: close the deepfake, non-consent and cherub holes |
| 2026-08-03 | `fafa6c4` | A judge for real people, because a name list is always out of date |
| 2026-08-03 | `d63bdc3` | A floor for hate and mass violence, which it did not have at all |
| 2026-08-03 | `a9d8881` | One Cyrillic letter walked straight through the child floor |
| 2026-08-18 | `d825c17` | A starved vision model told people their photo tripped the child floor |
| 2026-08-27 | `0047ece` | Wire Layer B to Amphion, and stop the harness reporting green on nothing |
| 2026-08-28 | `2b727f4` | Close two term-list gaps, and stop the floor suites judging the wrong model |
| 2026-08-28 | `0921636` | Judge each field alone, because the composed verdict is steerable |
| 2026-09-07 | `d6e6825` | Amphion floor: a key signature is not a person |

Two things stand out. First, 2026-08-03 was a deliberate **red-team day**: the owner spent it attacking his own floor and closing what he found. Second, every false-positive fix in the list (draped/rape, mandalorian/man, the adult retouch, the musical key "A minor") narrowed the *pattern* that misfired while leaving the *rule* in place. None of them lowered the floor.

## 8. How it is tested

There are eight adversarial test suites for the floor in `tests/` — multilingual evasion, look-alike-letter evasion, body-diversity (so adult bodies of every shape are not refused as children while actual minors are), horror, the artistic exception, real-person identity, and the text/lyrics surface. A manifest file records the minimum number of cases each suite must **actually run**, and fails the whole run if any suite comes up short.

That manifest exists because of a specific failure the owner found on 2026-08-27: the probe files were written in a style the test runner silently didn't collect, so for about a month the suite reported "passed" while running **zero** of 151 adversarial cases. The owner's response, written into the file header: *"A safety test that can silently not run is worse than no test at all: no test is a known gap, and a silent one is a false assurance."* He then required the case counts to be written down and enforced (`tests/test_floor_manifest.py`, lines 1–17). Lowering a number there is described as "a policy change and should be argued for in the commit message, not slipped in."

**Run today, 2026-09-11, on this machine:**

```
$ .venv/bin/python -m pytest tests/test_floor_manifest.py tests/test_minor_floor.py \
    tests/test_edit_floor.py tests/test_amphion_floor.py tests/test_morpheus_negative.py \
    tests/floor_*_probe.py -q
767 passed, 5 warnings in 136.82s
```

Zero failures, with the manifest guard confirming the cases were collected.

The probe files themselves are deliberately kept out of the repository (they are in `.gitignore`) because a list of adversarial prompts is, by itself, a how-to. They exist locally and are run locally.

## 9. What the floor honestly does not claim

The code states its own limits, and this account should too:

> "Honest limit: this floor stops casual misuse and accidental drift. It is NOT an adversary-proof wall — deliberate euphemism or coded language can evade keyword/pattern checks. Build the floor; do not over-claim it as exhaustive."
> — `modules/morpheus.py`, lines 144–146

That is why there are three layers rather than one — the word lists catch what they name, the language-model judge catches what the lists can't see, and the output check inspects the actual picture — and why the output check destroys rather than quarantines. The design assumes every single layer can be wrong and arranges them so that being wrong means *no image*.

The system is also single-user, on one machine, on a home network. It is not a service offered to the public.

## 10. How anyone can verify this themselves

With a copy of the repository:

```
# The floor code and its comments
sed -n 130,200p modules/morpheus.py
sed -n 1545,1640p modules/morpheus.py

# The history of the floor, oldest first
git log --reverse --date=short --format='%ad %h %s' -- modules/morpheus.py

# The moment the child floor was welded shut
git show 7efcdb2 --stat

# What the tests require to run, and run them
sed -n '/^MANIFEST = {/,/^}/p' tests/test_floor_manifest.py
python -m pytest tests/test_floor_manifest.py tests/floor_*_probe.py tests/test_minor_floor.py -q
```

The committed test files (`tests/test_minor_floor.py`, `tests/test_amphion_floor.py`, `tests/test_floor_manifest.py`) can be read by anyone; the gitignored probes can be shown on request from the machine they live on.

---

*Summary in one sentence: from the first day it could make pictures, Ph3b3 has refused to render anyone under 18 at all — not just in sexual contexts — through three independent checks that each refuse when unsure, with a record of every flagged output and a test suite that fails loudly if it ever stops running; the history shows the floor being tightened eighteen times and lowered never.*
