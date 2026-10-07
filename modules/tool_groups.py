"""Which tools ride on THIS turn — chosen deterministically, never by the model.

THE MEASUREMENT THAT MADE THIS NECESSARY. On 2026-10-04, against ph3b3-chat on
Ollama 0.24.0, the 105 tool schemas cost **9,010 prompt tokens** of a 16,384
window, measured by prompt_eval_count with and without the `tools` key. Her soul
is ~1,900 more, so ~10,900 tokens were spent before a word of conversation and
~5,450 were left for history, any inlined story, and the reply itself.

That is not merely wasteful. Ollama does not refuse an over-long prompt: it
discards the START of it and reports done_reason 'stop'. Verified the same day —
a secret planted at the head of a 1,500-token system message with num_ctx=512
was simply gone, silently. The first thing thrown away is her system prompt. So
schema bloat does not cost tokens, it costs her character and her memory of the
conversation, with no error anywhere.

DETERMINISTIC, AND NEVER THE MODEL'S CHOICE. Exposure is decided by UI state and
by explicit trigger phrases, before the request is built. Asking a model which
tools it should be shown would hand it the one decision it is least able to make
honestly, and would be unauditable besides.

MENTION IS NOT A REQUEST. "I did a web search yesterday" must not load the web
group. Capability words appear in ordinary talk about the past constantly, and a
keyword match cannot tell the difference — so a narration veto runs first, and
while it holds, no phrase trigger fires at all. UI state is unaffected: a photo
really is open or it is not.

UNKNOWN TOOLS ARE EXPOSED, NOT HIDDEN. A tool added later and not yet grouped
falls into the always-on set. The cost of that is tokens; the cost of the other
direction is a capability that silently stops working, and a Phoebe who says she
cannot do something she can. `ungrouped()` plus its test is how a new tool gets
grouped on purpose instead of by accident.

SELF-KNOWLEDGE IS NOT AFFECTED. Nothing here is consulted by the capability
block she answers from — that reads live config, so "can you search the web?"
is answered from whether egress is on, not from whether this turn happened to
load the group. One voice; a group that is not loaded is not a capability she
lacks.
"""
import logging
import re

log = logging.getLogger("ph3b3.tool_groups")

# ── Always on ────────────────────────────────────────────────────────────────
# Deliberately small, and chosen by what an ordinary turn reaches for without
# announcing itself: the time, the weather, her memory, a note, a timer, a joke.
# Vision is in here on purpose — "can you see me?" is an everyday question and
# an unrouted vision ask once had her claiming sight with zero captures. The
# camera switch still removes these when there is no camera.
# WRITERS STAY, READERS DO NOT (2026-10-04, after the battery).
#
# The first version of this set kept recall, recall_memory, search_notes and
# web_search in core, and the battery caught what that did: asked "what is the
# capital of Peru?" she chained recall_memory -> web_search -> recall_memory,
# three passes out of three, where the baseline reached for a tool once in three.
#
# The cause is the change itself. web_search went from one option in 111 to one
# in 29, and a small menu makes everything on it more salient — cutting exposure
# does not just save tokens, it raises the odds of whatever is left being
# chosen. So retrieval now needs asking for, and only the WRITE side is always
# available: failing to store something the user asked her to remember is worse
# than a wasted token, while an unnecessary lookup is a wrong answer dressed up
# as a sourced one.
CORE = frozenset({
    "get_time", "weather_current",
    "remember", "remember_fact", "add_note", "read_last_note",
    "add_reminder", "list_reminders", "start_timer", "pomodoro",
    "tell_joke", "roast", "speak",
    "system_status", "fleet_status",
    "look", "describe_view", "take_photo",
})

