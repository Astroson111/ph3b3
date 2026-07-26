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

## How to use this trail

- **Adding a capability?** Add its row *before* it ships. If you can't name the
  value at stake and the guardrail, the design isn't finished.
- **Auditing?** Each row is a claim with a code location — verify the guardrail is
  still there, not just that the feature works.
- **The rule of thumb:** anything that reads the room (camera, mic), speaks for
  her (TTS, chat), remembers (memory, captures, chats), or reaches the network is
  a values decision, not just a feature.
