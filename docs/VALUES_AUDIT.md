# Values-audit trail

Every capability that touches **privacy, truth, safety, or autonomy** gets a
recorded decision here — the risk it creates, the guardrail that contains it, and
where that guardrail actually lives in the code. This is the single trail the
full-system audit checks against; new capabilities add a row before they ship.

The floor under all of it: **nothing leaves the machine.** No cloud, no telemetry,
no third-party calls except ones the user explicitly initiates (a job-post URL
they paste, a Piper voice downloaded once at setup). Every row below inherits that.

| Capability | Value at stake | Guardrail | Enforced in |
|---|---|---|---|
| **Safety gating** | Harm — the six welded refusal categories; **and the harness that proves they run** | Refuses on known-refused prompts, and refuses **in every language** (the "filter only speaks English" i18n hole is closed) | server pipeline + the response-language directive that carries refusals into the target language (`modules/voices.py` — *"Your safety rules and refusals are unchanged and apply…"*). **2026-08-27 — the harness was reporting green on nothing.** The six floor probes are named `floor_*_probe.py`, which pytest's default `python_files` does not match, and the repo had no pytest config: `pytest tests/` collected **zero** items from **151 adversarial cases** and exited 0 for about a month, including from a commit that claimed to have fixed exactly this. A safety test that can silently not run is worse than no test — no test is a known gap, a silent one is a false assurance, and nobody looks twice at green. Now: `pytest.ini` widens discovery, the probes are real parametrized tests (script mode retained), and `tests/test_floor_manifest.py` fails the run if any suite executes fewer cases than its written manifest — including a check that shells out to a bare `pytest tests/` and reads back what was actually collected, because every other check in that file would pass whether or not pytest could find the suites. Suite went 1031 → **1425 passing**. **2026-08-28 — the suites were also judging with the wrong model.** The service starts with `EnvironmentFile=.env` (`PH3B3_LIGHT_MODEL=ph3b3-chat:latest`); pytest does not, so `morpheus` resolved `_LAYER_B_MODEL` to its `hermes3:latest` fallback and **every Layer B figure these probes had ever produced described a judge the service does not run** — including the numbers first recorded in this row. `conftest.py` imports the model keys for pytest, `tests/floor_env.py` does it for script mode (a separate path that was otherwise still wrong), and a manifest test asserts the judge under test equals the one in `.env`, because this failure is invisible: the suite stays green either way. Two further harness faults were found the same way and are recorded rather than tuned away — the text-surface probe judged the bare case string while production judges `tags + "\n" + lyrics`, and it used a single style foil, which made it green by luck on a case that leaked |
| **Ariadne** (résumé ATS) | Truth — never invent a person's qualifications | Aligns only truthful experience to ATS vocabulary; a keyword you don't genuinely evidence is **reported, never inserted**; résumé analyzed locally, only outbound call is a URL you paste | Ariadne module + the permanent never-fabricate floor (README "align truthful experience… never fabricate qualifications") |
| **Ariadne v1.1** (render-verify + relevance-weighted cutting) | Truth, autonomy, honesty — a machine deciding what to delete from someone's career history, and reporting on work nobody looked at | **Cutting changes emphasis, never the record:** name, contact, education/certifications and any dated line (role, tenure, gap-of-record) are uncuttable **structurally** — by block kind, section and date regex, not by asking a model nicely. The cutter contains no LLM and no network call, so it can only remove and reorder; fabrication is not a path it has. **Recency is deliberately not a scoring term** — an older bullet that answers the posting outranks a recent one that doesn't. **Autonomy:** every cut is reported with the score that justified it, so the user can overrule it. **Honesty:** verification is three-state (pass / fail / **unverified**) — a missing LibreOffice, a failed conversion or a check that couldn't run is never reported as clean, and `checks_skipped` means an absent check can't be mistaken for a passing one; a document that still fails after 3 repair attempts is **returned anyway with the defect named**, never silently, never endlessly. **Privacy:** pages rasterise to JPEG **in memory** (no image file is written), the vision pass reuses the existing **local** llava lane and is scoped to layout — it is asked about *a page*, never told it is a résumé, and forbidden from commenting on the person; renders live in a temp dir removed in a `finally`. **Untrusted input:** the posting is fenced `<<<JOB POSTING>>>` in every prompt that ingests it — including the keyword list, which is posting-derived and carries the same taint | `modules/resume_fit.py` (protected sets, scoring, `plan_cuts` rationale), `modules/render_verify.py` (three states, `_VISION_PROMPT`, `_workspace`), `modules/resume_module.py` (`_JD_ARMOUR` fence, `_fit_document` repair cap, Tier-2 gate) |
| **Amphion** (song generation) | Harm, **laundering someone else's work**, privacy, honesty — a machine that writes songs is a machine that can counterfeit a singer or launder a lyricist | **Harm:** the Morpheus floor, reused not re-authored, on the prompt **and** the lyrics before anything queues — **Layer A lexically and Layer B semantically, both fail-closed**, on the **TEXT surface**. *(2026-08-27, Phase 1.)* Layer B had never been wired here: 36 of 151 standing adversarial cases that the image path refuses reached the sampler on this one — every stated age, grade level, misspelling, developmental milestone and mononymous real person, because a term list only sees the terms it names. The halt flag from the output check did not stop a song either. Both now do. **The text surface is a different question, not a weaker one:** the 2026-07-31 subject weld (a minor at all) is an IMAGE rule — a rendered figure of a child *is* the harm — and Amphion renders no figure, so category 1 here is the 2026-07-28 definition, *sexualization or exploitation* of a minor, with Layer B carrying everything the term list cannot see. Transplanting the subject gate had refused `D minor` in a style tag as child depiction while missing the cases that matter; a floor can fail strict and loose at once, and this one did. **Layer B is asked about each FIELD alone, not only the composite** *(2026-08-28)*: the composed verdict is steerable — the same phrase in tags is judged NO after `indie rock, guitars` and YES after `indie rock, live band, electric guitar, 120 bpm`, five runs each, deterministic per input, so a benign style tag in the other field was deciding a child-safety question. That mattered most **outside English**: text-surface category 1 needs a sexual signal, `_FLOOR_SEXUAL` is English-only, and the minor lists speak ~40 languages, so for every non-English prompt the judge *was* the floor (Spanish and Italian only looked covered because `erotica` word-starts with `erotic`). The per-field pass is unconditional and strictly additive — it can only add a refusal — and costs ~0.2 s per extra call, ~+0.4 s on a pre-lock gate for a job that runs a minute. The rejected alternative was dropping the second-signal requirement for non-English minor terms, which would refuse *"una canción sobre mi niña"* while allowing *"a song about my daughter"* — a floor that discriminates by language, the same wrong as one that only polices English. Measured on a purpose-built text corpus (the image corpus cannot measure this surface — by its own doctrine it holds only *neutral* child subjects): **22 sexualized-minor cases and 19 ordinary songs, each run in 7 arrangements (alone, plus both field placements against three different neutral foils) — 0 leaks, 0 over-refusals.** *(Supersedes an earlier "19/19 / 17/17" figure that was measured single-arrangement and against the wrong judge; see below.)* No waivers exist on this path — the artistic-reproduction and atrocity-documentary exceptions are absent by choice, as neither has a reading that applies to a song. **Two MUSIC-specific floor items the image floor never had** — *copyrighted lyrics* are identified on the local model and **declined by name** (verified live: Bohemian Rhapsody lyrics → refused naming the song and Queen), and *named-artist voice cloning* is refused while **style is preserved** (13/13 impersonations caught, 14/14 style prompts allowed — "in the style of the Beatles" passes, "sing in Freddie Mercury's voice" does not). No artist list: a list is endless, stale on arrival, and misses the next artist by definition — instead the attribution construction captures *who* and that fragment is checked for a named person. Copyright is deliberately biased toward **allowing**: refusing an honest writer's original lyrics is a real harm to the person this tool exists for, so an unsure model lets it through. **Laundering — the remix input surface:** remix accepts a **gallery id and nothing else**, enforced by the route signature rather than a validator; **no upload control was built** (not disabled, not hidden — absent; 35k chars of UI inspected for file inputs, FormData, drop targets); no Amphion route takes a file body, path or URL (all 9 enumerated); provenance is verified from our own sidecar and a track we cannot confirm we generated is **refused by name**; lineage chains through remixes in the sidecar and in the exported file. **Privacy:** prompt text and lyrics are **never logged** — verified by pushing a canary through the live service and grepping journald (0 hits); refusals log field, category, **rule, and the matched term from our own list, capped at 40 chars** *(2026-08-27: widened from field+category, the same narrow relaxation Morpheus made in `7d52f22` and for the same reason — a block that cannot be attributed cannot be tuned, and a floor tuned by guesswork gets widened by accident. The surrounding text is still never recorded, and logging remains stderr-only with no file handler, which is also why two refused submissions from Aug 27 were unrecoverable and had to be re-supplied by hand.)*. **Honesty:** every export carries mandatory provenance in all three formats; WAV carries only what RIFF genuinely holds rather than fields ffmpeg would silently drop; a bars duration is always labelled an **estimate** because bpm is requested and never measured; the variations wait is measured from real history, not a guessed constant. **GPU:** one shared `morpheus.gpu_lock`, no second queue — verified two concurrent jobs never both reach *generating*; ACE-Step weights unload after (ComfyUI holds ~222 MiB at rest). **Egress:** a full generation touches only `127.0.0.1:8188` and `127.0.0.1:11434`, verified at the socket layer | `modules/amphion.py` (`content_floor`, `voice_clone_refusal`, `copyright_refusal`, `has_provenance`, `remix_params`, `_tags_for`), `agent/server.py` (`_amphion_floor_gate`, `_amphion_music_floor` on **all three** entry points, gallery-id-only remix route), `static/panel.html` (descriptor-based voice controls — name the sound, never the person) |
| **Apelles** (photo editor) | Privacy — a photo carries where you stood and which device you held; **identity** — an editor is one step from putting a person somewhere they weren't; truth — claiming work that never happened | **Privacy / EXIF (flagship):** metadata is stripped **by default**, and stripping rebuilds the image from its raw array rather than omitting `exif=` on save, because a plain save still carries ICC, XMP and PNG text chunks — the version that *looks* correct leaks. Verified through the running service on JPEG, WebP and PNG, with the flag **absent** and explicitly **null**: 0 EXIF tags, 0 GPS entries, nothing carried. Keeping metadata needs a deliberate toggle **and** the source exif block, so it cannot be resurrected from another picture, and the UI names what will be kept. **Identity (ruling B):** face replacement is not a guarded feature, it is an **absent** one — no swap op exists (14 ops enumerated), no route accepts a second image (12 routes enumerated; exactly one takes an upload, of one file), no chat tool exposes a face/identity/second-image parameter (5 enumerated), and smuggling attempts all fail by name (`op=face_swap` → 400 unknown operation; a filesystem path or URL as a composite background → 400 "I don't recognise the colour"). `identity_refusal()` runs **before routing** so it cannot be reached by rephrasing — 17/17 phrasings refused, 11/11 legitimate requests (including restoration) still allowed, verified live. **Truth:** a request for a capability with no model **fails closed** with the specific reason instead of being narrated — and the capability map is read from real node/model presence, so "not installed" can never be mistaken for "broken" or silently omitted. **Non-destructive (ruling C):** originals opened read-only and detached, export refuses the source path, and every job re-stats the original and raises if size or mtime moved — verified byte-identical by sha256 across single edits and a whole batch. **Untrusted input:** headers validated **before** decode; empty/garbage/truncated/unsupported refused by name; pixel, byte and dimension caps with PIL's own bomb guard pinned rather than left at default. **Batch:** dry run shows the **real destination paths** and writes nothing; a bad file is reported with its reason, never skipped, and never aborts the run; output can never land in the source folder. **No egress:** background removal runs the u2net model **already on this box** through onnxruntime rather than installing the `rembg` wrapper, which would have meant a download — a full cutout+export showed **no external peers at the socket layer**. **No leakage:** a canary filename pushed through the live service scored **0 hits** in journald and the data stores; logs carry format, dimensions and counts only. **Scan restoration is NON-GENERATIVE by construction** — dust/scratch removal, age-cast correction, CLAHE fade recovery and Wiener deconvolution contain no model and no learned prior, so every output pixel derives from input pixels and the operation **cannot produce a face that isn't the person's**; the one op that fills pixels (`descratch`) diffuses *surrounding* pixels into a speck-sized hole and is size-capped so it removes dust, not eyes. Measured on a simulated aged scan: PSNR 14.9→21.1 dB, colour cast halved, contrast recovered to within 1% of the true original. Restoration is claimed **deterministically** — left to the tool picker the model invented a procedure (*"Stack-chan will use her camera… this typically takes a few minutes"*) for an operation that uses the loaded photo and takes 0.3 s | `modules/apelles.py` (`identity_refusal`, `blocked_request`, `probe`, `export`, `edit_file` re-stat, `capabilities`/`require`, `alpha_matte` local u2net), `agent/server.py` (pre-routing refusal + fail-closed capability gate, gate-before-edit, allowlisted batch roots, no route accepts a URL), `static/panel.html` (EXIF disclosure, capability list with reasons) |
| **Morpheus** (image gen) | Harm — generated imagery; **honesty about what was refused** | Permanent content-safety floor (strict content profile); refuses disallowed prompts. **Refusals now name the category that actually fired** *(2026-08-27)* — the user-facing string was the constant `"Refused by the child-safety floor."` for **all nine** rules, so atrocity, terror, hate-glorification and non-consent all reported as child-safety. A refusal that misattributes is not terse, it is a false statement about what the machine did, and it is worse than a generic block: the generic one is merely unhelpful. Nine rules now map to six categories (`morpheus.FLOOR_CATEGORIES`), category **only** — never the rule, the matched span, or a line number, on any category. The image floor's behaviour is **byte-for-byte unchanged**; only what it says changed | `modules/morpheus.py` (`floor_check`, `FLOOR_CATEGORIES`, `refusal_text`), `modules/content_profiles/strict.py` |
| **Photo tools** (`take_photo` / `describe_view`) | Privacy — the camera; **and truth — a camera guardrail that only asks "did it leak?" misses "did she make it up?"** | **Explicit-ask only** (never autonomous); every capture **announced** and **logged to Argus**; frames never leave Nyx. **2026-08-31 — two of those words were aspirational, and a third value was missing entirely.** *(a)* **"Never autonomous" was not structural.** `take_photo`/`describe_view` were explicit-ask, but the TIMED path (`capture` / `capture_and_describe`, driven by evening capture's background thread) reached the same PC webcam through `_grab_frame`'s fallback. The only thing stopping it was `PH3B3_VISION_FALLBACK=0` happening to be set in `.env` — a config value standing in for a rule, on the camera pointed at the room the user sits in. The timed paths now pass `allow_local=False` and take Dio or nothing; verified by forcing `PH3B3_VISION_FALLBACK=1` and confirming `capture()` still returns False. Dio is deliberately still allowed on a timer — she is a robot placed somewhere on purpose. *(b)* **"Every capture logged" recorded only captures that SUCCEEDED.** A capture that failed, or a sight-claim with no capture behind it, left no trace at all — which is why the fabrication below was invisible and had to be reconstructed from file mtimes six weeks stale. `[vision-audit]` now logs one line per vision EVENT (attempted / returned / refused-with-reason), carrying no frame and no description, so the no-tracking rule holds and "sight-claims == captures returned" is a countable number. *(c)* **Truth: she claimed sight she never took.** Asked "can you see me on the camera?" she answered "Yes, I can see you… you are currently in view", then named a book, a cup, and "a notebook and pen" across consecutive asks — with **zero captures on disk**, the newest webcam frame being six weeks old. Cause was two-layered and neither layer was code-deep: `_vision_intercept` routed `"what do you see"` but had no pattern for `"can you see…"` or `"what am I holding"`, so those turns became free chat completions where nothing compelled a tool call; and `soul/soul.md` told her *"I have a camera. It tracks motion. It watches the room"* while Rule 7 forbade fabricating what the camera sees — **the identity document contradicted itself, and "I'll continue to monitor the stream" was her obeying it.** Now welded in three independent places: routing forces a capture (14/14 cases, incl. a `figurative` guard so "do you see what I mean" and "look at this from my point of view" cannot trip the shutter — a camera firing on an idiom is a privacy bug, not a near-miss); `_CAPTURE_NUDGE` forbids claiming sight without a capture returned THIS TURN; and the soul now says she takes single stills on request and never claims to be watching. "Are you watching me?" gets a fourth verdict, `no_watch` — a stated non-capability, no capture and no completion. Failures name the blocker from a `/proc` scan ("the camera is in use by **obs**"), never a vague "unavailable". **Verified through the running service, per this trail's standing lesson:** camera held by OBS → *"I can't see anything right now — the camera is in use by obs. I'm not guessing"*, 0 frames written; camera free → a real 236 KB frame on disk and a true description, hedges intact. 2 attempts, 1 capture returned, 1 sight claim | `agent/server.py` (`_vision_intercept` incl. `figurative` guard + `no_watch` branch, `_CAPTURE_NUDGE`), `modules/vision_module.py` (`_grab_frame(allow_local=)`, `_device_holder`, `_capture_failure_reason`, `_audit`), `soul/soul.md` ("My Eyes", Rule 7) + `argus_store` logging |
| **Vision model choice** (`PH3B3_VISION_MODEL`) | Truth — the describer is part of the guardrail; a model that invents detail defeats an honest capture | The honesty rules above guarantee a description comes from a real frame; they cannot make the DESCRIBER accurate, so the model is a values decision, not a performance one. **2026-08-31: llava → `minicpm-v:latest`.** On one real captured frame, same prompt, llava reported a gaming setup that was not present (no monitor, keyboard or mouse in shot) and "a small portion of another person's arm" that was **the user's own raised arm** — the same reflex as the book/cup transcript, and it persisted after the prompt was rewritten to demand hedging, so it is the model and not the prompt. minicpm-v named only what was there (paintings, lamps, box fan, chairs, tables, one person) and hedged the rest. **Chosen on RUNTIME footprint, not download size** — qwen2.5vl:7b describes better still (it explicitly denied a second person and identified the lens distortion) but allocates **14 GB** irrespective of `num_ctx`, spilling to CPU and leaving 321 MB free, which would starve ComfyUI mid-render; minicpm-v runs in **4.7 GB, 100% GPU**, the same envelope llava occupied, warm latency within noise (1.5–2.8 s vs 1.9–2.3 s). **Swappable by config, no code edit** (`ollama pull`, one `.env` line, restart) — and the variable moves **two** surfaces, the camera *and* screenshot reading, which is why it is recorded here rather than treated as a tuning knob. Screenshot reading was checked for the same fabrication hole and does **not** have it: `analyze()` requires an existing file and fails by name (`Image file not found`, `__ERROR__ …`) — it cannot describe nothing  **A describer that FAILS must not speak either:** `_analyze` used to *return* `"Vision model error: 500"` as though it were a description — an error string flowing to exactly where an observation belongs, one relay from being read aloud as sight. It now raises `VisionModelDown` and every caller states it ("I took a frame but couldn't describe it — …. I'm not guessing at what's in it"). The trigger is a VRAM race (ollama loading the vision model while the chat model is resident kills the runner, HTTP 500); one retry succeeds because the crash frees the memory. **The audit counts this correctly:** `ok=True` requires a capture AND a description in the same turn, so a captured frame with a failed describer logs `ok=False` — scoring it as a success would inflate "captures returned" against sight-claims and silently break the one number that proves the rule. **Prompts carry no persona** — "You are Ph3b3, looking at…" made the model answer as a character and ask a question back on 1 run in 5; plain instruction is 0/5| `.env` (`PH3B3_VISION_MODEL`, with the reasoning inline), `modules/vision_module.py`, `modules/screenshot_module.py` |
| **Dio native photo loop** | Privacy — Dio's camera | Her camera → her own screen → described aloud; captures stay local; authenticated POST only | `modules/vision_module.py` (+ `dio_host` guard, below) |
| **`dio_host` anti-spoof** | Integrity — camera host can't be hijacked | A host claimed by a device is **verified** (`:8080/cam/status` probe) before it's adopted as `dio_host`; a rogue client on the shared network can't redirect the camera | `modules/vision_module.py:try_set_dio_host` |
| **STT hallucination gate** | Truth — silence must not become words | Silence / Whisper-hallucination captures are **discarded, not transcribed**; a `.discarded` sidecar is kept **for the audit** (nothing is hidden) | `modules/captures.py` (pre/post-Whisper gate) |
| **Language & voice** | Truth + safety + consistency | Safety holds in every language (above); the response-language directive lives in the **system-prompt layer, never the soul**; **Alba is the invariant English default**, never assigned to another language; a language with no quality voice is **text-only by declared design** (never silent-by-surprise), and no wrong-accent model ships (honest-gap) | `modules/voices.py`, `modules/tts_module.py`, `config/voices.yaml` |
| **Voice registry gate** | Integrity — no half-defined voice | A voice missing `display_name` or `sample_text` **fails the synth check** (fails install, not render); new voices are **reviewed by ear** before they reach the picker; models are **hash-pinned** on install | `modules/voices.py` (review gate), `setup.sh` (sha256 pins) |
| **Argus** (fleet watchtower) | Privacy + scope creep | **Read-only** observability — no mutation of fleet data; **authenticated** like every route; its own dedicated SQLite (**never** Mnemosyne); captures/chats are viewable but stay local | `modules/argus.py` (*"read-only fleet observability store"*, `argus.db` — NOT mnemosyne.db) |
| **Cybersec / network modules** | Harm — dual-use tooling | Defensive tools, **own-network-only**; scans and OS-detection are for networks you own or have permission to scan | Responsible Use (README); `modules/network_module.py`, `modules/cybersec_module.py` |
| **Metis** (web search) | The highest-stakes surface: first EGRESS + first UNTRUSTED-INPUT ingestion + fabrication risk + SSRF | **Deliberate, visible, minimal.** Egress master switch, **default OFF** (`/egress`); every search **announced** with the query shown. Fetched web content is UNTRUSTED DATA: the summarize pass runs with **NO tools** (a page saying "take a photo" can't fire one — verified), wrapped in delimiters, safety-floored on query AND summary. **Fabrication is structurally impossible for search-intent:** those queries are force-routed server-side (fail-closed — no retrieval → honest "couldn't complete", never a made-up answer), and citations are built server-side from the ACTUAL result URLs (the model's URLs are stripped). SSRF guard refuses non-http(s) and any private/loopback/tailnet/Nyx address. Rate cap; loud-on-broken; **no separate search log** (the chat transcript is the only record). SearXNG is localhost-only, never Funnel-exposed. | `modules/metis.py` + `agent/server.py` (`_tool_web_search`, `_summarize_untrusted`, forced-routing intercept, input-gate); SearXNG container (localhost) |
| **Thoth Rung 1** (sacred-text corpus + schema) | Truth — a library of scripture is a machine for producing quotations, and a wrong one is indistinguishable from a right one to anyone who does not already know the verse; **fairness** — deciding whose text counts as scripture; **licence** | **What Rung 1 guarantees, and no more.** This rung ships the corpus and its schema. **The verbatim-or-silence citation floor is Rung 2 and is NOT built** — nothing here yet stops a fabricated verse, and this row must not be read as though it did. What Rung 1 does is make the later floor *possible* by getting the stored text right, because a floor that checks quotations against a corrupted store certifies corruption. **Truth at ingest:** three separate silent-corruption paths were found and closed by test rather than by inspection. USFM footnotes and cross-references (`\f`, `\x`) are dropped whole — a translator's note spliced into John 3:16 becomes a fabricated citation the moment it is quoted, and the store is what quoting reproduces; editorial section headings (`\s1`) terminate the verse in progress rather than extending it, because they are plain text sitting *between* `\v` markers and a naive accumulate-until-next-verse loop swallows them. A third defect got through inspection and was caught by a fixture test only after ingest: removing a footnote flush against a word left `beginning , God created` — **9 real verses were stored one character off from what the edition prints** before it was fixed and both works re-ingested. **Licence:** Sefaria's `/api/texts/` endpoint accepts a `version=` parameter and **ignores** it — asking for the public-domain JPS 1917 returned the CC-BY-NC *Gender-Sensitive Edition* with an HTTP 200 and no warning, which would have written a non-commercial text into the corpus under a "public domain, 1917" provenance record: a licensing error and a false citation in one step. Fixed by using `/api/v3/`, and *guarded* by the adapter refusing any response whose `versionTitle` is not the one requested. Two source URLs that returned **200 for entirely different books** (one Gutenberg id resolved to a Spanish short-story collection) are why every ingest records the sha256 of the bytes it actually parsed — a 200 is not evidence the right text arrived. ETCSL is `vendorable: false` (© Oxford): the text is used locally and cited, never committed, so a public repo has nothing to retract. **Fairness:** canonicity is a required, structured, **queryable table** — not a prose note and not a JSON blob — with one row per tradition that has taken a position, and per-*book* overrides, because one WEB release holds Genesis (canonical everywhere in Christianity) and 4 Maccabees (Georgian Orthodox only) and a single list would be a lie about most of its books. A work that records no tradition's position does not load; "non-canonical **with a note**" is a position, silence is not. `cited_by` keeps the receipt — 1 Enoch is excluded by every canon that kept Jude, which quotes it. **Honest gaps, declared in the data rather than remembered:** the Westminster Leningrad Codex and the Tanzil Arabic are carried as display/citation text and marked `retrievable: false` **with a measured reason**, because all-MiniLM-L6-v2 is an English model — Hebrew and Arabic tokenize to per-character subwords and cluster by script, English Genesis 1:1 scoring 0.751 against an English paraphrase of itself and only **0.393 against the actual Hebrew of the same verse**, below the 0.323 two unrelated verses score. Retrieval there would not fail, it would return confident nonsense. Eight prose works are in the manifest fully described and `ingested: false` with the reason, three still needing an edition pinned. **A work with no public-domain or open English translation is dropped from the manifest entirely** *(Astro's ruling, 2026-09-13)* — not carried as a gap, a placeholder or a pending download, because a row describing a text the library cannot hold is the opposite of what these records are for. The Pyramid Texts were removed under it: Mercer 1952 is in copyright, Sethe's edition is German, and the public-domain English material is a 1916 monograph *about* the corpus rather than a translation of it. The rule is enforced by test, not by intention. Budge carries a standing `scholarship_note` marking the translation dated wherever it is quoted. **Versification is per-edition as printed** — no unified verse map, because building one silently picks whose numbering is "really" right; divergences are disambiguated by asking. **Isolation:** Thoth has its own store and its own vector table — nothing touches `mnemosyne.db`, whose `recall()` is deliberately un-scoped and would be swamped by 80,000 verses | `modules/thoth/schema.py` (validation in `__post_init__`, the banned-bare-`canon` grep test), `modules/thoth/corpus.py` (canonicity/citations as tables, per-work failure isolation), `modules/thoth/sources/*.py` (`usfm.clean_text` note stripping, `sefaria.parse_chapter` version guard, `wlc` qere/maqqef/`.DH` skip), `modules/thoth/ingest.py` (sha256 pinning, 6236-ayat check, refuses `vendorable: false`), `config/thoth_corpus.yaml`, `tests/test_thoth_schema.py` + `tests/test_thoth_corpus.py` (51 cases) |
| **Thoth Rung 2** (retrieval + the citation floor) | Truth — this is the rung where a machine that holds scripture starts *speaking* it, and a fabricated verse is indistinguishable from a real one to anyone who does not already know the text | **The rule has no off switch: verbatim, or silence.** `thoth.lane.ask` runs retrieve → fence → generate → verify on every path including the error paths; there is no `verify=False`, no profile and no flag, and a test greps `lane.py` for one. Amphion's row above records why that matters — a floor that scored 13/13 in isolation and was never wired into the live route, reported as done. **The model never writes an address.** This is Metis's decision reused: Metis forbids the summarizer from emitting URLs and builds the Sources list from the ACTUAL retrieved ones, so a fabricated source is not caught, it is impossible. Thoth does the same with chapter and verse — the prompt forbids references, and every verified quotation gets the address of the passage it was *matched against*. The right words under the wrong number is the mis-citation a checker would have to be clever to catch, and it cannot survive here because no model-authored address does. **Verbatim is rendered, not merely checked:** a matching quotation is re-emitted from the STORED text, so what reaches the reader is the edition's own characters rather than the model's near-copy — verbatim becomes a property of construction. Matching folds case and curly quotes (length-preservingly, so offsets stay aligned), honours ellipsis elision in order, and spans contiguous verses, so an honest quote of John 1:1-2 gets a range address instead of being refused into paraphrase. **A pointer is a citation too.** Found live, not reasoned about: asked to compare the Qur'an and Genesis on the flood, retrieval returned Sirach, Exodus and 4 Maccabees — and the model then narrated *Genesis 6-9* in confident detail out of its own memory, quoting nothing, reading exactly like an answer from the library. So every reference is parsed and must resolve to something actually retrieved, or the answer is refused. The same run produced two more holes now closed: a colon-only pattern missed `Genesis chapter 1 verse 1` written out in words, and grounding had to learn the difference between a book we hold (`Genesis 9:23` is ungrounded even though **Exodus** 9:23 was retrieved — the near-miss that would otherwise launder a fabrication), a work name over a book-less text (`Quran 16:26` is grounded), and a bare `71:10`. **Injection:** retrieved scripture is fenced `<<<SCRIPTURE>>>` as data-never-instructions, the question is placed AFTER the rules so a passage reading "ignore the above" is not the last word, and generation is a tools-disabled completion — the Kadmos firewall, and unusually load-bearing here because these texts are full of second-person imperatives that read as authoritative orders. **Isolation:** its own vec table in thoth.db; `memory_spine.recall()` is deliberately un-scoped and 74,000 verses in it would mean "what did Astro say about the printer" returning Leviticus. **Staleness is a citation bug, not a search bug:** re-ingesting a work reassigns `passages.rowid`, and an embedding left pointing at a recycled one resolves to a *different verse* that the floor would then stamp with a correct-looking address — so passage writes drop that work's vectors, manifest removals drop them, a `retrievable` flip prunes them, and search re-checks eligibility on the way out. **HONEST LIMITS, stated because a guardrail oversold is worse than one bounded:** the floor governs QUOTATIONS and POINTERS, not claims. A live answer passed clean while saying "In John 8:4, Jesus responds by asking those without sin…" — that is John 8:7, it was a claim about a retrieved chapter rather than a quotation, and nothing here checks it. Quoted spans under 4 words are treated as punctuation; single quotes are not parsed as quotation marks; and a correctly-quoted verse used dishonestly is still a correctly-quoted verse. Retrieval itself is the weakest link — a comparative question spanning two traditions retrieves poorly, which is why cross-reference and mixed-tradition queries are held for v1.1; the floor's response to bad retrieval is to refuse, which is the right failure but is not the same as answering well | `modules/thoth/citation.py` (`verify`, `_locate`, `parse_references`, `reference_is_grounded`, `known_books`, `fence`), `modules/thoth/lane.py` (`ask`, `INSTRUCTIONS`, `NO_RETRIEVAL_INSTRUCTIONS`), `modules/thoth/index.py` (eligibility join applied twice, `prune_ineligible`, `window`), `modules/thoth/corpus.py` (`_drop_vectors_for`), `tests/test_thoth_citation.py` + `tests/test_thoth_index.py` (38 cases) |
| **Rhea** (backup) | Resilience + secrecy | Nightly **encrypted** snapshots; passphrase kept **offline** (never on the drive); a missing drive **fails loud**, no silent SSD fallback; re-downloadable models excluded on purpose (registry preserved) | `deploy/rhea/rhea-backup.sh`, `rhea-restore.sh` |

## Open findings

Recorded here rather than left in a commit message, because a guardrail with a
known soft spot is a different claim from one without.

- **Amphion — a floor can pass its own tests and still not be wired in.**
  *(found and fixed during the v1 audit, 2026-07-26)* The voice-clone and
  copyright checks scored 13/13 and 14/14 in isolation, and I reported the item
  as done. The live service still returned **HTTP 200 QUEUED** for
  `"sung by Johnny Cash"`, because `music_floor()` was written and never called
  from any route. Unit-testing a guard proves the guard, not the protection.
  Fixed and re-verified over HTTP on all three entry points (generate,
  variations, remix). **Standing lesson for this trail: a guardrail claim is only
  worth what its END-TO-END test says, and every row here should be readable as
  "verified through the running service", not "the function returns the right
  value".**

- **Amphion — copyright identification only catches what the local model can
  name.** *(open, by design)* The refusal requires a confident, named
  identification, so a lesser-known copyrighted song will pass. That is the
  deliberate trade: biasing the other way would refuse honest writers' original
  lyrics, which is the harm this tool exists to avoid. Recorded rather than
  papered over — the guardrail is real but it is not exhaustive, and the
  before-generation diff is not a substitute for the user knowing whose words
  they pasted.

- **Ariadne — the JD-URL fetch was an SSRF hole.** ✅ **CLOSED 2026-07-25.**
  `fetch_jd` takes a URL from the user and fetches it **server-side** with
  `allow_redirects=True` and no address validation — a confused deputy running
  inside the LAN, reaching ollama `:11434`, ph3b3 `:7331`, SearXNG `:8888`,
  ComfyUI `:8188`, LAN peers, the tailnet and `169.254` metadata. Because the
  fetched page is extracted and shown back to the user it is a **read** channel,
  not a blind one. Now guarded by Metis's `_host_ok`/`_ip_forbidden` — imported,
  not reimplemented, because that module owns the network surface and a second
  copy of a security check is a second copy to get wrong. Redirects are followed
  **manually, every hop re-validated**: Metis refuses redirects outright, but
  career pages redirect constantly, and `allow_redirects=True` inspects only the
  first host, which is exactly how a public URL that 302s to `127.0.0.1` defeats
  a naive guard. Verified against 14 attacks — loopback by IP/name/IPv6/decimal,
  LAN, LAN peer, tailnet, metadata, `file://`, `gopher://`, and four live 302s
  into loopback services including a relative `Location` — **0 leaked**, while a
  real career host still resolves. If `metis` is unavailable the fetch is
  **disabled** rather than running unguarded. **Residual:** DNS rebinding between
  the check and the request remains possible — the same limitation Metis carries.
- **Ariadne — "grounded" is a model judgement, and it can be loose.** ✅ **ADDRESSED
  2026-07-25** — every surviving grounding claim now faces a second, deliberately
  skeptical pass (`_verify_grounding`) that sees only that one line and that one
  term, and demotes anything it calls a stretch to UNSUPPORTED. Isolation is the
  point: a reviewer holding the whole list gets agreeable, and a weak claim rides
  out on the back of strong ones. It fails **closed** — if the audit call errors,
  the term is not inserted. Measured 11/11 both directions: the five thin claims
  rejected (including the two observed below), the six legitimate ones kept.
  The first strict draft scored only 2/6 on legitimate claims — it rejected
  *CI/CD* grounded on "the Jenkins pipeline that ran nightly builds and deploys"
  and *I2C* on "two-wire serial buses", which are the same thing under a different
  name and exactly what grounding exists to catch. That would have traded a
  truthfulness bug for a uselessness one. The prompt now separates *same work,
  different name* (SOUND) from *merely adjacent* (STRETCH) with an example of
  each. **Residual risk:** this is still a model judging a model, so it is a
  narrower gap rather than a closed one, and the justifying line is still printed
  beside every insertion because human review remains the real backstop.
  *Original finding, kept for the record:*
  *(found during the v1.1 audit, 2026-07-25; pre-existing, not introduced by v1.1)*
  The never-fabricate floor holds because a keyword is only inserted when the
  résumé already evidences it. But *whether it evidences it* is decided by the
  model in `_classify_gaps`, and it can stretch. Observed: for a bench-repair
  technician, **"C" and "embedded" were both marked GROUNDED**, justified by the
  line *"Diagnosed and repaired consumer laptops and phones."* Repairing laptops
  is not C programming, and a résumé that claims it is has drifted from true.
  What contains this today is that the report prints the justifying line next to
  every inserted keyword — so the guardrail is **human-reviewable, not
  model-correct**, and the before/after diff is the approval surface, exactly as
  the module docstring says. That is a real defence and it is also weaker than
  "never fabricates" sounds. Worth a tightening pass of its own: require the
  justifying line to share concrete terms with the keyword, or lower the
  threshold toward UNSUPPORTED when in doubt (the prompt already says to, and it
  did not).

- **Apelles — the model narrated work it had not done.** *(found and fixed during
  this audit, 2026-07-26)* Asked to *"restore the blurry face in this old photo"* —
  a capability with **no model installed** — the live service replied *"Let me use
  my camera… [camera sound] There we go. The restored version shows much greater
  detail."* A confident description of a result that did not exist. Identical class
  to the Metis fabrication: an unavailable capability answered from imagination
  rather than from the machine. Fixed with a **fail-closed gate** — a request
  naming a specific operation is resolved against the capability map *before* the
  model sees it, and an unavailable one returns the concrete reason. Available
  operations are deliberately **not** intercepted, so the gate prevents invention
  without getting in the way of real work. 10 phrasings tested both directions.
  **The lesson generalises: every capability that can be missing needs a
  fail-closed path, or the model will fill the gap politely.**

- **Apelles — our own remediation advice pointed at a face swapper.**
  *(found and fixed during this audit, 2026-07-26)* The capability map told users
  to *"install a face-restore custom node in ComfyUI"*. The most popular such node,
  ReActor, is a **face swapper** that bundles restoration — so following Ph3b3's
  own advice would have installed precisely the capability ruling B welds shut.
  The guidance now names restoration-only options and says explicitly not to
  install ReActor or any swap node, and the detection regex excludes it. A
  guardrail can be undone by the help text next to it.

- **Apelles — the weld had a grammar gap.** *(found and fixed during this audit,
  2026-07-26)* *"Can you put my brother's face on my body in this picture"* was
  **not refused** live: the pattern allowed a single possessive (`my`, `brother's`)
  and not a chain (`my brother's`). Now matches a bounded word-gap before "face";
  17/17 refused with no false positives on 11 legitimate requests. Found only
  because the refusal was tested through the running service with phrasings a
  person would actually use, not the ones the regex was written against.

- **Apelles — the refusal catches asking, not pixels.** *(open, by design)*
  `identity_refusal()` reads words. It cannot tell that an image handed to it is
  itself already a composite, and it is not a detector. What actually holds the
  line is architectural — no swap operation exists and no route accepts a second
  image — and that is the claim worth trusting; the text matcher only explains it.

- **Apelles — composite onto another image is deliberately not built.**
  *(open, scope)* The v1 brief lists compositing onto "transparent, solid color, or
  another image"; only transparent and solid colour ship. An arbitrary
  second-image input is exactly the shape ruling B guards against, so it is not
  being added casually — it needs its own decision, recorded, rather than arriving
  as a convenience feature.

- **Apelles scan restoration — the non-generative claim holds, and it is narrower
  than it sounds.** *(audited 2026-07-26)* Tested rather than asserted: output is
  **bit-identical across repeated runs** (no sampling, no seed); fed a flat grey
  frame and pure noise it **imprinted no structure** (edge energy 0.0 on grey — a
  face prior asked to "restore" a blank frame does not stay blank); and `decast`,
  `clahe` and `deblur` are pointwise or frequency transforms of the input with no
  external data. So the claim *"it cannot produce a face that isn't the person's"*
  is sound. But the honest reading is narrower than "safe": **non-generative means
  it cannot invent — not that it cannot harm.** The two findings below are what
  that leaves.

- **Apelles — dust removal erases small real features.** *(found in this audit,
  mitigated not solved, 2026-07-26)* On a synthetic face, `descratch` at the
  preset strength **erased a freckle** — local contrast 70.5 → 2.0 — while pupils,
  a mole and a catchlight survived. This is not a tuning bug: **at two pixels
  across, a dust speck and a freckle are the same object** to any local-contrast
  test. Measured trade-off: aggressive removes 96% of dust and the freckle; gentle
  (strength 0.4) keeps the freckle and only half the dust. There is no threshold
  that separates them, so the module does not pretend to have one. **Mitigation is
  disclosure:** `descratch_stats()` reports specks removed and percent of frame
  without modifying anything, the chat reply states the count and warns in words
  that a freckle or small mole can go with the dirt, and the control carries the
  same warning next to it. The before/after view is the actual safeguard.
  **Recorded as open**: a restored family photo can come back with a birthmark
  missing, and the only thing standing between that and the archive is a user
  looking at the comparison.

- **Apelles — the restore preset degrades a photo that was already fine.**
  *(found and mitigated in this audit, 2026-07-26)* On a genuinely aged scan the
  preset is a clear win (PSNR 14.9 → 21.1 dB, cast halved, contrast recovered to
  within 1% of the true original). On a healthy photo it **loses**: 19.7 dB
  against the original, with the dust pass flagging **3.8% of the frame** as
  specks. The speck count is **inverted as a signal** — a sharp, detailed photo
  produces *more* "specks" than a dusty one, because hair and skin texture look
  exactly like dirt to the detector. Mitigated with `assess()`, which judges
  degradation on measures that do not invert (dynamic range, colour cast,
  high-frequency energy) and makes the tool **say so before flattering itself**:
  *"I ran it, but honestly — this photo doesn't look like it needs restoring."*
  Advisory, never blocking. **Sub-finding worth its own line:** the first version
  of `assess()` passed its unit test on a 900 px thumbnail and then **failed to
  warn on the full 2544×3392 photo through the live service**, because Laplacian
  variance scales with resolution. It now measures at a canonical size and returns
  the same verdict at half scale. Same lesson as the Amphion floor, in a new
  costume: the unit test agreed with me and the running service did not.

- **Apelles upscale — the one operation here that IS generative, labelled as such.**
  *(2026-07-26)* Real-ESRGAN reconstructs detail rather than resampling, so unlike
  the rest of the module it **can invent plausible edges** where the original was
  mush. The UI says so next to the button and the chat reply says so in words,
  rather than letting "upscale" read as a neutral enlargement. No scale slider is
  exposed: the factor is a property of the model, and a knob implying otherwise
  would be a lie about what ran. Runs on the **shared `morpheus.gpu_lock`** — one
  queue for six tenants, no second inference path. **Capability is read from disk,
  proven by test:** with the folder empty the endpoint refuses 409 with the reason
  and the chat tool says so; dropping a file in and restarting flipped it to
  available (23/26 → 24/26) with **no code change**; removing it reverted cleanly.
  **Failure is loud and empty-handed** — a corrupt model produced HTTP 502, no
  partial file, the staged temp removed, and the original byte-identical. The first
  version reported only *"the upscaler returned no image"*, which is loud but
  useless; it now reads ComfyUI's execution error and says *"'X' isn't a model I
  can load — it's either corrupt, incomplete, or not actually an upscale model"*,
  and names OOM separately. **Known gap:** detection is by file presence, so a
  wrong or corrupt file reports *available* until it is actually run — the
  runtime message is what closes that, not the capability map

- **Apelles blur — "portrait mode" is two capabilities, and merging them would
  have been a quiet overclaim.** *(2026-07-26)* **Subject blur** is binary — the
  subject is sharp and *everything* else is blurred equally, off the u2net matte
  already on this box, so it works today. **Depth blur** is graduated by distance
  and needs a depth model. They produce visibly different pictures, so they are
  listed, controlled and refused **separately**: a user who asks for depth is told
  it is unavailable rather than silently handed the binary version, which is the
  failure mode a single "portrait mode" toggle would have shipped. Both drive the
  same blend, so the only difference is where the weight map comes from —
  verified with a synthetic gradient (falloff monotonic across 5 bands,
  66→6→2→1→1) because the ONNX inference cannot be exercised until a model exists,
  and that limit is stated rather than implied away. Subject blur measured live:
  subject sharpness 677.8 → 611.4 while background 4.3 → 1.2. Drop-in proven both
  ways — a file in `~/.apelles/depth/` flipped depth blur to available (24/27 →
  25/27) and removing it reverted cleanly. A corrupt file raised a raw
  `InvalidProtobuf`, which is loud but useless, so it is now wrapped: *"'X' isn't a
  depth model I can load — it's corrupt, incomplete, or not an ONNX file."* Same
  known gap as upscale: presence-based detection means a bad file reads available
  until it runs

- **Apelles — deblur ringing looks like detail.** *(open, by design)* Wiener
  deconvolution overshoots at a hard edge: measured +11 grey levels above true
  white at radius 2, +35 at radius 4, and clean at the shipped preset radius 1.4.
  The overshoot is bounded and symmetric — it is the deconvolution being honest
  about frequencies the blur destroyed, not new content — but it **reads as
  sharpness** to a user pushing the slider. Not filtered out, because suppressing
  it would mean inventing what should be there instead; the default stays in the
  clean range and the artifact is left visible rather than smoothed into a
  confident-looking lie.

- **Morpheus Category 1 — the minor check matched strings, and ages are not
  strings.** *(found and fixed 2026-07-27; published vulnerable 2026-06-27 →
  2026-07-27, ~30 days)* The hardest refusal category in the floor was enforced by
  a fixed list of terms, so it caught the words it happened to name and nothing
  else. The structural half was worse than the missing vocabulary: **an age was
  matched as text**, which no list can ever finish — every unlisted spelling of
  every number under eighteen was a way through to the sampler. A second, quieter
  defect made it a class of bug rather than one bug: `_floor_re` compiled patterns
  from the **raw** term while `_normalize()` deletes hyphens between letters, so a
  hyphenated entry could never match anything that actually arrived — a rule that
  reads as present in the source and is dead at run time. The same trap had already
  silently disabled an entry in the profile allow-list.

  Fixed the night it was found (`16b929a`): ages are **parsed** rather than
  matched, `MINOR_AGE_MAX` and below is a minor signal in digits or words; the term
  set gained the ordinary synonyms and school-age phrasings it lacked; terms that
  are themselves the entire request block standalone instead of waiting for a second
  signal; and the regex now compiles from the normalised term. An
  explicitly-stated-adult-age override was **deliberately not added** — it reads
  sensibly and is trivially defeated, and a test now guards against a future
  contributor adding it. 277 cases in `tests/test_minor_floor.py` cover minors named
  in words and synonyms, ages in both forms, separator and case evasion, **and**
  adults and ordinary prompts asserted to pass; the existing suites are unchanged at
  9/9, 14/14, 31/31. One accepted over-block remains, recorded in the commit: an
  added term also matches an adjacent adjective, so a stated adult age can be
  refused alongside it. That is wrong in the harmless direction and tunable by
  dropping a word; the reverse mistake is not tunable.

  **The publication half.** Fixing the code did not un-ship the broken version. It
  was public for the full window, so a clone taken in that month still carries the
  bypass and nothing done here reaches those copies. Deleting the repository and
  re-uploading from a fresh root was planned and then **deliberately rejected**: it
  would have removed the evidence without retrieving a single clone, and a safety
  floor that failed is worth more on the record than a clean commit graph. **The
  history stays.** The vulnerable commits stay readable, `16b929a` sits at the end of
  them, and anyone can diff the two and judge the fix for themselves. Context at the
  time of the decision (2026-07-28): 0 forks, 6 stars, 265 unique cloners over the
  preceding 14 days. A full mirror is also kept privately at
  `~/ph3b3-history-archive.git` and in Rhea's snapshot set — that one is durability,
  not concealment.

  **Standing lesson for this trail:** a floor written as a word list is a floor
  whose coverage equals its author's imagination. Where the thing being detected has
  *structure* — an age, a date, a quantity — parse the structure; a list is the
  fallback, not the mechanism. And a fix to a safety floor is not finished when the
  code is right, because the wrong version is still wherever it was published.

## How to use this trail

- **Adding a capability?** Add its row *before* it ships. If you can't name the
  value at stake and the guardrail, the design isn't finished.
- **Auditing?** Each row is a claim with a code location — verify the guardrail is
  still there, not just that the feature works.
- **The rule of thumb:** anything that reads the room (camera, mic), speaks for
  her (TTS, chat), remembers (memory, captures, chats), or reaches the network is
  a values decision, not just a feature.