# ── Groups ───────────────────────────────────────────────────────────────────
GROUPS: dict[str, frozenset[str]] = {
    # Only meaningful with a photo open; 4,880 chars of schema between the first
    # three alone, which is 11% of the whole table.
    "photo": frozenset({
        "edit_photo", "export_photo", "run_photo_batch", "convert_photo",
        "upscale_photo", "photo_capabilities", "analyze_screenshot",
    }),
    "resume": frozenset({
        "build_ats_resume", "analyze_resume", "draft_resume_section",
        "extract_job_posting", "match_candidate_to_job", "profile_get",
        "profile_add_certification", "profile_add_experience",
        "profile_add_note", "profile_add_project", "profile_add_skill",
    }),
    "network": frozenset({
        "network_arp_scan", "network_dig", "network_my_ip",
        "network_netdiscover", "network_nmap_expand", "network_scan",
        "network_speedtest", "network_tools_menu", "network_traceroute",
        "network_who_is_on", "dns_records", "whois", "ssl_check",
        "restore_scan",
    }),
    "security": frozenset({
        "cve_lookup", "check_password_breach", "check_identity_exposure",
        "analyze_scam", "cybersec_study", "hash_string",
    }),
    "ghost": frozenset({
        "investigation_start", "investigation_end", "investigation_status",
        "investigation_log_emf", "investigation_log_evp", "set_baseline",
        "check_anomaly", "weather_ghost_hunting", "start_evening_capture",
        "stop_evening_capture", "start_monitoring", "last_capture",
        "listen", "analyze_camera", "log_anomaly",
    }),
    "media": frozenset({
        "spotify_play", "spotify_control", "spotify_now_playing",
        "film_lookup", "anime_lookup", "anime_random",
        "list_singers", "list_songs", "song_status",
        "generate_song", "generate_video",
    }),
    "stories": frozenset({
        "add_story", "file_story", "read_shelf_story", "retell_story",
        "recall_stories",
    }),
    "lookup": frozenset({
        "dnd_lookup", "occult_lookup", "occult_random", "find_recipe",
        "read_document", "calendar_today", "calendar_week",
    }),
    "machine": frozenset({
        "gpu_status", "free_gpu", "ollama_status", "backup_status",
        "bluetooth_scan", "bluetooth_status",
    }),
    # These two are appended to TOOLS at import (`TOOLS += ATALANTA_TOOLS`,
    # `TOOLS += CAMERA_TOOLS`) rather than written in the literal, so a reader
    # that parses only the literal does not see them — mine did not, and the
    # live log said "29/111 advertised" when the measurement said 23 of 105.
    # Caught by the running system, not by the test, which is the wrong way
    # round; the test now builds the table the same way the server does.
    "sports": frozenset({"get_scores", "get_standings", "get_schedule"}),
    # Retrieval, moved out of core — see the CORE comment above.
    "memory": frozenset({"recall", "recall_memory", "search_notes"}),
    "web": frozenset({"web_search"}),
    # OUT OF CORE (2026-10-07). translate_text sat here and was chosen for "say
    # thank you for the support on TikTok" — five calls, text to Google. The
    # offline replacement loads only when translation is actually asked for.
    "translate": frozenset({"translate_offline"}),
    # Pan/tilt/zoom CONTROL. Plain seeing — look, describe_view, take_photo —
    # stays in core, because "can you see me?" is an everyday question and an
    # unrouted vision ask once had her claiming sight with no captures at all.
    "camera_ctl": frozenset({"camera_status", "camera_move", "camera_reset"}),
}

# ── The narration veto ───────────────────────────────────────────────────────
# Runs BEFORE any phrase trigger and suppresses all of them. These are the
# shapes in which a capability gets TALKED ABOUT rather than asked for, and the
# brief names the case directly: "I did a web search yesterday" must not fire
# the web group.
#
# Past tense alone is not enough ("did you scan the network?" is a request about
# a past act and should still load the group), so the veto needs a first-person
# or past-time frame — the speaker describing what THEY did, or when.
_NARRATION = re.compile(
    r"\b(?:"
    r"i|we)\s+(?:just\s+|already\s+|once\s+)?"
    r"(?:did|ran|used|made|tried|had|took|was|were|been|searched|scanned|"
    r"looked|checked|asked|told|showed|read|played|generated|built)\b"
    r"|\b(?:yesterday|last\s+(?:night|week|month|year|time)|earlier|"
    r"the\s+other\s+day|a\s+while\s+(?:ago|back)|back\s+then)\b",
    re.I)

