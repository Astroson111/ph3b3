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

## How to use this trail

- **Adding a capability?** Add its row *before* it ships. If you can't name the
  value at stake and the guardrail, the design isn't finished.
- **Auditing?** Each row is a claim with a code location — verify the guardrail is
  still there, not just that the feature works.
- **The rule of thumb:** anything that reads the room (camera, mic), speaks for
  her (TTS, chat), remembers (memory, captures, chats), or reaches the network is
  a values decision, not just a feature.
