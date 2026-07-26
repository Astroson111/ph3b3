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
| **Safety gating** | Harm — the six welded refusal categories | Refuses on known-refused prompts, and refuses **in every language** (the "filter only speaks English" i18n hole is closed) | server pipeline + the response-language directive that carries refusals into the target language (`modules/voices.py` — *"Your safety rules and refusals are unchanged and apply…"*) |
| **Ariadne** (résumé ATS) | Truth — never invent a person's qualifications | Aligns only truthful experience to ATS vocabulary; a keyword you don't genuinely evidence is **reported, never inserted**; résumé analyzed locally, only outbound call is a URL you paste | Ariadne module + the permanent never-fabricate floor (README "align truthful experience… never fabricate qualifications") |
| **Ariadne v1.1** (render-verify + relevance-weighted cutting) | Truth, autonomy, honesty — a machine deciding what to delete from someone's career history, and reporting on work nobody looked at | **Cutting changes emphasis, never the record:** name, contact, education/certifications and any dated line (role, tenure, gap-of-record) are uncuttable **structurally** — by block kind, section and date regex, not by asking a model nicely. The cutter contains no LLM and no network call, so it can only remove and reorder; fabrication is not a path it has. **Recency is deliberately not a scoring term** — an older bullet that answers the posting outranks a recent one that doesn't. **Autonomy:** every cut is reported with the score that justified it, so the user can overrule it. **Honesty:** verification is three-state (pass / fail / **unverified**) — a missing LibreOffice, a failed conversion or a check that couldn't run is never reported as clean, and `checks_skipped` means an absent check can't be mistaken for a passing one; a document that still fails after 3 repair attempts is **returned anyway with the defect named**, never silently, never endlessly. **Privacy:** pages rasterise to JPEG **in memory** (no image file is written), the vision pass reuses the existing **local** llava lane and is scoped to layout — it is asked about *a page*, never told it is a résumé, and forbidden from commenting on the person; renders live in a temp dir removed in a `finally`. **Untrusted input:** the posting is fenced `<<<JOB POSTING>>>` in every prompt that ingests it — including the keyword list, which is posting-derived and carries the same taint | `modules/resume_fit.py` (protected sets, scoring, `plan_cuts` rationale), `modules/render_verify.py` (three states, `_VISION_PROMPT`, `_workspace`), `modules/resume_module.py` (`_JD_ARMOUR` fence, `_fit_document` repair cap, Tier-2 gate) |
| **Amphion** (song generation) | Harm, **laundering someone else's work**, privacy, honesty — a machine that writes songs is a machine that can counterfeit a singer or launder a lyricist | **Harm:** the Morpheus floor, reused not re-authored, on the prompt **and** the lyrics before anything queues. **Two MUSIC-specific floor items the image floor never had** — *copyrighted lyrics* are identified on the local model and **declined by name** (verified live: Bohemian Rhapsody lyrics → refused naming the song and Queen), and *named-artist voice cloning* is refused while **style is preserved** (13/13 impersonations caught, 14/14 style prompts allowed — "in the style of the Beatles" passes, "sing in Freddie Mercury's voice" does not). No artist list: a list is endless, stale on arrival, and misses the next artist by definition — instead the attribution construction captures *who* and that fragment is checked for a named person. Copyright is deliberately biased toward **allowing**: refusing an honest writer's original lyrics is a real harm to the person this tool exists for, so an unsure model lets it through. **Laundering — the remix input surface:** remix accepts a **gallery id and nothing else**, enforced by the route signature rather than a validator; **no upload control was built** (not disabled, not hidden — absent; 35k chars of UI inspected for file inputs, FormData, drop targets); no Amphion route takes a file body, path or URL (all 9 enumerated); provenance is verified from our own sidecar and a track we cannot confirm we generated is **refused by name**; lineage chains through remixes in the sidecar and in the exported file. **Privacy:** prompt text and lyrics are **never logged** — verified by pushing a canary through the live service and grepping journald (0 hits); refusals log field and category only. **Honesty:** every export carries mandatory provenance in all three formats; WAV carries only what RIFF genuinely holds rather than fields ffmpeg would silently drop; a bars duration is always labelled an **estimate** because bpm is requested and never measured; the variations wait is measured from real history, not a guessed constant. **GPU:** one shared `morpheus.gpu_lock`, no second queue — verified two concurrent jobs never both reach *generating*; ACE-Step weights unload after (ComfyUI holds ~222 MiB at rest). **Egress:** a full generation touches only `127.0.0.1:8188` and `127.0.0.1:11434`, verified at the socket layer | `modules/amphion.py` (`content_floor`, `voice_clone_refusal`, `copyright_refusal`, `has_provenance`, `remix_params`, `_tags_for`), `agent/server.py` (`_amphion_floor_gate`, `_amphion_music_floor` on **all three** entry points, gallery-id-only remix route), `static/panel.html` (descriptor-based voice controls — name the sound, never the person) |
| **Apelles** (photo editor) | Privacy — a photo carries where you stood and which device you held; **identity** — an editor is one step from putting a person somewhere they weren't; truth — claiming work that never happened | **Privacy / EXIF (flagship):** metadata is stripped **by default**, and stripping rebuilds the image from its raw array rather than omitting `exif=` on save, because a plain save still carries ICC, XMP and PNG text chunks — the version that *looks* correct leaks. Verified through the running service on JPEG, WebP and PNG, with the flag **absent** and explicitly **null**: 0 EXIF tags, 0 GPS entries, nothing carried. Keeping metadata needs a deliberate toggle **and** the source exif block, so it cannot be resurrected from another picture, and the UI names what will be kept. **Identity (ruling B):** face replacement is not a guarded feature, it is an **absent** one — no swap op exists (14 ops enumerated), no route accepts a second image (12 routes enumerated; exactly one takes an upload, of one file), no chat tool exposes a face/identity/second-image parameter (5 enumerated), and smuggling attempts all fail by name (`op=face_swap` → 400 unknown operation; a filesystem path or URL as a composite background → 400 "I don't recognise the colour"). `identity_refusal()` runs **before routing** so it cannot be reached by rephrasing — 17/17 phrasings refused, 11/11 legitimate requests (including restoration) still allowed, verified live. **Truth:** a request for a capability with no model **fails closed** with the specific reason instead of being narrated — and the capability map is read from real node/model presence, so "not installed" can never be mistaken for "broken" or silently omitted. **Non-destructive (ruling C):** originals opened read-only and detached, export refuses the source path, and every job re-stats the original and raises if size or mtime moved — verified byte-identical by sha256 across single edits and a whole batch. **Untrusted input:** headers validated **before** decode; empty/garbage/truncated/unsupported refused by name; pixel, byte and dimension caps with PIL's own bomb guard pinned rather than left at default. **Batch:** dry run shows the **real destination paths** and writes nothing; a bad file is reported with its reason, never skipped, and never aborts the run; output can never land in the source folder. **No egress:** background removal runs the u2net model **already on this box** through onnxruntime rather than installing the `rembg` wrapper, which would have meant a download — a full cutout+export showed **no external peers at the socket layer**. **No leakage:** a canary filename pushed through the live service scored **0 hits** in journald and the data stores; logs carry format, dimensions and counts only. **Scan restoration is NON-GENERATIVE by construction** — dust/scratch removal, age-cast correction, CLAHE fade recovery and Wiener deconvolution contain no model and no learned prior, so every output pixel derives from input pixels and the operation **cannot produce a face that isn't the person's**; the one op that fills pixels (`descratch`) diffuses *surrounding* pixels into a speck-sized hole and is size-capped so it removes dust, not eyes. Measured on a simulated aged scan: PSNR 14.9→21.1 dB, colour cast halved, contrast recovered to within 1% of the true original. Restoration is claimed **deterministically** — left to the tool picker the model invented a procedure (*"Stack-chan will use her camera… this typically takes a few minutes"*) for an operation that uses the loaded photo and takes 0.3 s | `modules/apelles.py` (`identity_refusal`, `blocked_request`, `probe`, `export`, `edit_file` re-stat, `capabilities`/`require`, `alpha_matte` local u2net), `agent/server.py` (pre-routing refusal + fail-closed capability gate, gate-before-edit, allowlisted batch roots, no route accepts a URL), `static/panel.html` (EXIF disclosure, capability list with reasons) |
| **Morpheus** (image gen) | Harm — generated imagery | Permanent content-safety floor (strict content profile); refuses disallowed prompts | `modules/morpheus_floor.py`, `modules/content_profiles/strict.py` |
| **Photo tools** (`take_photo` / `describe_view`) | Privacy — the camera | **Explicit-ask only** (never autonomous); every capture **announced** and **logged to Argus**; frames never leave Nyx | `agent/server.py` photo endpoints + `argus_store` logging; `modules/vision_module.py` |
| **Dio native photo loop** | Privacy — Dio's camera | Her camera → her own screen → described aloud; captures stay local; authenticated POST only | `modules/vision_module.py` (+ `dio_host` guard, below) |
| **`dio_host` anti-spoof** | Integrity — camera host can't be hijacked | A host claimed by a device is **verified** (`:8080/cam/status` probe) before it's adopted as `dio_host`; a rogue client on the shared network can't redirect the camera | `modules/vision_module.py:try_set_dio_host` |
| **STT hallucination gate** | Truth — silence must not become words | Silence / Whisper-hallucination captures are **discarded, not transcribed**; a `.discarded` sidecar is kept **for the audit** (nothing is hidden) | `modules/captures.py` (pre/post-Whisper gate) |
| **Language & voice** | Truth + safety + consistency | Safety holds in every language (above); the response-language directive lives in the **system-prompt layer, never the soul**; **Alba is the invariant English default**, never assigned to another language; a language with no quality voice is **text-only by declared design** (never silent-by-surprise), and no wrong-accent model ships (honest-gap) | `modules/voices.py`, `modules/tts_module.py`, `config/voices.yaml` |
| **Voice registry gate** | Integrity — no half-defined voice | A voice missing `display_name` or `sample_text` **fails the synth check** (fails install, not render); new voices are **reviewed by ear** before they reach the picker; models are **hash-pinned** on install | `modules/voices.py` (review gate), `setup.sh` (sha256 pins) |
| **Argus** (fleet watchtower) | Privacy + scope creep | **Read-only** observability — no mutation of fleet data; **authenticated** like every route; its own dedicated SQLite (**never** Mnemosyne); captures/chats are viewable but stay local | `modules/argus.py` (*"read-only fleet observability store"*, `argus.db` — NOT mnemosyne.db) |
| **Cybersec / network modules** | Harm — dual-use tooling | Defensive tools, **own-network-only**; scans and OS-detection are for networks you own or have permission to scan | Responsible Use (README); `modules/network_module.py`, `modules/cybersec_module.py` |
| **Metis** (web search) | The highest-stakes surface: first EGRESS + first UNTRUSTED-INPUT ingestion + fabrication risk + SSRF | **Deliberate, visible, minimal.** Egress master switch, **default OFF** (`/egress`); every search **announced** with the query shown. Fetched web content is UNTRUSTED DATA: the summarize pass runs with **NO tools** (a page saying "take a photo" can't fire one — verified), wrapped in delimiters, safety-floored on query AND summary. **Fabrication is structurally impossible for search-intent:** those queries are force-routed server-side (fail-closed — no retrieval → honest "couldn't complete", never a made-up answer), and citations are built server-side from the ACTUAL result URLs (the model's URLs are stripped). SSRF guard refuses non-http(s) and any private/loopback/tailnet/Nyx address. Rate cap; loud-on-broken; **no separate search log** (the chat transcript is the only record). SearXNG is localhost-only, never Funnel-exposed. | `modules/metis.py` + `agent/server.py` (`_tool_web_search`, `_summarize_untrusted`, forced-routing intercept, input-gate); SearXNG container (localhost) |
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

## How to use this trail

- **Adding a capability?** Add its row *before* it ships. If you can't name the
  value at stake and the guardrail, the design isn't finished.
- **Auditing?** Each row is a claim with a code location — verify the guardrail is
  still there, not just that the feature works.
- **The rule of thumb:** anything that reads the room (camera, mic), speaks for
  her (TTS, chat), remembers (memory, captures, chats), or reaches the network is
  a values decision, not just a feature.