# ── Phrase triggers ──────────────────────────────────────────────────────────
# Word-boundary anchored. A group loads when the message is plausibly ASKING for
# that territory. These are deliberately generous inside their own subject —
# a missed trigger is a routing gap we log and tune, not a silent failure.
TRIGGERS: dict[str, re.Pattern] = {
    "photo": re.compile(r"\b(photo|picture|image|crop|resiz\w*|export|"
                        r"watermark|thumbnail|screenshot|upscal\w*)\b", re.I),
    "resume": re.compile(r"\b(resum[eé]|cv|job\s+post\w*|cover\s+letter|"
                         r"applicant|hiring|my\s+experience|certification)\b", re.I),
    "network": re.compile(r"\b(network|nmap|subnet|lan|wifi|router|ip\s+address|"
                          r"dns|whois|traceroute|speedtest|who\s+is\s+on|"
                          r"ssl|certificate|port\s+scan)\b", re.I),
    "security": re.compile(r"\b(cve|vulnerab\w*|breach|pwned|scam|phish\w*|"
                           r"exposure|hash|password\s+(?:leak|breach))\b", re.I),
    "ghost": re.compile(r"\b(ghost|investigation|emf|evp|paranormal|haunt\w*|"
                        r"anomaly|baseline|spirit)\b", re.I),
    "media": re.compile(r"\b(spotify|play\s+(?:some|the|a)?\s*(?:music|song)|"
                        r"song|music|film|movie|anime|album|artist|singer|"
                        r"video\s+clip|make\s+(?:me\s+)?a\s+(?:song|video))\b", re.I),
    "stories": re.compile(r"\b(story|stories|tale|shelf|retell|read\s+me)\b", re.I),
    "lookup": re.compile(r"\b(recipe|cook|d&d|dnd|dungeons|tarot|occult|"
                         r"calendar|schedule|document|pdf)\b", re.I),
    "machine": re.compile(r"\b(gpu|vram|card|ollama|bluetooth|backup|restic|"
                          r"free\s+(?:up\s+)?(?:the\s+)?(?:gpu|card))\b", re.I),
    # Asking her what she KNOWS about the past of this conversation, or about
    # the user — not merely using the word "remember" in passing.
    "memory": re.compile(r"\b(do\s+you\s+remember|remind\s+me|what\s+did\s+i|"
                         r"did\s+i\s+(?:tell|say|mention)|my\s+notes?|"
                         r"recall|earlier\s+i\s+said|we\s+talked\s+about)\b", re.I),
    # Asking her to GO AND LOOK. A factual question she can simply answer is not
    # a search request, which is the whole point of taking this out of core.
    "web": re.compile(r"\b(search|google|look\s+it\s+up|look\s+up|online|"
                      r"on\s+the\s+web|latest\s+news|current\s+price|"
                      r"what'?s\s+happening|headlines)\b", re.I),
    "sports": re.compile(r"\b(score|scores|standings|fixture\w*|league|"
                         r"who\s+won|match|game\s+(?:tonight|today)|"
                         r"schedule\s+for)\b", re.I),
    "translate": re.compile(r"\b(translat\w*|how\s+do\s+(?:you|i)\s+say|"
                            r"in\s+(?:spanish|french|german|italian|portuguese|"
                            r"japanese|chinese|mandarin|korean|russian|arabic))\b",
                            re.I),
    "camera_ctl": re.compile(r"\b(pan|tilt|zoom|point\s+the\s+camera|"
                             r"move\s+the\s+camera|camera\s+(?:left|right|up|"
                             r"down|home|reset|status))\b", re.I),
}

# ── UI state → groups ────────────────────────────────────────────────────────
# A fact about the screen, not a reading of the sentence, so no veto applies.
# Keys are what the client sends; absent keys simply contribute nothing.
UI_GROUPS: dict[str, str] = {
    "photo_open": "photo",
    "document_attached": "resume",
    "investigation_active": "ghost",
}
UI_TABS: dict[str, str] = {
    "apelles": "photo", "photos": "photo",
    "resume": "resume", "kadmos": "resume",
    "network": "network", "metis": "network",
    "ghost": "ghost",
    "amphion": "media", "orpheus": "media",
    "thoth": "stories",
}


# THE VETO CANNOT APPLY TO THE GROUP WHOSE SUBJECT IS THE PAST.
#
# Caught by the tests, 2026-10-04: "do you remember what I told you about the
# shed" is the canonical recall request and it matches the narration veto on
# "I told", so asking her to remember switched the memory tools off.
#
# The veto exists to stop a capability being MENTIONED from loading it. A recall
# request is not a mention of recall — it is a use of it, and it is about the
# past by definition. So memory is exempt, and its own triggers carry the weight
# instead: they are recall-shaped ("do you remember", "what did I", "did I
# tell"), not bare keywords.
VETO_EXEMPT = frozenset({"memory"})


def narrated(text: str) -> bool:
    """True when the message is TALKING ABOUT a capability rather than asking."""
    return bool(text) and bool(_NARRATION.search(text))


def groups_for_turn(text: str = "", ui: dict | None = None) -> set[str]:
    """The groups this turn gets. Deterministic; no model involved."""
    out: set[str] = set()
    ui = ui or {}
    # UI state first and unconditionally — a photo is open or it is not.
    for key, group in UI_GROUPS.items():
        if ui.get(key):
            out.add(group)
    tab = str(ui.get("tab") or "").strip().lower()
    if tab in UI_TABS:
        out.add(UI_TABS[tab])
    # Phrase triggers. The veto suppresses them, except for the groups whose
    # subject matter IS the past — see VETO_EXEMPT.
    if text:
        vetoed = narrated(text)
        for group, rx in TRIGGERS.items():
            if vetoed and group not in VETO_EXEMPT:
                continue
            if rx.search(text):
                out.add(group)
    return out


def exposed_names(all_names, text: str = "", ui: dict | None = None) -> set[str]:
    """Every tool name advertised this turn: core, the live groups, and anything
    not yet grouped (exposed, never hidden — see the module docstring)."""
    all_names = set(all_names)
    keep = set(CORE)
    for g in groups_for_turn(text, ui):
        keep |= GROUPS.get(g, frozenset())
    keep |= ungrouped(all_names)        # fail OPEN on an unclassified tool
    return keep & all_names


def ungrouped(all_names) -> set[str]:
    """Tools in the table that belong to no group and are not core."""
    claimed = set(CORE)
    for names in GROUPS.values():
        claimed |= names
    return set(all_names) - claimed


def group_of(name: str) -> str | None:
    """Which group a tool belongs to — for the routing-gap log line."""
    if name in CORE:
        return "core"
    for g, names in GROUPS.items():
        if name in names:
            return g
    return None
