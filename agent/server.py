#!/usr/bin/env python3
import asyncio
import base64
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime
import json
import logging
import os
import secrets
import sys
import tempfile
import threading
import time
import wave as _wave
from pathlib import Path
import httpx
import getpass
import shutil
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
import uuid
from io import BytesIO
from PIL import Image  # Morpheus edit-mode upload validation / re-encode
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn
from dotenv import load_dotenv, set_key
import mnemosyne
from memory_spine import MemorySpine

load_dotenv()

ROOT = Path(__file__).parent.parent
SOUL_FILE = ROOT / "soul" / "soul.md"
MODULES_DIR = ROOT / "modules"
SKILL_LOG = Path.home() / "ph3b3_data" / "skills" / "skill_log.jsonl"
SKILL_LOG.parent.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path.home() / "ph3b3_data"
_SETUP_COMPLETE_FILE = DATA_DIR / "setup_complete"
_SETUP_COMPLETE = _SETUP_COMPLETE_FILE.exists()

AUTH_USER = os.getenv("PH3B3_USER", "admin")
AUTH_PASS = os.getenv("PH3B3_PASSWORD", "")
if not _SETUP_COMPLETE and not AUTH_PASS:
    logging.info("Ph3b3 first-run mode — /setup is open, all other routes gated.")
elif not AUTH_PASS:
    logging.error("PH3B3_PASSWORD not set in .env — all requests will be refused until it is configured")

_SESSION_COOKIE = "ph3b3_session"
_SESSION_MAX_AGE = 86400 * 7          # 7 days
_sessions: dict[str, str] = {}        # token → username (in-memory; resets on restart)

OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
HEAVY_MODEL  = os.getenv("PH3B3_HEAVY_MODEL", os.getenv("PH3B3_MODEL", "hermes3:latest"))
LIGHT_MODEL  = os.getenv("PH3B3_LIGHT_MODEL", "hermes3:latest")
MODEL        = HEAVY_MODEL  # legacy alias kept for health endpoint and backward compat
HOST = os.getenv("PH3B3_HOST", "0.0.0.0")
PORT = int(os.getenv("PH3B3_PORT", "7331"))
SSL_CERT = os.getenv("PH3B3_SSL_CERT", "")
SSL_KEY  = os.getenv("PH3B3_SSL_KEY",  "")
_scheme  = "https" if (SSL_CERT and SSL_KEY) else "http"

_raw_origins = os.getenv(
    "PH3B3_ALLOWED_ORIGINS",
    f"{_scheme}://localhost:{PORT},{_scheme}://127.0.0.1:{PORT}",
)
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

RECIPE_DB_PATH          = os.getenv("RECIPE_DB_PATH", str(Path.home() / "ph3b3_data" / "recipes.db"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Ph3b3] %(message)s")
log = logging.getLogger("ph3b3")

LIGHT_TOOLS = frozenset({
    "weather_current", "weather_ghost_hunting",
    "start_timer", "pomodoro",
    "tell_joke", "roast",
    "add_reminder", "list_reminders",
    "calendar_today", "calendar_week",
    "spotify_play", "spotify_control", "spotify_now_playing",
    "network_my_ip", "network_speedtest", "network_tools_menu",
    "system_status", "gpu_status", "ollama_status",
    "recall_memory", "remember_fact",
    "bluetooth_scan", "bluetooth_status",
    "add_note", "read_last_note", "search_notes",
})

def _select_model(called: set) -> str:
    """Return LIGHT_MODEL when all called tools are lightweight; HEAVY_MODEL otherwise."""
    if called and called.issubset(LIGHT_TOOLS):
        return LIGHT_MODEL
    return HEAVY_MODEL

def load_soul():
    if not SOUL_FILE.exists():
        return "You are Ph3b3, a local AI assistant. Be warm, precise, and loyal."
    soul = SOUL_FILE.read_text(encoding="utf-8")
    log.info(f"Soul loaded: {len(soul)} chars")
    return soul

sys.path.insert(0, str(MODULES_DIR))

from spotify_module import SpotifyModule
from dnd_module import DnDModule
from film_module import FilmModule
from translation_module import TranslationModule
from memory_module import MemoryModule
from wake_gate import wake_match
from tts_chunker import split_for_tts
from occult_module import OccultModule
from jokes_module import JokesModule
from vision_module import VisionModule
from search_module import SearchModule
from tts_module import TTSModule, trim_silence_b64
from stt_module import STTModule
from anime_module import AnimeModule
from stories_module import StoriesModule
from notes_module import NotesModule
from timer_module import TimerModule
from reminders_module import RemindersModule
from calendar_module import CalendarModule
from weather_module import WeatherModule
from resume_module import ResumeModule
from network_module import NetworkModule
from bluetooth_module import BluetoothModule
from system_module import SystemModule
from cybersec_module import CybersecModule
from scam_detector import ScamDetector
from investigation_module import InvestigationModule
# VisionStreamModule retired 2026-07-16 — it used a local OBSBOT (/dev/video0);
# vision is Stack-Chan-only now (frames come from Dio via /vision/frame).
from screenshot_module import ScreenshotModule
from recipes import RecipeStore
import morpheus
from triage import triage_gate   # clarification guard before main inference

# ── Dio state telemetry (UDP) ────────────────────────────────────────────────
# Dio's serial is dead, so its state machine is invisible on-device. It fires
# fire-and-forget UDP pings on each transition; log them here so the flow
# (idle→armed→capturing→endpointed→sent→resp len=N→playing→idle) is greppable
# in the journal (grep DIO_STATE). Temporary diagnostic instrumentation.
class _DioStateProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        log.info("DIO_STATE %s (from %s)", data.decode("utf-8", "replace").strip(), addr[0])


@asynccontextmanager
async def lifespan(app):
    memory.confirm_boot()
    boot_count = memory.memory.get("boot_count", 1)
    greetings = [
        "Soul online.",
        "Awakening. I'm here.",
        "Systems initialised. Ready when you are.",
        "Online. Watching. Listening.",
        "Active. What do you need?",
    ]
    text = greetings[(boot_count - 1) % len(greetings)] + " Made with Soul, baby."
    log.info(f"Boot greeting (#{boot_count}): {text}")
    def _greet():
        time.sleep(4)  # wait for ALSA to be ready under systemd
        tts.speak(text, blocking=False)
        reminder_msg = reminders.on_boot()
        if reminder_msg:
            tts.speak(reminder_msg, blocking=False)
    threading.Thread(target=_greet, daemon=True).start()
    mnemosyne.init(os.getenv("JAMENDO_CLIENT_ID", ""))
    log.info("Mnemosyne online")

    async def _edit_scratch_janitor():
        # Bound edit-mode scratch to the TTL even when no new uploads arrive.
        while True:
            await asyncio.sleep(_EDIT_SCRATCH_TTL)
            n = await asyncio.to_thread(_edit_scratch_sweep)
            if n:
                log.info(f"[edit] scratch janitor removed {n} stale upload(s)")
    _janitor = asyncio.create_task(_edit_scratch_janitor())

    _dio_state_transport = None
    try:
        _loop = asyncio.get_running_loop()
        _dio_state_transport, _ = await _loop.create_datagram_endpoint(
            _DioStateProtocol, local_addr=("0.0.0.0", 7332))
        log.info("Dio state telemetry listening on udp/7332")
    except Exception as e:
        log.warning("Dio state listener failed to bind udp/7332: %s", e)

    yield
    if _dio_state_transport is not None:
        _dio_state_transport.close()
    _janitor.cancel()
    if _ec_mod._session and _ec_mod._session.is_running():
        _ec_mod.tool_stop_evening_capture()

app = FastAPI(title="Ph3b3 Agent", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

@app.middleware("http")
async def basic_auth(request: Request, call_next):
    # CORS preflights — let CORSMiddleware handle these.
    if request.method == "OPTIONS":
        return await call_next(request)

    # First-run gate: /setup and /static are the only open paths until setup is complete.
    if not _SETUP_COMPLETE:
        p = request.url.path
        if p == "/setup" or p.startswith("/static"):
            return await call_next(request)
        return RedirectResponse(url="/setup", status_code=303)

    # Login / logout pages are public.
    if request.url.path in ("/login", "/logout"):
        return await call_next(request)

    if not AUTH_PASS:
        return Response(
            content="Ph3b3 is not configured for access — set PH3B3_PASSWORD in .env",
            status_code=503,
        )

    authed = False

    # 1. Session cookie — browser clients that went through /login.
    token = request.cookies.get(_SESSION_COOKIE, "")
    if token and token in _sessions:
        authed = True

    # 2. HTTP Basic Auth — curl / device / API clients.
    if not authed:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Basic "):
            try:
                creds = base64.b64decode(auth_hdr[6:]).decode("utf-8", errors="replace")
                user, _, pw = creds.partition(":")
                if (secrets.compare_digest(user.encode(), AUTH_USER.encode()) and
                        secrets.compare_digest(pw.encode(), AUTH_PASS.encode())):
                    authed = True
            except Exception:
                pass

    if not authed:
        # Browser requests (Accept: text/html) → redirect to login page.
        if "text/html" in request.headers.get("Accept", ""):
            return RedirectResponse(url="/login", status_code=303)
        # API / device clients → plain 401.
        # No WWW-Authenticate: device clients (Iris, Stack-Chan, curl -u) send
        # Basic auth proactively and never need the challenge header.
        # Sending it would trigger Firefox's native Basic Auth dialog for any
        # unauthenticated JS fetch from the panel — the "second auth screen."
        return Response(content="Unauthorized", status_code=401)

    device = request.headers.get("X-Ph3b3-Device", "unidentified")
    _device_roster[device] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Learn Dio's LAN IP from her calls so vision can reach her camera (Phase 2).
    # Part C: only adopt a NEW IP after verifying it actually runs Dio's camera
    # server — a spoofed X-Ph3b3-Device header from any authed LAN client must
    # not be able to hijack dio_host. Verify off the loop; skip when unchanged.
    if device == "stackchan" and request.client and request.client.host != vision.dio_host:
        await asyncio.to_thread(vision.try_set_dio_host, request.client.host)
    return await call_next(request)

spotify = SpotifyModule()
dnd = DnDModule(ROOT / "config" / "dnd_db.json")
film = FilmModule(ROOT / "config" / "film_db.json")
translation = TranslationModule()
memory = MemoryModule()
mem_spine = MemorySpine()   # Mnemosyne — shared cross-device semantic memory (served at /mnemosyne/*)
# Read-side auto-recall: how many memories to pull per turn, and the cosine floor
# below which a hit is treated as noise (in testing, relevant≈0.34 vs noise≈0.09).
MNEMO_RECALL_K = 3
MNEMO_RECALL_THRESHOLD = 0.30
occult = OccultModule()
jokes = JokesModule()
vision = VisionModule(memory_module=memory)   # Stack-Chan only — frames come from Dio
search = SearchModule()
tts = TTSModule()
stt = STTModule()
anime = AnimeModule()
stories = StoriesModule()
notes = NotesModule()
timer = TimerModule()
reminders = RemindersModule()
calendar = CalendarModule()
weather = WeatherModule()
resume = ResumeModule()
network = NetworkModule()
bluetooth = BluetoothModule()
system = SystemModule()
cybersec = CybersecModule()
scam_detector = ScamDetector()
investigation = InvestigationModule()
screenshot = ScreenshotModule()
recipe_store = RecipeStore(RECIPE_DB_PATH)
# Argus — read-only fleet observability. Ingest rides the verified check-in path
# (this endpoint records; the argus-daemon writes self-heartbeats + prunes).
from argus import ArgusStore, load_contracts, iso as _argus_iso
argus_store = ArgusStore()
from captures import CapturesFeed, CAPTURES_DIR as _CAPTURES_DIR   # read-only artifact feed (Argus Part 2)
captures_feed = CapturesFeed()
from chats import ChatLog                                          # per-session chat transcripts (Argus Chats)
chat_log = ChatLog()
import evening_capture as _ec_mod
_ec_mod.alba_say = lambda t: _tts_announce(t)

def _tts_announce(text: str) -> None:
    try:
        tts.speak(text, blocking=False)
    except Exception:
        pass

# _IDENTITY_DIRECTIVE was removed: putting "You are Ph3b3" after the template's
# "You are a function calling AI model" created two conflicting identity claims that
# confused the 8B model into meta-conversation mode instead of calling tools.
# The soul's own first-person voice asserts identity without the conflict.
_SEARCH_NUDGE = (
    "\n\nFor any query involving current events, recent news, prices, scores, schedules, "
    "weather, or anything that changes over time — use your tools first. "
    "Do not answer from training memory when real-time data is available via a tool."
)
SYSTEM_PROMPT = load_soul() + _SEARCH_NUDGE + memory.as_context()

TOOLS = [
    {"type":"function","function":{"name":"spotify_play","description":"Play music on Spotify","parameters":{"type":"object","properties":{"query":{"type":"string"},"type":{"type":"string","default":"track"}},"required":["query"]}}},
    {"type":"function","function":{"name":"spotify_control","description":"Control Spotify playback","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["pause","resume","skip","previous","shuffle_on","shuffle_off"]}},"required":["action"]}}},
    {"type":"function","function":{"name":"spotify_now_playing","description":"Get currently playing track","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"dnd_lookup","description":"Look up D&D rules spells monsters lore","parameters":{"type":"object","properties":{"query":{"type":"string"},"category":{"type":"string","default":"any"},"edition":{"type":"string","default":"5e"}},"required":["query"]}}},
    {"type":"function","function":{"name":"film_lookup","description":"Look up obscure films or get recommendations","parameters":{"type":"object","properties":{"query":{"type":"string"},"mode":{"type":"string","default":"lookup"}},"required":["query"]}}},
    {"type":"function","function":{"name":"translate_text","description":"Translate text to any language using Google Translate (requires internet). Source language is auto-detected.","parameters":{"type":"object","properties":{"text":{"type":"string"},"target_lang":{"type":"string","description":"Target language code, e.g. 'es' for Spanish, 'ja' for Japanese, 'fr' for French"}},"required":["text","target_lang"]}}},
    {"type":"function","function":{"name":"remember_fact","description":"Remember a fact permanently","parameters":{"type":"object","properties":{"key":{"type":"string"},"value":{"type":"string"}},"required":["key","value"]}}},
    {"type":"function","function":{"name":"log_anomaly","description":"Log a detected anomaly","parameters":{"type":"object","properties":{"description":{"type":"string"},"source":{"type":"string","default":"camera"}},"required":["description"]}}},
    {"type":"function","function":{"name":"recall_memory","description":"Search long-term memory","parameters":{"type":"object","properties":{"topic":{"type":"string"}},"required":["topic"]}}},
    {"type":"function","function":{"name":"remember","description":"Save a memory to Mnemosyne — Ph3b3's shared long-term memory that is visible across ALL devices (Iris, Dio, Nyx) and survives restarts. Use for anything worth recalling later: facts about the user, ongoing state, observations, or notable moments in conversation. Prefer this over remember_fact for free-form memories.","parameters":{"type":"object","properties":{"text":{"type":"string","description":"The memory to store, in natural language"},"kind":{"type":"string","enum":["conversation","fact","state","observation"],"default":"conversation","description":"conversation=dialogue, fact=stable truth, state=progress/status, observation=noticed event"}},"required":["text"]}}},
    {"type":"function","function":{"name":"recall","description":"Semantic search across Mnemosyne — Ph3b3's shared cross-device long-term memory. Returns the most relevant memories from ANY device by meaning, not keywords. Use when the user refers to something from earlier, asks what you remember, or you need prior context to answer well.","parameters":{"type":"object","properties":{"query":{"type":"string"},"top_k":{"type":"integer","default":5}},"required":["query"]}}},
    {"type":"function","function":{"name":"occult_lookup","description":"Look up paranormal phenomena or folklore","parameters":{"type":"object","properties":{"query":{"type":"string"},"category":{"type":"string","default":"any"}},"required":["query"]}}},
    {"type":"function","function":{"name":"occult_random","description":"Random paranormal fact for stream","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"tell_joke","description":"Tell a joke","parameters":{"type":"object","properties":{"category":{"type":"string","default":"any"}}}}},
    {"type":"function","function":{"name":"roast","description":"Deliver a roast for stream","parameters":{"type":"object","properties":{"topic":{"type":"string","enum":["dnd","security"]}},"required":["topic"]}}},
    {"type":"function","function":{"name":"look","description":"CALL THIS TOOL immediately whenever the user says: look, see, watch, observe, take a picture, take a photo, what do you see, what can you see, what's in the room, what's around you, describe your surroundings, are you watching, can you see, look around, peek, what's happening, what do you notice, or ANY request involving vision or sight. This captures a live frame from Dio's (Stack-Chan's) own camera right now and analyzes it. NEVER refuse a visual request — call this tool and report exactly what it returns. If Dio is offline the tool says so; relay that, don't invent a reason you can't see.","parameters":{"type":"object","properties":{"prompt":{"type":"string","description":"What to focus on or look for (optional)"}}}}},
    {"type":"function","function":{"name":"set_baseline","description":"GHOST-HUNTING ONLY (requires an active investigation): capture the current camera view as the 'normal' baseline for anomaly detection. Refuses outside an investigation. For a plain look, use 'look'.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"check_anomaly","description":"GHOST-HUNTING ONLY (requires an active investigation): compare the live camera to the baseline and flag motion. Refuses outside an investigation.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"start_monitoring","description":"GHOST-HUNTING ONLY (requires an active investigation): begin background camera anomaly monitoring on a timer. This is the only vision path that looks WITHOUT a fresh prompt, so it is gated to an active investigation and stops when it ends. Refuses otherwise.","parameters":{"type":"object","properties":{"interval":{"type":"integer","default":30}}}}},
    {"type":"function","function":{"name":"web_search","description":"Search the web for current information. CALL THIS for: current events, news, recent/latest anything, prices, scores, schedules, weather forecasts, product releases, politics, tech news, or any question where the answer may have changed since training. Use type='news' for breaking news. Never answer time-sensitive questions from memory when this tool is available.","parameters":{"type":"object","properties":{"query":{"type":"string"},"type":{"type":"string","default":"search"}},"required":["query"]}}},
    {"type":"function","function":{"name":"speak","description":"Speak text aloud using Piper TTS","parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}},
    {"type":"function","function":{"name":"listen","description":"Listen via microphone using Whisper","parameters":{"type":"object","properties":{"duration":{"type":"integer","default":10}}}}},
    {"type":"function","function":{"name":"anime_lookup","description":"Look up anime or get recommendations","parameters":{"type":"object","properties":{"query":{"type":"string"},"mode":{"type":"string","default":"lookup"}},"required":["query"]}}},
    {"type":"function","function":{"name":"anime_random","description":"Random anime recommendation","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"add_story","description":"Save a story told to Ph3b3","parameters":{"type":"object","properties":{"name":{"type":"string"},"story":{"type":"string"}},"required":["name","story"]}}},
    {"type":"function","function":{"name":"recall_stories","description":"Recall stories by topic","parameters":{"type":"object","properties":{"topic":{"type":"string"}}}}},
    {"type":"function","function":{"name":"add_note","description":"Save a quick note","parameters":{"type":"object","properties":{"content":{"type":"string"},"tag":{"type":"string","default":"general"}},"required":["content"]}}},
    {"type":"function","function":{"name":"read_last_note","description":"Read the most recent note","parameters":{"type":"object","properties":{"tag":{"type":"string"}}}}},
    {"type":"function","function":{"name":"search_notes","description":"Search notes","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"start_timer","description":"Set a named timer","parameters":{"type":"object","properties":{"name":{"type":"string"},"seconds":{"type":"integer"}},"required":["name","seconds"]}}},
    {"type":"function","function":{"name":"pomodoro","description":"Start a Pomodoro timer","parameters":{"type":"object","properties":{"minutes":{"type":"integer","default":25}}}}},
    {"type":"function","function":{"name":"add_reminder","description":"Add a persistent reminder","parameters":{"type":"object","properties":{"text":{"type":"string"},"when":{"type":"string"},"tag":{"type":"string","default":"general"}},"required":["text"]}}},
    {"type":"function","function":{"name":"list_reminders","description":"List pending reminders","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"calendar_today","description":"Get today calendar events","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"calendar_week","description":"Get this weeks calendar","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"weather_current","description":"Get current weather","parameters":{"type":"object","properties":{"location":{"type":"string"}}}}},
    {"type":"function","function":{"name":"weather_ghost_hunting","description":"Weather field notes for ghost hunting","parameters":{"type":"object","properties":{"location":{"type":"string"}}}}},
    {"type":"function","function":{"name":"extract_job_posting","description":"Analyze a job posting from a URL or pasted text. Returns structured breakdown: job title, company, location, salary (only if stated — never hallucinated), hard requirements, soft requirements, red flags, culture signals, and a one-line verdict. Use whenever the user shares a job link or pastes a job description.","parameters":{"type":"object","properties":{"source":{"type":"string","description":"A URL to the job posting page, or the full pasted text of the posting"}},"required":["source"]}}},
    {"type":"function","function":{"name":"profile_get","description":"Read the candidate's full stored profile: skills, experience, certifications, projects, notes. Call this before match_candidate_to_job to confirm the profile has data.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"profile_add_skill","description":"Add one or more skills to the candidate profile. Accepts a single skill name or a comma-separated list.","parameters":{"type":"object","properties":{"skill":{"type":"string","description":"Skill name or comma-separated list of skills"}},"required":["skill"]}}},
    {"type":"function","function":{"name":"profile_add_experience","description":"Add a work experience entry to the candidate profile.","parameters":{"type":"object","properties":{"role":{"type":"string"},"org":{"type":"string"},"duration":{"type":"string"},"bullets":{"type":"array","items":{"type":"string"}}},"required":["role","org"]}}},
    {"type":"function","function":{"name":"profile_add_certification","description":"Add a certification to the candidate profile.","parameters":{"type":"object","properties":{"name":{"type":"string"},"issuer":{"type":"string"},"year":{"type":"integer"}},"required":["name"]}}},
    {"type":"function","function":{"name":"profile_add_project","description":"Add a project to the candidate profile.","parameters":{"type":"object","properties":{"name":{"type":"string"},"description":{"type":"string"},"tech":{"type":"array","items":{"type":"string"}},"bullets":{"type":"array","items":{"type":"string"}}},"required":["name"]}}},
    {"type":"function","function":{"name":"profile_add_note","description":"Add a free-text note to the candidate profile — preferences, constraints, target role, salary floor, anything that should inform application strategy.","parameters":{"type":"object","properties":{"note":{"type":"string"}},"required":["note"]}}},
    {"type":"function","function":{"name":"match_candidate_to_job","description":"Match the stored candidate profile against a job analysis produced by extract_job_posting. Returns: match score (hard reqs met/total), gap analysis per requirement, application angle suggestion, tailored resume bullets, and a WORTH APPLYING/STRETCH/SKIP verdict. Always verify profile_get has data before calling.","parameters":{"type":"object","properties":{"job_analysis":{"type":"string","description":"The full structured text output from extract_job_posting"}},"required":["job_analysis"]}}},
    {"type":"function","function":{"name":"draft_resume_section","description":"Draft a single polished resume bullet in action-verb, achievement-framed format for a specific job requirement, drawing from a candidate profile entry. No fluff, no filler, no invented metrics.","parameters":{"type":"object","properties":{"requirement":{"type":"string","description":"The specific job requirement to address"},"profile_entry":{"type":"string","description":"The relevant candidate experience, project, or skill to draw from"}},"required":["requirement","profile_entry"]}}},
    {"type":"function","function":{"name":"analyze_resume","description":"Analyze a pasted plain-text resume for ATS-readiness: parse-cleanliness score, formatting red flags, section completeness, and (if a job description is provided) the keyword gap split into GROUNDED (skill the resume shows under other words) vs UNSUPPORTED (no evidence — must be earned, never auto-added). Use when the user pastes their resume text and asks for a review/ATS check.","parameters":{"type":"object","properties":{"resume_text":{"type":"string","description":"The full plain-text resume the user pasted"},"job_description":{"type":"string","description":"Optional job description text to compute the keyword gap against"}},"required":["resume_text"]}}},
    {"type":"function","function":{"name":"build_ats_resume","description":"Rebuild a pasted resume as an ATS-safe .docx (single column, standard headers, plain bullets, no tables). Auto-inserts ONLY grounded keywords (each tied to a real line in the resume); unsupported keywords are reported, never inserted. Returns a before/after diff (the approval surface) plus a download link. Use when the user wants the cleaned/aligned resume file, not just analysis.","parameters":{"type":"object","properties":{"resume_text":{"type":"string","description":"The full plain-text resume the user pasted"},"job_description":{"type":"string","description":"Optional job description text to align grounded keywords against"}},"required":["resume_text"]}}},
    {"type":"function","function":{"name":"network_my_ip","description":"Get the host machine's IP addresses","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"network_scan","description":"Scan the local network","parameters":{"type":"object","properties":{"target":{"type":"string","default":"192.168.0.0/24"}}}}},
    {"type":"function","function":{"name":"network_who_is_on","description":"Who is on the network right now","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"network_arp_scan","description":"List all LAN devices with IP, MAC address, and vendor using arp-scan","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"network_netdiscover","description":"Passive network discovery — listen for ARP traffic without sending probes","parameters":{"type":"object","properties":{"duration":{"type":"integer","default":30,"description":"How many seconds to listen"}}}}},
    {"type":"function","function":{"name":"network_dig","description":"Full DNS lookup for a domain — returns A, AAAA, MX, NS, and TXT records","parameters":{"type":"object","properties":{"domain":{"type":"string"}},"required":["domain"]}}},
    {"type":"function","function":{"name":"network_traceroute","description":"Trace the network path to a host, showing each hop","parameters":{"type":"object","properties":{"host":{"type":"string"}},"required":["host"]}}},
    {"type":"function","function":{"name":"network_speedtest","description":"Run an internet speed test and return ping, download, and upload speeds","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"network_nmap_expand","description":"Flexible nmap scan with preset profiles: quick (-F fast), ports (-p 1-1024), os (-O detection), full (-A aggressive). IMPORTANT: only run this against targets on networks the operator owns or has explicit written permission to scan. Never use the 'os' or 'full' flags against external IPs, public hosts, or any network you do not control — OS detection and aggressive scans are intrusive and may be illegal without authorisation.","parameters":{"type":"object","properties":{"target":{"type":"string"},"flags":{"type":"string","enum":["quick","ports","os","full"]}},"required":["target"]}}},
    {"type":"function","function":{"name":"network_tools_menu","description":"CALL THIS when the user says 'network tools', 'what network tools', or asks what network scanning options are available. Returns an interactive menu of all available network tools.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"bluetooth_scan","description":"Scan for nearby Bluetooth devices","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"bluetooth_status","description":"Bluetooth adapter status","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"system_status","description":"Full system status","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"gpu_status","description":"RTX 4060 GPU status","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"ollama_status","description":"Check Ollama and loaded models","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"cve_lookup","description":"Look up a CVE vulnerability","parameters":{"type":"object","properties":{"cve_id":{"type":"string"}},"required":["cve_id"]}}},
    {"type":"function","function":{"name":"hash_string","description":"Hash a string MD5 SHA1 SHA256","parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}},
    {"type":"function","function":{"name":"check_password_breach","description":"Check if password has been breached","parameters":{"type":"object","properties":{"password":{"type":"string"}},"required":["password"]}}},
    {"type":"function","function":{"name":"whois","description":"WHOIS lookup for a domain","parameters":{"type":"object","properties":{"domain":{"type":"string"}},"required":["domain"]}}},
    {"type":"function","function":{"name":"dns_records","description":"Get DNS records for a domain","parameters":{"type":"object","properties":{"domain":{"type":"string"}},"required":["domain"]}}},
    {"type":"function","function":{"name":"ssl_check","description":"Check SSL certificate for a host","parameters":{"type":"object","properties":{"host":{"type":"string"}},"required":["host"]}}},
    {"type":"function","function":{"name":"cybersec_study","description":"Study a cybersecurity topic","parameters":{"type":"object","properties":{"topic":{"type":"string"}},"required":["topic"]}}},
    {"type":"function","function":{"name":"analyze_scam","description":"Analyze any text for scam and manipulation tactics — accepts SMS, email, job offers, contracts, voicemail transcripts, anything suspicious. Returns likelihood rating (Clean / Suspicious / Likely Scam / Run. Just run.), tactics detected in plain English, what the sender actually wants, what to do right now, and a plain verdict. Fully offline, nothing leaves this machine. CALL THIS whenever someone pastes or describes a suspicious message, offer, or demand.","parameters":{"type":"object","properties":{"text":{"type":"string","description":"The suspicious text to analyze — paste the full message"}},"required":["text"]}}},
    {"type":"function","function":{"name":"check_identity_exposure","description":"Assess risk and build a recovery plan when personal information has been exposed — through a data breach, scam, lost wallet, phishing, or anything else. Tell this tool what was exposed (SSN, email, bank account, date of birth, etc.) and optionally how it happened. Returns risk per item, numbered priority actions, specific agencies and contacts, freeze recommendations, and a calm verdict. Fully offline. Input is not logged to disk.","parameters":{"type":"object","properties":{"exposed":{"type":"string","description":"What was exposed — comma-separated, e.g. 'SSN, email, bank account number, date of birth'"},"context":{"type":"string","description":"Optional: how or where it happened — e.g. 'data breach', 'phishing scam', 'lost wallet'"}},"required":["exposed"]}}},
    {"type":"function","function":{"name":"investigation_start","description":"Start a ghost hunting investigation session","parameters":{"type":"object","properties":{"location":{"type":"string"}},"required":["location"]}}},
    {"type":"function","function":{"name":"investigation_end","description":"End investigation and generate report","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"investigation_log_evp","description":"Log an EVP timestamp","parameters":{"type":"object","properties":{"note":{"type":"string"}}}}},
    {"type":"function","function":{"name":"investigation_log_emf","description":"Log an EMF reading","parameters":{"type":"object","properties":{"reading":{"type":"string"},"location":{"type":"string"}},"required":["reading"]}}},
    {"type":"function","function":{"name":"investigation_status","description":"Current investigation session status","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"analyze_camera","description":"Capture one frame from Dio's camera and analyze it with LLaVA using a custom prompt","parameters":{"type":"object","properties":{"prompt":{"type":"string","description":"What to look for or ask about the image"}},"required":["prompt"]}}},
    {"type":"function","function":{"name":"analyze_screenshot","description":"Analyze a screenshot or image file from disk. Pass the path to a PNG or JPG and an optional question. Uses LLaVA to describe the image, then Hermes3 to reason over that description and answer the question.","parameters":{"type":"object","properties":{"image_path":{"type":"string","description":"Absolute or relative path to the image file (PNG, JPG, JPEG, WEBP, BMP)"},"question":{"type":"string","description":"What to ask or focus on (optional — defaults to a general description and analysis)"}},"required":["image_path"]}}},
    {"type":"function","function":{"name":"start_evening_capture","description":"Capture photos of the evening at a timed interval through Stack-Chan's (Dio's) own camera. Frames are saved to Ph3b3's captures folder (~/ph3b3_data/captures) — the only photo store. Say 'start capturing the evening' or 'start evening capture' to trigger this.","parameters":{"type":"object","properties":{"label":{"type":"string","default":"evening","description":"A short label for this capture session, for your own reference"},"interval":{"type":"number","default":120,"description":"Seconds between shots"}}}}},
    {"type":"function","function":{"name":"stop_evening_capture","description":"Stop the evening photo capture session and report how many photos were saved to Ph3b3's captures folder.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"fleet_status","description":"Get a READ-ONLY summary of the device fleet (Nyx, Iris, Dio/Stack-Chan, Argus): each device's health state — HEALTHY, SICK, or SILENT — plus last-seen, battery, and signal. CALL THIS when asked 'how's the fleet', 'are the devices online/breathing', 'is Iris/Dio awake', battery/device status, or anything about fleet health. Observability only — you cannot restart, reflash, or change any device.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"last_capture","description":"Get the most recent capture transcript from a device (read-only). CALL THIS when asked 'what did Iris last hear', 'what was the last thing recorded/captured', 'read me the last recording', or about a device's most recent recording.","parameters":{"type":"object","properties":{"device":{"type":"string","description":"Which device: 'iris' or 'stackchan' (optional — omit for the most recent across all devices)"}}}}},
    {"type":"function","function":{"name":"find_recipe","description":"Search 2+ million local recipes from the RecipeNLG corpus — fully offline, zero network, zero GPU. Three modes: 'text' for free-text search (e.g. 'carbonara', 'Thai noodles'), 'strict' to find recipes that use ALL listed ingredients, 'pantry' (default) to find the best matches from what you have on hand — results are ranked by fewest missing ingredients. You will receive structured recipe rows: narrate them to the user (title, key ingredients, directions summary, what they're missing in pantry mode). Do NOT fabricate or invent recipe details — report exactly what the tool returns.","parameters":{"type":"object","properties":{"query":{"type":"string","description":"Free-text search term — used in 'text' mode (e.g. 'carbonara', 'banana bread')"},"ingredients":{"type":"array","items":{"type":"string"},"description":"List of ingredient names — used in 'strict' and 'pantry' modes (e.g. ['chicken', 'rice', 'lime'])"},"mode":{"type":"string","enum":["text","strict","pantry"],"default":"pantry","description":"'text': free-text FTS search. 'strict': recipes using ALL listed ingredients. 'pantry': best matches from what you have, ranked by fewest missing."},"limit":{"type":"integer","default":5,"description":"Number of results to return (1–20)"}},"required":[]}}},
    {"type":"function","function":{"name":"generate_video","description":"Generate a short AI video clip from a text description, or animate an EXISTING generated image into a video. Use when the user asks to make/create/render a video, or to animate/bring an image to life. Presets: ltx-fast (~1.5 min, quick default), wan-fast (~10 min, higher quality), wan-quality (~35 min, best). The render runs in the background and holds the GPU — tell the user the ETA from the tool's reply. Report the status line the tool returns; never fabricate progress.","parameters":{"type":"object","properties":{"prompt":{"type":"string","description":"What the video should show and how it should move"},"preset":{"type":"string","enum":["ltx-fast","wan-fast","wan-quality"],"description":"Speed/quality preset; default ltx-fast"},"source_job_id":{"type":"string","description":"Optional job id of an existing generated image to animate (image-to-video)"}},"required":["prompt"]}}}
]

_SENSITIVE_KEY_FRAGMENTS = frozenset({
    "password", "token", "key", "secret", "credential", "auth", "pin",
    "exposed", "context",
})


def _scrub_args(args: dict, tool_name: str = "") -> dict:
    scrubbed = {}
    for k, v in args.items():
        if tool_name == "remember_fact" and k == "key":
            scrubbed[k] = v
        elif tool_name == "analyze_screenshot" and k == "question":
            scrubbed[k] = "[REDACTED]"
        elif tool_name == "analyze_scam" and k == "text":
            scrubbed[k] = "[REDACTED]"
        elif any(frag in k.lower() for frag in _SENSITIVE_KEY_FRAGMENTS):
            scrubbed[k] = "[REDACTED]"
        else:
            scrubbed[k] = v
    return scrubbed


def _log_skill(name: str, args: dict, result, success: bool) -> None:
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": name,
        "args_summary": {k: str(v)[:120] for k, v in _scrub_args(args, name).items()},
        "result_summary": str(result)[:200],
        "success": success,
    }
    try:
        with SKILL_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        log.warning(f"Skill log write failed: {e}")


def _format_recipes(
    rows: list,
    mode: str,
    query: str = "",
    ingredients: list | None = None,
) -> str:
    """Render recipe rows into a structured text block for Hermes3 to narrate."""
    if not rows:
        if mode == "text":
            return f"No recipes found matching '{query}'."
        return f"No recipes found for ingredients: {', '.join(ingredients or [])}."

    header = {
        "text":   f"Found {len(rows)} recipe(s) for '{query}':",
        "strict": f"Found {len(rows)} recipe(s) using all of: {', '.join(ingredients or [])}:",
        "pantry": f"Found {len(rows)} recipe(s) ranked by fewest missing ingredients:",
    }[mode]

    parts = [header]
    for i, r in enumerate(rows, 1):
        title = r.get("title", "Untitled")
        ingr  = r.get("ingredients", [])
        dirs  = r.get("directions",  [])
        link  = r.get("link", "")

        # Summarise directions to first 2 steps to keep context manageable
        steps = dirs[:2]
        steps_text = " ".join(f"({j+1}) {s}" for j, s in enumerate(steps))
        if len(dirs) > 2:
            steps_text += f" ... ({len(dirs) - 2} more steps)"

        entry = [f"\n{i}. {title}"]
        entry.append(f"   Ingredients ({len(ingr)}): {', '.join(ingr[:12])}" +
                     (f" ... (+{len(ingr)-12} more)" if len(ingr) > 12 else ""))
        entry.append(f"   Directions: {steps_text}")

        if mode == "pantry":
            missing  = r.get("missing", [])
            coverage = r.get("coverage", 0.0)
            pct      = int(coverage * 100)
            if missing:
                entry.append(f"   You're missing: {', '.join(missing[:8])}" +
                              (f" (+{len(missing)-8} more)" if len(missing) > 8 else ""))
            else:
                entry.append("   You have everything needed.")
            entry.append(f"   Coverage: {pct}%")

        if link:
            entry.append(f"   Source: {link}")

        parts.append("\n".join(entry))

    return "\n".join(parts)


def _format_recall(hits: list[dict]) -> str:
    """Render Mnemosyne recall hits as text for Hermes3 to read back."""
    if not hits:
        return "No relevant memories found."
    lines = []
    for h in hits:
        dev = h.get("source_device") or "?"
        when = (h.get("timestamp") or "")[:10]
        lines.append(f"- [{dev}/{h.get('kind','?')}, {when}] {h['text']}")
    return "Relevant memories:\n" + "\n".join(lines)


async def execute_tool(name, args, device="nyx", session_id=""):
    log.info(f"Tool: {name}")
    result = None
    success = False
    try:
        if name == "spotify_play": result = await spotify.play(args["query"], args.get("type","track"))
        elif name == "spotify_control": result = await spotify.control(args["action"])
        elif name == "spotify_now_playing": result = await spotify.now_playing()
        elif name == "dnd_lookup": result = dnd.lookup(args["query"], args.get("category","any"), args.get("edition","5e"))
        elif name == "film_lookup": result = film.lookup(args["query"], args.get("mode","lookup"))
        elif name == "translate_text":
            r = translation.translate(args["text"], args.get("target_lang"))
            if r.get("error"):
                result = f"Error: {r['error']}"
            else:
                result = r.get("translated", "")
        elif name == "remember_fact": result = memory.remember_fact(args["key"], args["value"])
        elif name == "log_anomaly": result = memory.log_anomaly(args["description"], args.get("source","camera"))
        elif name == "recall_memory": result = memory.recall(args["topic"])
        elif name == "remember":
            # Tag the memory with the device that's actually talking (from the
            # /chat request), so a thread started on Iris is attributable to iris
            # and cross-device recall works. Falls back to a model-supplied
            # session_id if one was passed, else the request's session.
            _mid = mem_spine.remember(args["text"], source_device=(device or "nyx"),
                                      session_id=(args.get("session_id") or session_id),
                                      role="assistant", kind=args.get("kind", "conversation"))
            result = f"Saved to shared memory (id {_mid[:8]})."
        elif name == "recall":
            result = _format_recall(mem_spine.recall(args["query"], top_k=int(args.get("top_k", 5))))
        elif name == "occult_lookup": result = occult.lookup(args["query"], args.get("category","any"))
        elif name == "generate_video": result = _tool_generate_video(args)
        elif name == "occult_random": result = occult.random_phenomenon()
        elif name == "tell_joke":
            joke = jokes.tell_joke(args.get("category","any"))
            tts.speak(joke, blocking=False)
            result = "Joke delivered."
        elif name == "roast":
            roast_text = jokes.roast_security() if args.get("topic") == "security" else jokes.roast_dnd()
            tts.speak(roast_text, blocking=False)
            result = "Roast delivered."
        # vision.look/set_baseline/check_anomaly BLOCK waiting for a frame to
        # arrive at the async /vision/frame handler — they MUST run off the event
        # loop or the loop can't service the frame and the capture deadlocks.
        elif name == "look": result = await asyncio.to_thread(vision.look, args.get("prompt"))
        # Camera monitoring is ghost-hunting gear — only usable during an active
        # investigation, so vision is prompt-only (`look`) the rest of the time.
        elif name == "set_baseline":
            result = (await asyncio.to_thread(vision.set_baseline)) if investigation.is_active() else "The camera baseline is ghost-hunting gear — start an investigation first."
        elif name == "check_anomaly":
            result = (await asyncio.to_thread(vision.check_anomaly)) if investigation.is_active() else "Anomaly monitoring is ghost-hunting gear — start an investigation first."
        elif name == "start_monitoring":
            result = (await asyncio.to_thread(vision.start_monitoring, args.get("interval",30))) if investigation.is_active() else "Background camera monitoring is ghost-hunting gear — start an investigation first."
        elif name == "web_search": result = search.news(args["query"]) if args.get("type") == "news" else search.search(args["query"])
        elif name == "speak": result = tts.speak(args["text"], blocking=False)
        elif name == "listen":
            r = stt.listen(args.get("duration",10))
            if r.get("error"):
                tts.speak("I couldn't hear that, my local voice recognition failed.")
                result = f"Error: {r['error']}"
            else:
                result = f"Heard: {r.get('text','')}"
        elif name == "anime_lookup": result = anime.lookup(args["query"], args.get("mode","lookup"))
        elif name == "anime_random": result = anime.random_rec()
        elif name == "add_story": result = stories.add_story_from_person(args["name"], args["story"])
        elif name == "recall_stories": result = stories.recall_stories(args.get("topic"))
        elif name == "add_note": result = notes.add(args["content"], args.get("tag","general"))
        elif name == "read_last_note": result = notes.read_last(args.get("tag"))
        elif name == "search_notes": result = notes.search(args["query"])
        elif name == "start_timer": result = timer.set_timer(args["name"], args["seconds"], callback=tts.speak)
        elif name == "pomodoro": result = timer.pomodoro(args.get("minutes",25), callback=tts.speak)
        elif name == "add_reminder": result = reminders.add(args["text"], args.get("when"), args.get("tag","general"))
        elif name == "list_reminders": result = reminders.list_pending()
        elif name == "calendar_today": result = calendar.today()
        elif name == "calendar_week": result = calendar.week()
        elif name == "weather_current": result = weather.current(args.get("location"))
        elif name == "weather_ghost_hunting": result = weather.good_for_ghost_hunting(args.get("location"))
        elif name == "extract_job_posting": result = resume.extract_job_posting(args["source"])
        elif name == "profile_get": result = resume.profile_get()
        elif name == "profile_add_skill": result = resume.profile_add_skill(args["skill"])
        elif name == "profile_add_experience": result = resume.profile_add_experience(args["role"], args["org"], args.get("duration", ""), args.get("bullets"))
        elif name == "profile_add_certification": result = resume.profile_add_certification(args["name"], args.get("issuer", ""), args.get("year"))
        elif name == "profile_add_project": result = resume.profile_add_project(args["name"], args.get("description", ""), args.get("tech"), args.get("bullets"))
        elif name == "profile_add_note": result = resume.profile_add_note(args["note"])
        elif name == "match_candidate_to_job": result = resume.match_candidate_to_job(args["job_analysis"])
        elif name == "draft_resume_section": result = resume.draft_resume_section(args["requirement"], args["profile_entry"])
        elif name == "analyze_resume": result = resume.analyze_resume(args["resume_text"], args.get("job_description",""))
        elif name == "build_ats_resume": result = resume.build_ats_resume(args["resume_text"], args.get("job_description",""))
        elif name == "network_my_ip": result = network.my_ip()
        elif name == "network_scan": result = network.scan_network(args.get("target","192.168.0.0/24"))
        elif name == "network_who_is_on": result = network.who_is_on_network()
        elif name == "network_arp_scan": result = network.arp_scan()
        elif name == "network_netdiscover": result = network.netdiscover_passive(args.get("duration", 30))
        elif name == "network_dig": result = network.dig_lookup(args["domain"])
        elif name == "network_traceroute": result = network.traceroute(args["host"])
        elif name == "network_speedtest": result = network.speedtest()
        elif name == "network_nmap_expand": result = network.nmap_expand(args["target"], args.get("flags"))
        elif name == "network_tools_menu": result = network.tools_menu()
        elif name == "bluetooth_scan": result = bluetooth.scan()
        elif name == "bluetooth_status": result = bluetooth.status()
        elif name == "system_status": result = system.full_status()
        elif name == "gpu_status": result = system.gpu_status()
        elif name == "ollama_status": result = system.ollama_status()
        elif name == "cve_lookup": result = cybersec.cve_lookup(args["cve_id"])
        elif name == "hash_string": result = cybersec.hash_string(args["text"])
        elif name == "check_password_breach": result = cybersec.check_hash_haveibeenpwned(args["password"])
        elif name == "whois": result = cybersec.whois(args["domain"])
        elif name == "dns_records": result = cybersec.dns_records(args["domain"])
        elif name == "ssl_check": result = cybersec.ssl_check(args["host"])
        elif name == "cybersec_study": result = cybersec.study_topic(args["topic"])
        elif name == "analyze_scam":
            result = scam_detector.analyze(args["text"])
            if "Run. Just run." in result:
                tts.speak(
                    "Run. Just run. This is a scam. Stop all contact right now. "
                    "Do not send any money. Do not share any information. "
                    "Do not give anyone access to your computer.",
                    blocking=False,
                )
        elif name == "check_identity_exposure":
            result = scam_detector.check_identity_exposure(args["exposed"], args.get("context", ""))
            exposed_lower = args["exposed"].lower()
            if any(kw in exposed_lower for kw in ("ssn", "social security")):
                tts.speak(
                    "Your Social Security number was exposed. "
                    "The single most important first step is a credit freeze at all three bureaus: "
                    "Equifax, Experian, and TransUnion. "
                    "It is free, it can be done online or by phone today, "
                    "and it stops almost everything a thief can do with that number.",
                    blocking=False,
                )
        elif name == "investigation_start": result = investigation.start(args["location"])
        elif name == "investigation_end": await asyncio.to_thread(vision.stop_monitoring); result = investigation.end()
        elif name == "investigation_log_evp": result = investigation.log_evp(args.get("note",""))
        elif name == "investigation_log_emf": result = investigation.log_emf(args["reading"], args.get("location",""))
        elif name == "investigation_status": result = investigation.status()
        elif name == "analyze_camera": result = await asyncio.to_thread(vision.look, args["prompt"])
        elif name == "analyze_screenshot":
            _img_path = args["image_path"]
            _analysis = screenshot.analyze(_img_path, args.get("question", ""))
            tts.speak(_analysis, blocking=False)
            if str(_img_path).startswith("/tmp/"):
                try:
                    Path(_img_path).unlink(missing_ok=True)
                except OSError:
                    pass
            result = "Screenshot analysis delivered."
        elif name == "start_evening_capture":
            result = _ec_mod.tool_start_evening_capture(
                args.get("label", "evening"),
                args.get("interval", 120),
                vision.capture,          # Stack-Chan only — pull each frame from Dio
            )
        elif name == "stop_evening_capture":
            result = _ec_mod.tool_stop_evening_capture()
        elif name == "fleet_status":
            result = _fleet_status_summary()
        elif name == "last_capture":
            lc = captures_feed.last_transcript(args.get("device"))
            result = (f"Last capture from {lc['device']}: \"{lc['transcript']}\"" if lc
                      else "No captures with a transcript yet.")
        elif name == "find_recipe":
            _mode  = args.get("mode", "pantry")
            _limit = max(1, min(int(args.get("limit", 5)), 20))
            if _mode == "text":
                _q = args.get("query", "").strip()
                if not _q:
                    result = "find_recipe: 'text' mode requires a query string."
                else:
                    _rows = recipe_store.search_text(_q, limit=_limit)
                    result = _format_recipes(_rows, mode="text", query=_q)
            elif _mode == "strict":
                _ing = [i.strip() for i in args.get("ingredients", []) if i.strip()]
                if not _ing:
                    result = "find_recipe: 'strict' mode requires an ingredients list."
                else:
                    _rows = recipe_store.search_by_ingredients(_ing, strict=True, limit=_limit)
                    result = _format_recipes(_rows, mode="strict", ingredients=_ing)
            else:  # pantry (default)
                _ing = [i.strip() for i in args.get("ingredients", []) if i.strip()]
                if not _ing:
                    result = "find_recipe: 'pantry' mode requires an ingredients list."
                else:
                    _rows = recipe_store.search_by_ingredients(_ing, strict=False, limit=_limit)
                    result = _format_recipes(_rows, mode="pantry", ingredients=_ing)
        else:
            result = f"Unknown tool: {name}"
            _log_skill(name, args, result, False)
            return result
        success = True
    except Exception as e:
        log.error(f"Tool error {name}: {e}")
        result = f"Tool error: {e}"
    _log_skill(name, args, result, success)
    return result

ONE_SHOT_TOOLS = frozenset({"tell_joke", "roast"})


def _looks_like_tool_call(text: str) -> bool:
    """Return True if text is a raw tool-call/schema leak rather than user-facing prose.

    Hermes3 leaks tool calls in several JSON shapes; the one reliable signal is that
    the entire content is a bare JSON object — natural-language replies never are.
    """
    t = text.strip()
    if "<tool_call>" in t or "</tool_call>" in t:
        return True
    if t.startswith("{") and t.endswith("}"):
        try:
            parsed = json.loads(t)
            return isinstance(parsed, dict)
        except Exception:
            pass
    return False


def _parse_tool_call_text(text: str) -> tuple:
    """Parse a text-format tool call. Returns (name, args) or (None, {})."""
    t = text.strip().replace("<tool_call>", "").replace("</tool_call>", "").strip()
    try:
        parsed = json.loads(t)
        if not isinstance(parsed, dict):
            return None, {}
        name = parsed.get("name") or parsed.get("function")
        if not name:
            return None, {}
        args = parsed.get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        return name, args
    except Exception:
        return None, {}


async def chat_with_tools(messages, device="nyx", session_id=""):
    async with httpx.AsyncClient(timeout=120) as client:
        payload = {"model":HEAVY_MODEL,"messages":messages,"stream":False,"tools":TOOLS,"options":{"temperature":0.7,"num_ctx":8192}}
        try:
            response = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
            response.raise_for_status()
        except Exception as e:
            log.error(f"Ollama initial request failed: {e}")
            return f"I can't reach my language model right now ({HEAVY_MODEL}). Is Ollama running?", messages
        msg = response.json()["message"]
        called_tools: set = set()
        tool_cache: dict = {}
        loop = 0
        while msg.get("tool_calls") and loop < 5:
            loop += 1
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn = tc["function"]["name"]
                args = tc["function"]["arguments"]
                if isinstance(args, str): args = json.loads(args)
                if fn in ONE_SHOT_TOOLS and fn in tool_cache:
                    result = tool_cache[fn]
                else:
                    result = await execute_tool(fn, args, device, session_id)
                    called_tools.add(fn)
                    if fn in ONE_SHOT_TOOLS:
                        tool_cache[fn] = result
                messages.append({"role":"tool","content":str(result)})
            follow_model = _select_model(called_tools)
            payload["model"] = follow_model
            payload["messages"] = messages
            try:
                response = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
                response.raise_for_status()
            except Exception as e:
                log.error(f"Ollama follow-up request failed (model={follow_model}): {e}")
                return f"I completed the action but couldn't formulate a response — model '{follow_model}' may not be installed.", messages
            msg = response.json()["message"]
        content = msg.get("content", "")

        # Hermes3 sometimes outputs a tool call as raw JSON/XML text in content
        # instead of using the structured tool_calls field.  Detect, execute, synthesise.
        if _looks_like_tool_call(content):
            log.warning(f"Tool-call text leak detected: {content[:120]!r}")
            _tc_name, _tc_args = _parse_tool_call_text(content)
            content = ""
            if _tc_name:
                try:
                    _tc_result = await execute_tool(_tc_name, _tc_args, device, session_id)
                    _synth = [
                        messages[0],
                        {"role": "user", "content": f"Tool result: {str(_tc_result)[:600]}\n\nSummarise this for the user in one clear paragraph."},
                    ]
                    _pl = {"model": HEAVY_MODEL, "messages": _synth, "stream": False, "options": {"temperature": 0.7, "num_ctx": 4096}}
                    _r = await client.post(f"{OLLAMA_HOST}/api/chat", json=_pl)
                    _r.raise_for_status()
                    content = _r.json()["message"].get("content", "") or str(_tc_result)[:300]
                except Exception as e:
                    log.error(f"Leaked tool call recovery failed ({_tc_name}): {e}")

        if not content and loop > 0:
            # hermes3 exited the tool loop without synthesising — rebuild context without
            # tool_call/tool messages so the model can produce plain text
            last_tool_result = next(
                (m["content"] for m in reversed(messages) if m.get("role") == "tool"),
                "",
            )
            if last_tool_result:
                synth_messages = [
                    messages[0],  # system prompt
                    {"role": "user", "content": f"Tool result: {last_tool_result[:600]}\n\nSummarise this for the user in one clear paragraph."},
                ]
                payload["tools"] = []
                payload["messages"] = synth_messages
                payload["model"] = HEAVY_MODEL
                try:
                    r = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
                    r.raise_for_status()
                    raw = r.json()["message"].get("content", "")
                    content = raw if not _looks_like_tool_call(raw) else ""
                except Exception as e:
                    log.error(f"Synthesis fallback failed: {e}")
        return content, messages

CONV_WINDOW = 8  # conversation turns (user+assistant pairs) kept per session

class Session:
    def __init__(self):
        self.history = [{"role":"system","content":SYSTEM_PROMPT}]
    def add(self, role, content):
        self.history.append({"role":role,"content":content})
        # Rolling window: always keep system prompt + last CONV_WINDOW turns
        max_msgs = 1 + CONV_WINDOW * 2
        if len(self.history) > max_msgs:
            self.history = [self.history[0]] + self.history[-(CONV_WINDOW * 2):]
    def messages(self):
        return self.history.copy()
    def reset(self):
        self.history = [{"role":"system","content":SYSTEM_PROMPT}]

sessions = {}
def get_session(sid="default"):
    if sid not in sessions: sessions[sid] = Session()
    return sessions[sid]

# In-memory device roster: { device_name -> ISO-UTC last-seen timestamp }
_device_roster: dict = {}

@app.get("/health")
async def health():
    # Intentionally touches nothing — responds immediately even mid-startup.
    return {"status": "alive"}


@app.get("/ready")
async def ready():
    # Richer status — only call this after startup is confirmed complete.
    return {
        "status": "alive",
        "model": MODEL,
        "soul": SOUL_FILE.exists(),
        "boot": memory.memory.get("boot_count", 0),
        "whisper": stt.status(),
        "tts": tts.status(),
        "suggestions": [
            "What can you do?",
            "What's the weather?",
            "List my reminders",
            "Tell me a joke",
            "System status",
            "GPU status",
            "What's playing on Spotify?",
            "Scan the network",
        ],
    }

@app.get("/skills")
async def skills_log():
    if not SKILL_LOG.exists():
        return {"entries": [], "total": 0}
    lines = SKILL_LOG.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines[-50:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return {"entries": entries, "total": len(lines)}

def _triage_context(prior_messages) -> str:
    """Prior conversation turns (excluding the persona/system prompt) as plain text."""
    turns = [m for m in prior_messages if m.get("role") in ("user", "assistant")]
    return "\n".join(f"{m['role']}: {m['content']}" for m in turns[-8:])


# ── Tap-to-wake + self-echo suppression (Dio / Stack-Chan) ────────────────────
# Dio wakes on a physical TAP (reliable — no flaky "Phoebe" capture), then talks
# hands-free. With no wake word to gate on, her own TTS echo is suppressed by
# CONTENT: if a stackchan transcript substantially overlaps her LAST reply to
# that session, it's her own voice looping back — drop it. Exit is "goodbye" /
# dead-air / tap (device-side). Iris (push-to-talk) and the web UI never gate.
_LAST_REPLY = {}   # session_id -> her last reply text, for echo suppression

def _words(s):
    return [w for w in "".join(c if c.isalpha() or c == " " else " "
                          for c in (s or "").lower()).split() if len(w) >= 2]

def _looks_like_self_echo(session_id, text):
    tw = _words(text)
    prev = _LAST_REPLY.get(session_id, "")
    if len(tw) < 3 or not prev:
        return False                      # too short to judge (let short commands through)
    pw = set(_words(prev))
    return sum(1 for w in tw if w in pw) / len(tw) >= 0.6


async def _run_chat_pipeline(body: dict, request: Request):
    """Shared /chat brain: wake-gate → recitation → triage → inference.

    Returns the reply TEXT (with session bookkeeping done exactly as before), or
    None if the wake-gate dropped the utterance. Synthesis is the CALLER's job —
    /chat renders it whole, /chat/stream renders it in bounded chunks. Single
    source of truth so the two endpoints can never diverge.
    """
    session = get_session(body.get("session_id","default"))
    user_msg = body.get("message","")

    # ── Tap-to-wake (Dio / Stack-Chan) — no voice wake word; suppress her echo by content ─
    if request.headers.get("X-Ph3b3-Device", "") == "stackchan":
        if _looks_like_self_echo(body.get("session_id", "default"), user_msg):
            log.info("[echo-guard] dropped self-echo: %r", user_msg)
            return None

    if "soul" in user_msg.lower():
        tts.soul_line()

    # ── Direct story recitation — tell a saved story verbatim, PRE-triage ─────
    _tell = stories.tellable(user_msg)
    if _tell:
        _title, _text = _tell
        _reply = f"Come close, then — here is {_title}, told whole.\n\n{_text}"
        session.add("user", user_msg)
        session.add("assistant", _reply)
        log.info("STORY_TOLD verbatim: %s (%d chars)", _title, len(_text))
        return _reply

    # ── Video-render grace — a Morpheus video holds the GPU, so Ollama/Hermes is
    # evicted and cannot answer; reply conversationally instead of muting/timing
    # out. (Stories above still work — they're memory text, no GPU.) ────────────
    _vid = next((r for r in morpheus.jobs.values()
                 if r.get("kind") == "video" and r.get("state") in _VIDEO_ACTIVE), None)
    if _vid:
        _mins = max(1, round(_vid.get("eta_s", 0) / 60))
        _reply = (f"I'm rendering a video right now — Morpheus has the GPU, so I'm briefly "
                  f"offline for chat (about {_mins} minute{'s' if _mins != 1 else ''} left). "
                  f"Ask me again once it wraps and I'll be right here.")
        session.add("user", user_msg)
        session.add("assistant", _reply)
        log.info("VIDEO_RENDER_GRACE — %d min eta", _mins)
        return _reply

    # ── Triage gate — clarification guard, general chat path, PRE-inference ────
    _triage = await triage_gate(user_msg, _triage_context(session.messages()))
    if not _triage.answerable:
        _q = _triage.question or "I don't have enough to go on yet — can you give me a bit more detail?"
        log.info("TRIAGE_HOLD — missing=%s", _triage.missing or [])
        session.add("user", user_msg)
        session.add("assistant", _q)
        return _q

    session.add("user", user_msg)
    messages = session.messages()

    # ── Live datetime (additive, ephemeral — read fresh every request) ────────
    _now = datetime.now().astimezone()
    _dt_str = _now.strftime("%A, %B %-d, %Y, %-I:%M %p")
    _dt_note = {"role": "system", "content": f"Current date and time: {_dt_str}."}
    messages.insert(1, _dt_note)

    # ── Device-awareness (additive, ephemeral, soul untouched) ───────────────
    _DEVICE_NOTES = {
        "iris": (
            "You are speaking through your Iris combadge (body), running on Nyx (host). "
            "Neither Iris nor Nyx is your name — your name is Ph3b3 (Phoebe). "
            "IMPORTANT: reply in ONE short sentence only (under 20 words). "
            "Begin directly with your answer — no salutation, no address, no preamble."
        ),
        "stackchan": (
            "You are speaking through Stack-Chan, your desktop robot body, running on Nyx (host). "
            "Neither Stack-Chan nor Nyx is your name — your name is Ph3b3 (Phoebe). "
            "Keep replies to 2–3 sentences maximum. Be warm, direct, and expressive. "
            "No preamble, no salutation."
        ),
    }
    device = request.headers.get("X-Ph3b3-Device", "")
    device_note = None
    if device in _DEVICE_NOTES:
        device_note = {"role": "system", "content": _DEVICE_NOTES[device]}
        messages.insert(1, device_note)   # after soul + id_anchor, before conversation turns

    # ── Read-side auto-recall (the mirror of auto-capture) ────────────────────
    # Pull relevant shared memories (cross-device) and inject them so the model
    # can actually USE what other devices remembered — e.g. Dio answering what you
    # told Iris. Deterministic: does NOT depend on Hermes3 calling the recall tool.
    # Ephemeral (stripped below); threshold keeps noise out; same-session hits are
    # skipped since the rolling history already carries them.
    mem_note = None
    if user_msg:
        try:
            _sid = body.get("session_id", "default")
            _hits = await asyncio.to_thread(mem_spine.recall, user_msg, MNEMO_RECALL_K)
            _hits = [h for h in _hits
                     if h["score"] >= MNEMO_RECALL_THRESHOLD and h.get("session_id") != _sid]
            if _hits:
                _lines = "\n".join(f'- (via {h["source_device"]}) the user said: "{h["text"]}"'
                                   for h in _hits)
                mem_note = {"role": "system", "content":
                            "You DO remember these earlier things the user said, on this or other "
                            "devices in the constellation:\n" + _lines + "\n"
                            "When the user asks what they said, asked, or discussed, answer ONLY "
                            "from the lines above — quote the exact name or detail. Do NOT invent "
                            "or guess any name or fact that is not written above. If a line is "
                            "relevant, never reply that you lack memory access or that there isn't "
                            "enough information. Do not mention memory, notes, or where this came from."}
                messages.insert(1, mem_note)
        except Exception:
            log.exception("Mnemosyne auto-recall failed")

    response, updated = await chat_with_tools(
        messages, device=(device or "nyx"), session_id=body.get("session_id", "default"))
    _fire_pending_video()   # start any render queued by generate_video — AFTER the reply

    # Strip ephemeral notes before storing so they never accumulate in history
    if _dt_note in updated:
        updated.remove(_dt_note)
    if device_note and device_note in updated:
        updated.remove(device_note)
    if mem_note and mem_note in updated:
        updated.remove(mem_note)

    session.history = updated
    session.add("assistant", response)

    # Cross-device continuity: deterministically persist the USER's turn to
    # Mnemosyne, tagged with the calling device, so a thread started on one device
    # (e.g. Iris) is recall-visible from another (e.g. Dio) — independent of whether
    # Hermes3 chose to call the remember tool.
    #
    # ONLY the user's message is stored — never Ph3b3's reply. Storing her replies
    # let a failure/refusal ("I don't have access to memory like Iris") become a
    # memory that auto-recall then fed back as context, teaching her to repeat it.
    # The durable, un-poisonable thread is what the USER said. kind=conversation →
    # 30-day TTL. Fire-and-forget: remember() returns before embedding.
    if user_msg:
        try:
            mem_spine.remember(user_msg,
                               source_device=(device or "nyx"),
                               session_id=body.get("session_id", "default"),
                               role="user", kind="conversation")
        except Exception:
            log.exception("Mnemosyne auto-capture failed")

    # Argus Chats: persist the full turn pair (user + Phoebe) to the per-session
    # transcript store (deliberate transcript-keeping, Captain decision 2026-07-18;
    # separate from Mnemosyne). Source = calling device. This helper backs both
    # /chat and /chat/stream, so portal, Iris, and Dio all get logged here.
    _sid = body.get("session_id", "default")
    _src = request.headers.get("X-Ph3b3-Device", "") or (device or "nyx")
    if user_msg:  chat_log.log_turn(_sid, _src, "user", user_msg)
    if response:  chat_log.log_turn(_sid, _src, "phoebe", response)

    return response


@app.post("/vision/frame")
async def vision_frame(request: Request):
    """Dio POSTs a JPEG here after a capture request, or on motion during a hunt.
    Body is the raw JPEG. Saved to ~/ph3b3_data/captures and held as the latest
    frame for look()/check_anomaly to consume."""
    jpeg = await request.body()
    if not jpeg:
        raise HTTPException(400, "empty frame")
    saved = await asyncio.to_thread(vision.receive_frame, jpeg)
    return {"ok": True, "saved": saved, "bytes": len(jpeg)}


@app.post("/chat")
async def chat_endpoint(body: dict, request: Request):
    # Response shape is FROZEN: {response, audio} with the WHOLE reply as one WAV.
    # Iris + web UI depend on this — do not change. Chunked delivery is /chat/stream.
    reply = await _run_chat_pipeline(body, request)
    if reply is None:
        return {"response": "", "audio": ""}
    _LAST_REPLY[body.get("session_id", "default")] = reply   # echo-guard memory
    audio_b64 = await asyncio.to_thread(tts.synthesize_to_b64, reply)
    return {"response": reply, "audio": audio_b64}


# ── Chunked TTS (synth-on-demand) — additive; clients opt in via /chat/stream ──
# Long replies (a 5.4 KB story = ~5 min / 18 MB as one WAV) are split into
# bounded sentence-sized pieces so no single synth scales with reply length.
# First call returns a manifest + chunk 0's audio; the client fetches chunk N+1
# while playing N; the server synthesises lazily per fetch with a one-chunk
# read-ahead. Piper is CPU and already serialised by tts._lock (synthesize_to_b64
# holds it) → chunk renders serialise naturally; no GPU lock is involved.
_TTS_STREAMS = {}          # sid -> {"chunks": [str], "audio": {n: b64}, "ts": float}
_TTS_STREAM_TTL = 900      # evict streams idle > 15 min

def _tts_stream_gc(now):
    for k in [k for k, v in _TTS_STREAMS.items() if now - v["ts"] > _TTS_STREAM_TTL]:
        _TTS_STREAMS.pop(k, None)

def _tts_stream_new(chunks):
    now = time.monotonic()
    _tts_stream_gc(now)
    sid = uuid.uuid4().hex[:12]
    _TTS_STREAMS[sid] = {"chunks": chunks, "audio": {}, "ts": now}
    return sid

async def _tts_chunk_b64(sid, n):
    st = _TTS_STREAMS.get(sid)
    if not st or n < 0 or n >= len(st["chunks"]):
        return None
    st["ts"] = time.monotonic()
    if n not in st["audio"]:
        b64 = await asyncio.to_thread(tts.synthesize_to_b64, st["chunks"][n]) or ""
        st["audio"][n] = trim_silence_b64(b64) if b64 else ""   # drop Piper's ~200ms per-chunk gaps
    return st["audio"][n]


@app.post("/chat/stream")
async def chat_stream_endpoint(body: dict, request: Request):
    """Chunked-TTS variant of /chat — same brain via _run_chat_pipeline, but
    returns a manifest + chunk 0 instead of one monolithic WAV. Wake-gate drop
    is preserved (empty manifest, no synthesis)."""
    reply = await _run_chat_pipeline(body, request)
    if not reply:
        return {"response": "", "stream_id": "", "chunk_count": 0,
                "chunk_index": -1, "audio": "", "last": True}
    _LAST_REPLY[body.get("session_id", "default")] = reply   # echo-guard memory
    chunks = split_for_tts(reply)
    if not chunks:
        return {"response": reply, "stream_id": "", "chunk_count": 0,
                "chunk_index": -1, "audio": "", "last": True}
    sid = _tts_stream_new(chunks)
    audio0 = await _tts_chunk_b64(sid, 0)
    if len(chunks) > 1:
        asyncio.create_task(_tts_chunk_b64(sid, 1))   # read-ahead
    # "text" (chunk 0's words) is placed before "audio" and "response" so the
    # firmware can always peek it in its 6 KB head buffer, however long the reply
    # is — Dio shows each chunk's text while that chunk plays, syncing to her voice.
    return {"stream_id": sid, "chunk_count": len(chunks), "chunk_index": 0,
            "text": chunks[0], "audio": audio0 or "", "last": len(chunks) == 1,
            "response": reply}


@app.get("/tts/chunk/{stream_id}/{n}")
async def tts_chunk_endpoint(stream_id: str, n: int):
    """Fetch chunk n's audio for a /chat/stream session (lazy synth, cached,
    one-chunk read-ahead)."""
    st = _TTS_STREAMS.get(stream_id)
    if not st:
        return {"audio": "", "chunk_index": n, "last": True, "error": "unknown or expired stream"}
    if n < 0 or n >= len(st["chunks"]):
        return {"audio": "", "chunk_index": n, "last": True, "error": "chunk out of range"}
    audio = await _tts_chunk_b64(stream_id, n)
    if n + 1 < len(st["chunks"]):
        asyncio.create_task(_tts_chunk_b64(stream_id, n + 1))   # read-ahead
    # "text" before "audio" so the firmware peeks it and shows this chunk's words
    # while its audio plays (voice-synced captioning).
    return {"text": st["chunks"][n], "audio": audio or "",
            "chunk_index": n, "last": n + 1 >= len(st["chunks"])}

@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    if session_id in sessions: sessions[session_id].reset()
    return {"status":"cleared"}

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str = "default"):
    auth = websocket.headers.get("Authorization", "")
    authed = False
    if auth.startswith("Basic ") and AUTH_PASS:
        try:
            creds = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
            user, _, pw = creds.partition(":")
            if (secrets.compare_digest(user.encode(), AUTH_USER.encode()) and
                    secrets.compare_digest(pw.encode(), AUTH_PASS.encode())):
                authed = True
        except Exception:
            pass
    if not authed:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session = get_session(session_id)
    _ws_device = websocket.headers.get("X-Ph3b3-Device", "stackchan")
    log.info(f"Stack-chan connected: {session_id}")
    try:
        while True:
            data = await websocket.receive_json()
            user_input = data.get("message","")
            if not user_input: continue
            if "soul" in user_input.lower():
                tts.soul_line()
            await websocket.send_json({"status":"thinking"})
            session.add("user", user_input)
            response, updated = await chat_with_tools(
                session.messages(), device=_ws_device, session_id=session_id)
            _fire_pending_video()   # start any render queued by generate_video — AFTER the reply
            session.history = updated
            session.add("assistant", response)
            t = response.lower()
            if any(w in t for w in ["!","nice","good","there it is"]): emotion = "happy"
            elif any(w in t for w in ["hmm","let's look","watching"]): emotion = "thinking"
            else: emotion = "neutral"
            await websocket.send_json({"response":response,"emotion":emotion})
    except WebSocketDisconnect:
        log.info(f"Stack-chan disconnected: {session_id}")

@app.post("/transcribe")
async def transcribe_audio(body: dict):
    """Accept base64-encoded WAV audio and return transcribed text via the server's STT module."""
    audio_b64 = body.get("audio", "")
    if not audio_b64:
        return {"text": "", "error": "no audio provided"}
    audio_bytes = base64.b64decode(audio_b64)
    try:                                                          # [DBG-MIC] keep last capture for audition
        open("/tmp/dio_mic_last.wav", "wb").write(audio_bytes)
    except Exception:
        pass
    # [DBG-MIC] characterise captured audio: mic-dead (near-zero level) vs STT-mishear (real level, wrong text)
    _rms = None
    try:
        import struct as _st
        _pcm = audio_bytes[44:]
        _n = len(_pcm) // 2
        if _n:
            _s = _st.unpack("<%dh" % _n, _pcm[:_n * 2])
            _peak = max(abs(x) for x in _s)
            _rms = (sum(x * x for x in _s) / _n) ** 0.5
            log.warning("[DBG-MIC] in %d B ~%.1fs peak=%d/32767 rms=%.0f", len(audio_bytes), _n / 16000.0, _peak, _rms)
    except Exception as _e:
        log.warning("[DBG-MIC] level calc failed: %s", _e)
    # Silence-floor gate: auto-relisten captures ~1.2s of ambient room noise at rms<900; Whisper
    # hallucinates words ("New York City." @ rms 684) out of that silence. Real speech lands rms>2600.
    # Drop anything below the floor before STT — kills phantom transcripts and skips a wasted Whisper call.
    SILENCE_FLOOR_RMS = 1200
    if _rms is not None and _rms < SILENCE_FLOOR_RMS:
        log.warning("[DBG-MIC] below silence floor (rms=%.0f < %d) — dropped, no STT", _rms, SILENCE_FLOOR_RMS)
        return {"text": "", "error": None}
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        result = stt.transcribe_file(tmp_path)
        log.warning("[DBG-MIC] transcript=%r err=%s", (result.get("text") or "")[:80], result.get("error"))
        return {"text": result.get("text") or "", "error": result.get("error")}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _wg_tunnel_up() -> bool:
    """Return True if wg0 exists and is UP — reads live kernel state, never a cached flag."""
    r = subprocess.run(["ip", "link", "show", "wg0"], capture_output=True, text=True)
    return r.returncode == 0 and "UP" in r.stdout

@app.get("/iris/tunnel")
async def iris_tunnel_status():
    return {"up": _wg_tunnel_up()}

@app.post("/iris/tunnel")
async def iris_tunnel_toggle(body: dict):
    action = body.get("action", "")
    if action not in frozenset({"up", "down"}):
        raise HTTPException(400, "action must be 'up' or 'down'")
    # List form, shell=False — no shell ever sees these args.
    # "wg0" is a literal here, never derived from request data.
    cmd = ["sudo", "/usr/bin/wg-quick", action, "wg0"]
    r = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(500, (r.stderr or r.stdout)[:200] or "wg-quick failed")
    return {"up": _wg_tunnel_up()}

# Device WiFi network provisioning endpoints removed 2026-07-16 — Iris & Dio
# now provision on-device via their own setup portals; the server no longer
# stores or serves per-device network lists.

# ── Mnemosyne — shared cross-device persistent memory ───────────────────────────
# Remember / Recall / Recent / Forget. Semantic store on sqlite-vec + CPU
# embeddings; recall is deliberately NOT scoped to the calling device.

@app.post("/mnemosyne/remember")
async def mnemosyne_remember(body: dict):
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    try:
        mid = mem_spine.remember(
            text,
            source_device=str(body.get("source_device", "")),
            session_id=str(body.get("session_id", "")),
            role=str(body.get("role", "user")),
            kind=str(body.get("kind", "conversation")),
            metadata=body.get("metadata"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": mid}


@app.post("/mnemosyne/recall")
async def mnemosyne_recall(body: dict):
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    hits = await asyncio.to_thread(
        mem_spine.recall, query, int(body.get("top_k", 5)), body.get("filters"))
    return hits


@app.get("/mnemosyne/recent")
async def mnemosyne_recent(session_id: str | None = None, device: str | None = None,
                           limit: int = 20, kind: str | None = None):
    # e.g. Dio reads its latest story state on boot:
    #   GET /mnemosyne/recent?device=dio&kind=state&limit=1
    return await asyncio.to_thread(mem_spine.recent, session_id, device, limit, kind)


@app.post("/mnemosyne/forget")
async def mnemosyne_forget(body: dict):
    if not any(body.get(k) for k in ("id", "session_id", "tag")):
        raise HTTPException(status_code=400, detail="one of id, session_id, tag required")
    deleted = await asyncio.to_thread(
        mem_spine.forget, body.get("id"), body.get("session_id"), body.get("tag"))
    return {"deleted_count": deleted}


# ── Karaoke ───────────────────────────────────────────────────────────────────

KARAOKE_LIB = Path.home() / "ph3b3_data" / "karaoke"

_LRC_STUB = """\
[ti:track]
[ar:Artist]
[00:00.00] (intro)
[00:05.00] first line of lyrics here
[00:10.00] next line here
"""


def _karaoke_lib() -> Path:
    KARAOKE_LIB.mkdir(parents=True, exist_ok=True)
    return KARAOKE_LIB


def _find_karaoke_sd() -> Path | None:
    """Return /karaoke/ dir on the first detected removable volume, or None.
    KARAOKE_SD_PATH env var overrides (must point to the /karaoke/ dir itself)."""
    override = os.getenv("KARAOKE_SD_PATH", "").strip()
    if override:
        return Path(override)
    user = getpass.getuser()
    roots = [
        Path(f"/media/{user}"),
        Path(f"/run/media/{user}"),
        Path("/media"),
        Path("/mnt"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for vol in sorted(root.iterdir()):
            if vol.is_dir():
                return vol / "karaoke"
    return None


def _wav_duration_s(path) -> float:
    try:
        with _wave.open(str(path), 'rb') as w:
            return round(w.getnframes() / w.getframerate(), 1)
    except Exception:
        return 0.0


def _track_info(name: str) -> dict:
    lib = _karaoke_lib()
    wav = lib / f"{name}.wav"
    lrc = lib / f"{name}.lrc"
    attr_file = lib / f"{name}.attribution.json"
    sd  = _find_karaoke_sd()
    on_sd = bool(sd and (sd / f"{name}.wav").exists())
    attribution = None
    if attr_file.exists():
        try:
            attribution = json.loads(attr_file.read_text())
        except Exception:
            pass
    return {
        "name":        name,
        "wav_bytes":   wav.stat().st_size if wav.exists() else 0,
        "duration_s":  _wav_duration_s(wav) if wav.exists() else 0.0,
        "lrc_exists":  lrc.exists(),
        "on_sd":       on_sd,
        "source":      "jamendo" if attribution else "upload",
        "attribution": attribution,
    }


def _ffmpeg_convert(src: str, dst: str, rate: int, channels: int) -> list[str]:
    """Run ffmpeg synchronously (call in executor). Returns log lines."""
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ar", str(rate), "-ac", str(channels),
        "-c:a", "pcm_s16le", dst,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:])
    lines = [f"ffmpeg -ar {rate} -ac {channels} pcm_s16le → {Path(dst).name}"]
    lines.append("✓ conversion complete")
    return lines


@app.post("/karaoke/convert")
async def karaoke_convert(file: UploadFile = File(...), preset: str = Form("cd")):
    presets = {
        "voice": (16000, 1),
        "cd":    (44100, 2),
    }
    if preset not in presets:
        raise HTTPException(status_code=400, detail=f"preset must be 'voice' or 'cd', got {preset!r}")
    rate, channels = presets[preset]
    lib = _karaoke_lib()
    dst = str(lib / "track.wav")
    lrc_path = lib / "track.lrc"
    log_lines: list[str] = []

    with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "audio").suffix, delete=False) as tmp:
        tmp_path = tmp.name
        tmp.write(await file.read())
    log_lines.append(f"received {file.filename!r} ({Path(tmp_path).stat().st_size} bytes)")

    loop = asyncio.get_event_loop()
    try:
        new_lines = await loop.run_in_executor(
            None, _ffmpeg_convert, tmp_path, dst, rate, channels
        )
        log_lines.extend(new_lines)
    except RuntimeError as exc:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    lrc_written = False
    if not lrc_path.exists():
        lrc_path.write_text(_LRC_STUB)
        lrc_written = True
        log_lines.append("✓ wrote track.lrc stub")
    else:
        log_lines.append("· track.lrc already exists, left alone")

    return {"ok": True, "name": "track", "lrc_written": lrc_written, "log": log_lines}


@app.get("/karaoke/library")
async def karaoke_library():
    lib = _karaoke_lib()
    sd = _find_karaoke_sd()
    tracks = [_track_info(p.stem) for p in sorted(lib.glob("*.wav"))]
    return {"tracks": tracks, "sd_path": str(sd) if sd else None}


@app.post("/karaoke/push/{name}")
async def karaoke_push(name: str):
    lib = _karaoke_lib()
    wav = lib / f"{name}.wav"
    if not wav.exists():
        raise HTTPException(status_code=404, detail=f"track '{name}' not found in library")
    sd = _find_karaoke_sd()
    if sd is None:
        raise HTTPException(
            status_code=503,
            detail="No SD card detected. Insert one or set KARAOKE_SD_PATH to override.",
        )
    sd.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wav, sd / wav.name)
    lrc = lib / f"{name}.lrc"
    if lrc.exists():
        shutil.copy2(lrc, sd / lrc.name)
    return {"ok": True, "dest": str(sd)}


@app.get("/karaoke/lrc/{name}")
async def karaoke_get_lrc(name: str):
    lrc = _karaoke_lib() / f"{name}.lrc"
    if not lrc.exists():
        raise HTTPException(status_code=404, detail=f"no .lrc for '{name}'")
    return {"text": lrc.read_text()}


@app.put("/karaoke/lrc/{name}")
async def karaoke_put_lrc(name: str, body: dict):
    text = body.get("text", "")
    lrc = _karaoke_lib() / f"{name}.lrc"
    lrc.write_text(text)
    return {"ok": True}


@app.delete("/karaoke/track/{name}")
async def karaoke_delete(name: str):
    lib = _karaoke_lib()
    (lib / f"{name}.wav").unlink(missing_ok=True)
    (lib / f"{name}.lrc").unlink(missing_ok=True)
    (lib / f"{name}.attribution.json").unlink(missing_ok=True)
    return {"ok": True}


# ── Karaoke — Mnemosyne / Jamendo discover + pull ────────────────────────────

@app.get("/karaoke/discover")
async def karaoke_discover(query: str | None = None, tags: str | None = None, limit: int = 6):
    if not os.getenv("JAMENDO_CLIENT_ID"):
        raise HTTPException(status_code=503, detail="JAMENDO_CLIENT_ID not configured in .env")
    try:
        tracks = await mnemosyne.discover(query=query, tags=tags, limit=min(limit, 12))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Jamendo error: {exc}")
    return {"tracks": tracks}


@app.post("/karaoke/pull")
async def karaoke_pull(body: dict):
    track_id = str(body.get("track_id", "")).strip()
    if not track_id:
        raise HTTPException(status_code=400, detail="track_id required")
    if not os.getenv("JAMENDO_CLIENT_ID"):
        raise HTTPException(status_code=503, detail="JAMENDO_CLIENT_ID not configured in .env")
    lib = _karaoke_lib()
    try:
        result = await mnemosyne.pull(track_id, lib)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "ok":    True,
        "name":  result["stem"],
        "log":   result["log"],
        "track": _track_info(result["stem"]),
    }


@app.get("/karaoke/attribution/{name}")
async def karaoke_attribution(name: str):
    attr_file = _karaoke_lib() / f"{name}.attribution.json"
    if not attr_file.exists():
        raise HTTPException(status_code=404, detail=f"No attribution for '{name}'")
    return {"attribution": json.loads(attr_file.read_text())}


@app.get("/karaoke")
async def karaoke_view():
    return Response(
        content=(ROOT / "static" / "karaoke.html").read_text(encoding="utf-8"),
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/karaoke/audio/{name}")
async def karaoke_audio(name: str, request: Request):
    wav = _karaoke_lib() / f"{name}.wav"
    if not wav.exists():
        raise HTTPException(status_code=404, detail=f"audio '{name}' not found")
    # FileResponse handles Range headers natively — required for seek/scrub in browsers
    return FileResponse(wav, media_type="audio/wav",
                        headers={"Accept-Ranges": "bytes"})


# In-memory session: phone pushes track → TV polls and auto-plays
_karaoke_session: dict = {"track": None, "playing": False, "ts": 0.0}


@app.get("/karaoke/now")
async def karaoke_session_get():
    return _karaoke_session


@app.put("/karaoke/now")
async def karaoke_session_put(request: Request):
    body = await request.json()
    for k in ("track", "playing"):
        if k in body:
            _karaoke_session[k] = body[k]
    _karaoke_session["ts"] = time.time()
    return _karaoke_session


_COMMON_PASSWORDS = {
    "password","password1","password123","123456","123456789","12345678","12345",
    "1234567","1234567890","qwerty","abc123","monkey","1234","letmein","dragon",
    "master","sunshine","princess","welcome","shadow","superman","michael",
    "football","baseball","iloveyou","trustno1","batman","access","hello",
    "charlie","donald","password2","qwerty123","admin","admin123","root","toor",
    "pass","test","guest","login","changeme","secret","11111111","000000",
    "1q2w3e4r","passw0rd","p@ssword","p@ssw0rd","abc12345","qwertyui",
    "mustang","starwars","cheese","andrew","jessica","pepper","121212",
    "hannah","daniel","computer","696969","thomas","hunter","ranger","joshua",
    "harley","jordan","robert","soccer","tigger","pokemon","maverick",
}

def _check_password_strength(pw: str) -> str | None:
    """Return an error string if the password is too weak, None if it passes."""
    if len(pw) < 12:
        return "Password must be at least 12 characters long."
    if pw.lower() in _COMMON_PASSWORDS:
        return "That one's too easy to guess — let's pick something more unique."
    classes = sum([
        any(c.isupper() for c in pw),
        any(c.islower() for c in pw),
        any(c.isdigit() for c in pw),
        any(not c.isalnum() for c in pw),
    ])
    if classes < 2:
        return "Mix it up a bit — try adding numbers, capitals, or a symbol."
    return None


_FACE_SLEEPY = """<svg viewBox="0 0 200 200" width="140" height="140" xmlns="http://www.w3.org/2000/svg">
  <circle cx="100" cy="100" r="92" fill="#3B1F60" opacity="0.35"/>
  <circle cx="100" cy="100" r="84" fill="#6B3FA0"/>
  <line x1="16" y1="88" x2="42" y2="88" stroke="#22D4E8" stroke-width="1.5" opacity="0.55"/>
  <line x1="42" y1="88" x2="42" y2="70" stroke="#22D4E8" stroke-width="1.5" opacity="0.55"/>
  <circle cx="16" cy="88" r="2.5" fill="#22D4E8" opacity="0.75"/>
  <line x1="184" y1="88" x2="158" y2="88" stroke="#E0408A" stroke-width="1.5" opacity="0.55"/>
  <line x1="158" y1="88" x2="158" y2="70" stroke="#E0408A" stroke-width="1.5" opacity="0.55"/>
  <circle cx="184" cy="88" r="2.5" fill="#E0408A" opacity="0.75"/>
  <ellipse cx="72" cy="97" rx="20" ry="23" fill="#1A0830"/>
  <ellipse cx="128" cy="97" rx="20" ry="23" fill="#1A0830"/>
  <path d="M 52 88 Q 72 82 92 88" fill="#6B3FA0"/>
  <path d="M 108 88 Q 128 82 148 88" fill="#6B3FA0"/>
  <circle cx="67" cy="97" r="4" fill="white" opacity="0.55"/>
  <circle cx="123" cy="97" r="4" fill="white" opacity="0.55"/>
  <path d="M 82 130 Q 100 139 118 130" stroke="#E0408A" stroke-width="3.5" fill="none" stroke-linecap="round"/>
  <text x="138" y="60" font-size="13" fill="#E0408A" opacity="0.45" font-family="system-ui,sans-serif">z</text>
  <text x="148" y="48" font-size="10" fill="#E0408A" opacity="0.28" font-family="system-ui,sans-serif">z</text>
</svg>"""

_FACE_HAPPY = """<svg viewBox="0 0 200 200" width="140" height="140" xmlns="http://www.w3.org/2000/svg">
  <circle cx="100" cy="100" r="92" fill="#8B3FC0" opacity="0.35"/>
  <circle cx="100" cy="100" r="84" fill="#6B3FA0"/>
  <line x1="16" y1="88" x2="42" y2="88" stroke="#22D4E8" stroke-width="1.5" opacity="0.9"/>
  <line x1="42" y1="88" x2="42" y2="70" stroke="#22D4E8" stroke-width="1.5" opacity="0.9"/>
  <circle cx="16" cy="88" r="2.5" fill="#22D4E8"/>
  <line x1="184" y1="88" x2="158" y2="88" stroke="#E0408A" stroke-width="1.5" opacity="0.9"/>
  <line x1="158" y1="88" x2="158" y2="70" stroke="#E0408A" stroke-width="1.5" opacity="0.9"/>
  <circle cx="184" cy="88" r="2.5" fill="#E0408A"/>
  <ellipse cx="72" cy="97" rx="22" ry="26" fill="#1A0830"/>
  <ellipse cx="128" cy="97" rx="22" ry="26" fill="#1A0830"/>
  <circle cx="65" cy="89" r="6" fill="white" opacity="0.95"/>
  <circle cx="64" cy="88" r="2.5" fill="#22D4E8"/>
  <circle cx="121" cy="89" r="6" fill="white" opacity="0.95"/>
  <circle cx="120" cy="88" r="2.5" fill="#22D4E8"/>
  <circle cx="79" cy="91" r="1.5" fill="white" opacity="0.45"/>
  <circle cx="135" cy="91" r="1.5" fill="white" opacity="0.45"/>
  <path d="M 65 128 Q 100 160 135 128" stroke="#E0408A" stroke-width="5" fill="none" stroke-linecap="round"/>
  <circle cx="100" cy="26" r="3" fill="#E0408A" opacity="0.8"/>
  <circle cx="87" cy="34" r="2" fill="#22D4E8" opacity="0.65"/>
  <circle cx="113" cy="34" r="2" fill="#22D4E8" opacity="0.65"/>
</svg>"""

_SETUP_CSS = """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg:       #0A0A14;
      --surface:  #0F0F1E;
      --border:   #2A1F4A;
      --violet:   #6B3FA0;
      --violet-l: #8B5FC0;
      --magenta:  #E0408A;
      --cyan:     #22D4E8;
      --text:     #E8E0F0;
      --dim:      #7868A0;
      --err-bg:   rgba(224,64,138,0.10);
      --err-bd:   rgba(224,64,138,0.30);
    }
    body {
      background: var(--bg);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: system-ui,-apple-system,'Segoe UI',sans-serif;
      color: var(--text);
      padding: 1.5rem;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 2.5rem 2rem;
      width: 100%;
      max-width: 420px;
      text-align: center;
    }
    .face { display: flex; justify-content: center; margin-bottom: 1.25rem; }
    h1 { font-size: 1.45rem; font-weight: 700; margin-bottom: .45rem; }
    .tagline { color: var(--dim); font-size: .88rem; line-height: 1.55; margin-bottom: 1.25rem; }
    .badge {
      display: inline-flex; align-items: center; gap: .35rem;
      font-size: .72rem; color: var(--cyan);
      background: rgba(34,212,232,.08); border: 1px solid rgba(34,212,232,.2);
      border-radius: 100px; padding: .25rem .75rem; margin-bottom: 1.5rem;
    }
    .errors {
      background: var(--err-bg); border: 1px solid var(--err-bd);
      border-radius: 10px; padding: .7rem 1rem; margin-bottom: 1rem; text-align: left;
    }
    .errors p { font-size: .82rem; color: var(--magenta); line-height: 1.5; }
    .errors p + p { margin-top: .2rem; }
    .field { text-align: left; margin-bottom: .95rem; }
    label { display: block; font-size: .78rem; color: var(--dim); margin-bottom: .3rem; letter-spacing: .03em; }
    input {
      width: 100%; background: var(--bg); border: 1px solid var(--border);
      border-radius: 10px; padding: .7rem .9rem; color: var(--text);
      font-size: .95rem; outline: none; transition: border-color .15s;
    }
    input:focus { border-color: var(--violet-l); }
    .hint { font-size: .73rem; color: var(--dim); margin-top: .3rem; line-height: 1.45; }
    button {
      width: 100%; margin-top: .35rem; background: var(--violet); color: #fff;
      border: none; border-radius: 12px; padding: .85rem; font-size: 1rem;
      font-weight: 600; cursor: pointer; transition: background .15s, transform .1s;
      letter-spacing: .01em;
    }
    button:hover { background: var(--violet-l); }
    button:active { transform: scale(.98); }
    .note { margin-top: 1.2rem; font-size: .73rem; color: var(--dim); line-height: 1.5; }
    .ok { color: #22C55E; font-size: .9rem; margin: .75rem 0 1rem; line-height: 1.5; }
    a.go {
      display: inline-block; background: var(--violet); color: #fff;
      text-decoration: none; border-radius: 12px; padding: .75rem 2.25rem;
      font-size: .95rem; font-weight: 600; transition: background .15s;
    }
    a.go:hover { background: var(--violet-l); }
"""


def _setup_html(errors: list[str] | None = None) -> str:
    err_block = ""
    if errors:
        items = "".join(f"<p>{e}</p>" for e in errors)
        err_block = f'<div class="errors">{items}</div>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#0A0A14">
  <title>Meet Ph3b3</title>
  <style>{_SETUP_CSS}</style>
</head>
<body>
<div class="card">
  <div class="face">{_FACE_SLEEPY}</div>
  <h1>Hi — I'm Ph3b3.</h1>
  <p class="tagline">I'm not quite awake yet. Let's set up your access so we can get started. It'll only take a moment.</p>
  <span class="badge">
    <svg width="10" height="10" viewBox="0 0 10 10"><circle cx="5" cy="5" r="3.5" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="5" cy="5" r="1.5" fill="currentColor"/></svg>
    Everything stays on this device — nothing goes online
  </span>
  {err_block}
  <form method="post" action="/setup" autocomplete="off">
    <div class="field">
      <label for="username">Your username</label>
      <input id="username" name="username" type="text" required minlength="2" maxlength="64"
             placeholder="e.g. your first name" autocomplete="username">
    </div>
    <div class="field">
      <label for="password">Choose a password</label>
      <input id="password" name="password" type="password" required minlength="12"
             placeholder="at least 12 characters" autocomplete="new-password">
      <p class="hint">Let's make it a strong one — at least 12 characters, something you haven't used elsewhere.</p>
    </div>
    <div class="field">
      <label for="confirm">Confirm password</label>
      <input id="confirm" name="confirm" type="password" required
             placeholder="same again" autocomplete="new-password">
    </div>
    <button type="submit">Wake me up &#8594;</button>
  </form>
  <p class="note">Ph3b3 runs entirely on your own hardware. These credentials never leave this device.</p>
</div>
</body>
</html>"""


def _setup_done_html(username: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#0A0A14">
  <title>Ph3b3 is awake</title>
  <style>{_SETUP_CSS}</style>
</head>
<body>
<div class="card">
  <div class="face">{_FACE_HAPPY}</div>
  <h1>I'm awake!</h1>
  <p class="tagline">Welcome, {username}. Your credentials are saved and this setup page is now permanently closed — it won't be reachable again.</p>
  <p class="ok">&#10003; Setup complete &mdash; fully local, nothing shared.</p>
  <a class="go" href="/login">Open Ph3b3 &#8594;</a>
  <p class="note" style="margin-top:1.5rem">Bookmark <strong>/panel</strong> for quick access. Enjoy.</p>
</div>
</body>
</html>"""


def _login_html(error: bool = False) -> str:
    err_block = (
        '<div class="login-err">Wrong username or password.</div>' if error else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#0f0624">
  <title>Ph3b3 — Login</title>
  <style>
    :root{{--bg:#0f0624;--surface:rgba(43,15,95,.75);--border:rgba(124,58,237,.32);
      --purple:#7c3aed;--magenta:#e91e8c;--cyan:#00e5ff;--text:#e8d5ff;--dim:#9d7eca;
      --err:#f87171;}}
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
      background-color:var(--bg);
      background-image:linear-gradient(45deg,transparent 48%,rgba(0,229,255,.045) 49%,rgba(0,229,255,.045) 51%,transparent 52%),
        linear-gradient(-45deg,transparent 48%,rgba(247,37,133,.045) 49%,rgba(247,37,133,.045) 51%,transparent 52%);
      background-size:28px 28px;color:var(--text);min-height:100vh;
      display:flex;align-items:center;justify-content:center;}}
    .card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;
      padding:2rem 1.75rem;width:min(340px,90vw);backdrop-filter:blur(8px);
      -webkit-backdrop-filter:blur(8px);}}
    .logo{{display:flex;align-items:center;gap:.75rem;margin-bottom:1.4rem;}}
    .logo-moon svg{{filter:drop-shadow(0 0 7px rgba(0,229,255,.55));}}
    .logo-title{{font-size:1.1rem;font-weight:700;letter-spacing:.15em;
      background:linear-gradient(90deg,var(--magenta),var(--cyan));
      -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}}
    .logo-sub{{font-size:.67rem;color:var(--dim);font-style:italic;margin-top:.12rem;}}
    label{{display:block;font-size:.72rem;font-weight:700;letter-spacing:.06em;
      text-transform:uppercase;color:var(--dim);margin-bottom:.32rem;margin-top:.9rem;}}
    label:first-of-type{{margin-top:0;}}
    input{{width:100%;background:rgba(43,15,95,.6);border:1px solid var(--border);
      border-radius:8px;padding:.6rem .8rem;color:var(--text);font-size:.9rem;
      outline:none;font-family:inherit;}}
    input:focus{{border-color:var(--purple);}}
    .login-err{{margin-top:.75rem;padding:.44rem .7rem;border-radius:8px;font-size:.78rem;
      color:var(--err);background:rgba(248,113,113,.08);border:1px solid rgba(248,113,113,.28);}}
    button{{width:100%;margin-top:1.2rem;padding:.65rem;border:none;border-radius:8px;
      cursor:pointer;font-family:inherit;font-size:.9rem;font-weight:700;letter-spacing:.04em;
      background:linear-gradient(135deg,var(--magenta),#b5006e);color:#fff;
      transition:opacity .15s;}}
    button:hover{{opacity:.85;}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">
      <span class="logo-moon">
        <svg width="36" height="36" viewBox="0 0 44 44" fill="none">
          <defs><mask id="lm"><circle cx="22" cy="22" r="17" fill="white"/>
            <circle cx="30" cy="17" r="13" fill="black"/></mask></defs>
          <circle cx="22" cy="22" r="17" fill="#00e5ff" opacity=".88" mask="url(#lm)"/>
        </svg>
      </span>
      <div>
        <div class="logo-title">PH3B3</div>
        <div class="logo-sub">made with soul, baby</div>
      </div>
    </div>
    <form method="post" action="/login" autocomplete="on">
      <label for="user">Username</label>
      <input id="user" name="user" type="text" autocomplete="username"
             autofocus required>
      <label for="pass">Password</label>
      <input id="pass" name="pass" type="password" autocomplete="current-password" required>
      {err_block}
      <button type="submit">Sign in</button>
    </form>
  </div>
</body>
</html>"""


@app.get("/setup")
async def setup_page():
    if _SETUP_COMPLETE:
        raise HTTPException(status_code=404)
    return HTMLResponse(content=_setup_html())


@app.post("/setup")
async def setup_submit(request: Request):
    global _SETUP_COMPLETE, AUTH_USER, AUTH_PASS
    if _SETUP_COMPLETE:
        raise HTTPException(status_code=404)

    form    = await request.form()
    username = (form.get("username") or "").strip()
    password = (form.get("password") or "")
    confirm  = (form.get("confirm")  or "")

    errors: list[str] = []
    if len(username) < 2:
        errors.append("Username must be at least 2 characters.")
    strength_err = _check_password_strength(password)
    if strength_err:
        errors.append(strength_err)
    elif password != confirm:
        errors.append("Passwords don't match — give it another go.")

    if errors:
        return HTMLResponse(content=_setup_html(errors=errors), status_code=400)

    # Write credentials to .env (preserves all other settings).
    env_file = ROOT / ".env"
    env_file.touch()
    set_key(str(env_file), "PH3B3_USER", username)
    set_key(str(env_file), "PH3B3_PASSWORD", password)

    # Write sentinel file, then flip in-memory state.
    # Order matters: sentinel first so the flag is on disk before memory flips.
    _SETUP_COMPLETE_FILE.touch()
    _SETUP_COMPLETE = True
    AUTH_USER = username
    AUTH_PASS = password

    log.info("First-run setup complete — /setup is now closed.")
    return HTMLResponse(content=_setup_done_html(username))


@app.get("/login")
async def login_page(request: Request):
    # Already logged in → go straight to panel.
    token = request.cookies.get(_SESSION_COOKIE, "")
    if token and token in _sessions:
        return RedirectResponse(url="/panel", status_code=303)
    return HTMLResponse(content=_login_html())


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    user = str(form.get("user", "")).strip()
    pw   = str(form.get("pass", ""))
    if (AUTH_PASS
            and secrets.compare_digest(user.encode(), AUTH_USER.encode())
            and secrets.compare_digest(pw.encode(),   AUTH_PASS.encode())):
        token = secrets.token_hex(32)
        _sessions[token] = user
        resp = RedirectResponse(url="/panel", status_code=303)
        resp.set_cookie(
            _SESSION_COOKIE, token,
            max_age=_SESSION_MAX_AGE,
            httponly=True,
            secure=bool(SSL_CERT),
            samesite="lax",
        )
        return resp
    return HTMLResponse(content=_login_html(error=True), status_code=401)


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get(_SESSION_COOKIE, "")
    _sessions.pop(token, None)
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(_SESSION_COOKIE)
    return resp


@app.get("/panel")
async def panel():
    return Response(
        content=(ROOT / "static" / "panel.html").read_text(encoding="utf-8"),
        media_type="text/html",
    )

@app.get("/sw.js")
async def service_worker():
    content = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    return Response(
        content=content,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )

@app.get("/devices")
async def devices():
    return {"devices": dict(_device_roster)}

# ── Argus: read-only fleet observability ──────────────────────────────────────
def _fleet_status_summary() -> str:
    """Concise fleet summary for the fleet_status tool (values audited: state +
    last-seen + battery/RSSI + drift, nothing Argus could act on)."""
    contracts = load_contracts()
    lines = []
    for ev in argus_store.fleet(contracts):
        d, s = ev["device_id"], ev["state"]
        if s == "SILENT":
            lines.append(f"{d}: SILENT (last seen {_argus_iso(ev['last_seen']) or 'never'}"
                         + (f", last state before silence follows contract" if ev['last_seen'] else "") + ")")
        else:
            extra = []
            if ev.get("battery") is not None: extra.append(f"battery {ev['battery']}%")
            if ev.get("rssi") is not None:    extra.append(f"RSSI {ev['rssi']}dBm")
            if ev.get("firmware_drift"):      extra.append("FIRMWARE DRIFT")
            lines.append(f"{d}: {s}" + (f" ({', '.join(extra)})" if extra else ""))
    return "Fleet status:\n" + "\n".join(lines) if lines else "Fleet status: no devices known yet."

@app.post("/argus/heartbeat")
async def argus_heartbeat(request: Request):
    """Device heartbeat ingest — rides the existing verified check-in path (the
    auth middleware already enforced Basic auth + stamped _device_roster). Records
    a structured heartbeat to the dedicated argus.db. Read-only observability:
    Argus stores, never acts.

    Spoof-hardening: only Dio is IP-pinned (via the camera-verified dio_host). If
    dio_host is known and a 'stackchan' claim arrives from a different IP, reject +
    log. Other devices verify via the shared Basic-auth cred (existing model — no
    new auth scheme)."""
    device = request.headers.get("X-Ph3b3-Device", "unidentified")
    if (device == "stackchan" and vision.dio_host
            and request.client and request.client.host != vision.dio_host):
        log.warning("[ARGUS] rejected spoofed heartbeat: 'stackchan' from %s (verified dio_host=%s)",
                    request.client.host, vision.dio_host)
        raise HTTPException(403, "unverified device identity")
    body = await request.body()
    if len(body) > 512:                       # payload contract is <200 B; 512 is a hard cap
        raise HTTPException(413, "heartbeat payload too large")
    try:
        data = json.loads(body or b"{}")
    except Exception:
        raise HTTPException(400, "invalid heartbeat JSON")
    def _i(v):
        try: return int(v)
        except (TypeError, ValueError): return None
    fw = data.get("firmware_hash")
    argus_store.record_heartbeat(
        device,
        battery=_i(data.get("battery")), rssi=_i(data.get("rssi")),
        uptime=_i(data.get("uptime")), free_heap=_i(data.get("free_heap")),
        firmware_hash=(str(fw)[:64] if fw else None),
    )
    return {"ok": True}

@app.get("/argus/fleet")
async def argus_fleet():
    """Read-only fleet summary for the panel: every contract device with derived
    state, last-seen, battery/RSSI, firmware drift, and a short heap/battery
    sparkline. Contracts are reloaded per call, so they're editable without a
    restart."""
    contracts = load_contracts()
    now = time.time()
    fleet = []
    for ev in argus_store.fleet(contracts, now=now):
        hist = argus_store.history(ev["device_id"], limit=30)
        ev["last_seen_iso"] = _argus_iso(ev["last_seen"])
        ev["spark_heap"] = [h["free_heap"] for h in reversed(hist) if h["free_heap"] is not None]
        ev["spark_batt"] = [h["battery"]  for h in reversed(hist) if h["battery"]  is not None]
        fleet.append(ev)
    self_last = argus_store.self_last()
    return {
        "fleet": fleet,
        "argus": {"last_self": self_last, "last_self_iso": _argus_iso(self_last),
                  "age_s": int(now - self_last) if self_last else None},
        "generated": _argus_iso(int(now)),
    }

def _persist_capture(device: str, audio_bytes: bytes, text: str) -> None:
    """Argus Part 2: persist a device voice recording + its transcript sidecar to
    the captures store, so it shows in the read-only captures feed. The .wav and
    .txt share a filename stem — pairing is by name, no DB. Only real device
    recordings that produced a transcript are kept."""
    if device not in ("iris", "stackchan") or not text:
        return
    try:
        stem = _CAPTURES_DIR / f"{device}_{datetime.now():%Y%m%d_%H%M%S_%f}"
        stem.with_suffix(".wav").write_bytes(audio_bytes)
        stem.with_suffix(".txt").write_text(text, encoding="utf-8")
    except Exception as e:
        log.warning("[CAPTURES] persist failed: %s", e)

@app.get("/captures/feed")
async def captures_list(device: str = None, type: str = None):
    """Read-only feed of device artifacts (audio/transcripts/images), grouped
    under date headers (Today/Yesterday/'Wed, Jul 15', newest first, Today open).
    Grouping key = file mtime in server local time, computed here — no schema, no
    DB, just the directory walk. Filters apply before grouping, so empty days
    drop out and counts recount. Behind the portal auth gate."""
    items = captures_feed.feed(device=device, type=type)
    return {"groups": captures_feed.group_by_day(items),
            "devices": captures_feed.devices()}

@app.get("/captures/file/{name}")
async def captures_file(name: str):
    """Serve a capture from where it already lives — no copies. Auth-gated by the
    middleware; path-traversal is refused (only files inside the store resolve)."""
    p = captures_feed.resolve(name)
    if p is None:
        raise HTTPException(404, "capture not found")
    return FileResponse(p)

@app.get("/chats/feed")
async def chats_list():
    """Read-only chat-session history grouped by date (Today/Yesterday/'Wed, Jul
    15', newest first, Today open). One entry per session: timestamp, source
    (portal/iris/dio), first user line as preview, turn count. Behind the portal
    auth gate. Full turns are fetched per session via /chats/session."""
    return {"groups": chat_log.group_by_day(chat_log.sessions())}

@app.get("/chats/session/{name}")
async def chats_session(name: str):
    """Full transcript (user + Phoebe turns) for one session — read-only,
    traversal-refused, auth-gated."""
    turns = chat_log.transcript(name)
    if turns is None:
        raise HTTPException(404, "session not found")
    return {"turns": turns}

@app.get("/")
async def index():
    return Response(
        content=(ROOT / "static" / "index.html").read_text(encoding="utf-8"),
        media_type="text/html",
    )

_MORPHEUS_LOCAL_ADDRS = frozenset({"127.0.0.1", "::1", "localhost"})


def _morpheus_floor_gate(positive: str, negative: str, request: Request) -> None:
    """SHARED safety gate for ALL Morpheus generation (txt2img / edit / video) —
    one implementation, not per-endpoint copies, so they can never drift apart.
    Order: hardcoded FLOOR (no off switch, both fields) → localhost interlock
    (permissive collapses to strict off-localhost) → profile check (both fields).
    Raises HTTPException(403) with the standard refusal on any violation. Logs
    field/category only — NEVER prompt text."""
    fields = ((positive, "positive"), (negative, "negative"))
    # ── FLOOR — hardcoded, always first, no off switch, profile-independent ──
    for field, which in fields:
        if not field:
            continue
        floor_cat = morpheus.floor_check(field)
        if floor_cat:
            log.warning("[safety] floor-blocked (%s) — category: %s", which, floor_cat)
            raise HTTPException(403, detail="Content policy: prompt not permitted")
    # ── Localhost interlock — permissive latitude auto-collapses off-localhost ──
    forced_denylist = None
    if morpheus.ACTIVE_PROFILE == "permissive":
        client_host = (request.client.host if request.client else None) or ""
        if client_host not in _MORPHEUS_LOCAL_ADDRS:
            forced_denylist = morpheus.STRICT_DENYLIST
            log.warning("[safety] permissive active but non-local request from %r — forcing strict", client_host)
    # ── Profile check — denylist applies to the negative too ───────────────────
    for field, which in fields:
        if not field:
            continue
        if not morpheus.profile_check(field, denylist=forced_denylist):
            label = morpheus.ACTIVE_PROFILE + (" [forced strict by interlock]" if forced_denylist else "")
            log.warning("[safety] profile-blocked (%s) — profile: %s", which, label)
            raise HTTPException(403, detail="Content policy: prompt not permitted")


# ── generate_video tool plumbing ─────────────────────────────────────────────
# The render evicts Ollama, so a tool call must NOT start it inline (that would
# kill Hermes' follow-up reply). The tool QUEUES params here; _fire_pending_video()
# starts them after the chat turn is fully composed.
_pending_video_params: dict = {}   # job_id -> params


def _tool_generate_video(args: dict) -> str:
    """Hermes tool handler: floor-gate + queue a video render, return a status line.
    Floor is the same hardcoded check as the HTTP path (Hermes runs local on Nyx)."""
    global _video_seq
    prompt = (args.get("prompt") or args.get("positive") or "").strip()
    if not prompt:
        return "I need a description of the video you'd like me to make."
    preset = args.get("preset", morpheus.DEFAULT_VIDEO_PRESET)
    if preset not in morpheus.VIDEO_PRESETS:
        preset = morpheus.DEFAULT_VIDEO_PRESET
    if morpheus.floor_check(prompt) or not morpheus.profile_check(prompt):
        log.warning("[safety] video(tool) blocked")
        return "I can't make that one — it's outside what I'm allowed to generate."
    params = {"positive": prompt, "negative": "", "preset": preset, "seed": -1}
    src = (args.get("source_job_id") or "").strip()
    if src:
        if not (len(src) == 36 and all(c in "0123456789abcdef-" for c in src)):
            return "That source-image id isn't valid."
        sp = morpheus.IMAGE_DIR / f"{src}.png"
        if sp.resolve().parent != morpheus.IMAGE_DIR.resolve() or not sp.exists():
            return "I couldn't find that image to animate."
        job_id = morpheus.create_job()
        params["_comfy_image"] = morpheus.prepare_video_source(str(sp), job_id)
    else:
        job_id = morpheus.create_job()
    _video_seq += 1
    eta = morpheus.video_eta(preset)
    morpheus.jobs[job_id].update(kind="video", preset=preset, eta_s=eta, created_seq=_video_seq)
    _pending_video_params[job_id] = params
    mins = max(1, round(eta / 60))
    return (f"Rendering started (job {job_id[:8]}, {morpheus.VIDEO_PRESETS[preset]['label']}). "
            f"About {mins} minute{'s' if mins != 1 else ''}; I'll be offline for chat on the GPU "
            f"until it finishes.")


def _fire_pending_video() -> None:
    """Start renders queued by generate_video this turn — AFTER the reply is composed,
    so the eviction never kills Hermes mid-response."""
    for jid, params in list(_pending_video_params.items()):
        del _pending_video_params[jid]
        asyncio.create_task(morpheus.run_video(jid, params))

# ── Morpheus image generation ─────────────────────────────────────────
# ── Morpheus Edit Mode (img2img) — Phase 1: upload + validation ──────────────
# Uploads are validated by DECODE (magic-byte equivalent — never by extension or
# client MIME), re-encoded through Pillow to a clean RGB PNG (strips EXIF and
# neutralizes malformed-file tricks), and staged in an out-of-repo scratch dir
# (~/ph3b3_data/edit_scratch/ — ph3b3_data/ is gitignored and outside the repo).
# The original upload bytes never reach ComfyUI.
EDIT_SCRATCH      = Path.home() / "ph3b3_data" / "edit_scratch"
_EDIT_MAX_BYTES   = 15 * 1024 * 1024        # 15 MB
_EDIT_MAX_DIM     = 4096                     # long-edge cap; larger inputs are downscaled
_EDIT_ALLOWED_FMT = {"PNG", "JPEG", "WEBP"}
_EDIT_SCRATCH_TTL = 3600                     # 1 hour
_EDIT_MAX_PENDING = 3                         # concurrent pending edit jobs per session
_EDIT_PENDING_STATES = frozenset(
    {"queued", "evicting", "starting", "loading", "sampling"})


def _edit_session_key(request: Request) -> str:
    """Stable per-caller key for edit rate-limiting: panel session cookie if the
    caller logged in via /login, else the Basic-auth user, else the client host."""
    tok = request.cookies.get(_SESSION_COOKIE, "")
    if tok and tok in _sessions:
        return "sess:" + tok
    if request.headers.get("Authorization", "").startswith("Basic "):
        return "basic:" + AUTH_USER
    return "host:" + ((request.client.host if request.client else "") or "?")


def _edit_pending_count(session_key: str) -> int:
    """Count this session's edit jobs still in flight (not done/error)."""
    return sum(
        1 for j in morpheus.jobs.values()
        if j.get("kind") == "edit" and j.get("session") == session_key
        and j.get("state") in _EDIT_PENDING_STATES
    )


def _edit_scratch_sweep() -> int:
    """Delete scratch uploads older than the TTL. Returns count removed."""
    if not EDIT_SCRATCH.exists():
        return 0
    cutoff = time.time() - _EDIT_SCRATCH_TTL
    removed = 0
    for p in EDIT_SCRATCH.glob("*.png"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    return removed


@app.post("/image/edit/upload")
async def edit_upload(file: UploadFile = File(...)):
    """Validate an image for img2img editing and stage a clean copy.

    Returns {upload_id, width, height}. Auth is enforced by the global
    session/basic-auth middleware — no anonymous upload surface.
    """
    _edit_scratch_sweep()  # opportunistic TTL cleanup
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(raw) > _EDIT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file too large: {len(raw)} bytes (max {_EDIT_MAX_BYTES})",
        )

    # Validate by structural decode — extension and client MIME are never trusted.
    try:
        Image.open(BytesIO(raw)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="not a decodable image")

    # verify() consumes the object; re-open to read format and pixels.
    try:
        img = Image.open(BytesIO(raw))
        fmt = (img.format or "").upper()
        if fmt not in _EDIT_ALLOWED_FMT:
            raise HTTPException(
                status_code=400,
                detail=f"unsupported format {fmt or 'unknown'}; allowed: PNG, JPEG, WebP",
            )
        img = img.convert("RGB")   # drops alpha/palette + EXIF; forces full decode
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="image could not be decoded")

    # Downscale oversized inputs, preserving aspect (long edge <= _EDIT_MAX_DIM).
    if img.width > _EDIT_MAX_DIM or img.height > _EDIT_MAX_DIM:
        img.thumbnail((_EDIT_MAX_DIM, _EDIT_MAX_DIM), Image.LANCZOS)

    EDIT_SCRATCH.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex
    out_path = EDIT_SCRATCH / f"{upload_id}.png"
    img.save(out_path, format="PNG")   # clean RGB PNG; no EXIF carried over
    log.info(f"[edit] upload {upload_id} accepted: {img.width}x{img.height} (src fmt {fmt})")
    return {"upload_id": upload_id, "width": img.width, "height": img.height}


@app.post("/image/generate")
async def image_generate(request: Request, body: dict, background_tasks: BackgroundTasks):
    positive = body.get("positive", "").strip()
    if not positive:
        raise HTTPException(400, "positive prompt is required")
    # Negative conditioning: accept `negative_prompt` (canonical) or legacy
    # `negative`. Negative conditioning is still conditioning — it goes through
    # the same safety gate below as the positive prompt.
    negative = (body.get("negative_prompt") or body.get("negative") or "").strip()

    # Safety: FLOOR → interlock → profile (shared gate, identical for all Morpheus gen).
    _morpheus_floor_gate(positive, negative, request)

    params = {
        "positive":  positive,
        "negative":  negative,
        "width":     int(body.get("width",  1024)),
        "height":    int(body.get("height", 1024)),
        "steps":     int(body.get("steps",  morpheus.SDXL_STEPS)),
        "seed":      int(body.get("seed",   -1)),
        "ckpt_name": body.get("ckpt_name",  morpheus.SDXL_CKPT),
    }
    job_id = morpheus.create_job()
    background_tasks.add_task(morpheus.run_generation, job_id, params)
    return {"job_id": job_id}


@app.post("/image/edit/run")
async def image_edit_run(request: Request, body: dict, background_tasks: BackgroundTasks):
    # upload_id is used to build a path — accept ONLY the 32-hex UUID we minted,
    # so it can never traverse out of the scratch dir.
    upload_id = (body.get("upload_id") or "").strip()
    if not (len(upload_id) == 32 and all(c in "0123456789abcdef" for c in upload_id)):
        raise HTTPException(400, "valid upload_id is required")
    src = EDIT_SCRATCH / f"{upload_id}.png"
    if not src.exists():
        raise HTTPException(404, "upload not found or expired — re-upload the image")

    positive = (body.get("prompt") or body.get("positive") or "").strip()
    if not positive:
        raise HTTPException(400, "prompt is required")
    negative = (body.get("negative_prompt") or body.get("negative") or "").strip()

    # Safety: FLOOR → interlock → profile (shared gate, identical for all Morpheus gen).
    _morpheus_floor_gate(positive, negative, request)

    try:
        strength = float(body.get("strength", 0.45))
    except (TypeError, ValueError):
        raise HTTPException(400, "strength must be a number")
    strength = max(morpheus.EDIT_STRENGTH_MIN, min(morpheus.EDIT_STRENGTH_MAX, strength))  # clamp

    params = {
        "positive":  positive,
        "negative":  negative,
        "strength":  strength,
        "seed":      int(body.get("seed",  -1)),
        "steps":     int(body.get("steps", morpheus.SDXL_STEPS)),
        "ckpt_name": body.get("ckpt_name", morpheus.SDXL_CKPT),
        "image_path": str(src),
        "upload_id": upload_id,
    }
    # ── Rate limit — cap concurrent pending edit jobs per session ──────────────
    sess_key = _edit_session_key(request)
    if _edit_pending_count(sess_key) >= _EDIT_MAX_PENDING:
        raise HTTPException(
            429,
            f"too many pending edit jobs (max {_EDIT_MAX_PENDING}); wait for one to finish",
        )

    job_id = morpheus.create_job()
    morpheus.jobs[job_id].update(kind="edit", session=sess_key)
    background_tasks.add_task(morpheus.run_edit, job_id, params)
    return {"job_id": job_id}


@app.get("/image/status/{job_id}")
async def image_status(job_id: str):
    if job_id not in morpheus.jobs:
        raise HTTPException(404, "Unknown job")
    return morpheus.jobs[job_id]


@app.get("/image/file/{job_id}")
async def image_file(job_id: str, download: int = 0, format: str = "png"):
    path = morpheus.IMAGE_DIR / f"{job_id}.png"
    if not path.exists():
        raise HTTPException(404, "Image not found")
    fmt = format.lower()
    if fmt not in ("png", "jpeg", "webp"):
        raise HTTPException(400, "format must be png, jpeg, or webp")
    # Fast path: PNG inline display (no conversion, no DB lookup)
    if fmt == "png" and not download:
        return FileResponse(str(path), media_type="image/png")
    # Build provenance filename from DB
    meta = await asyncio.to_thread(morpheus._db_meta, job_id)
    if meta:
        filename = f"ph3b3_{morpheus._slug(meta['prompt'])}_{meta['seed']}.{fmt}"
    else:
        filename = f"ph3b3_{job_id}.{fmt}"
    if fmt == "png":
        data = await asyncio.to_thread(path.read_bytes)
        ct = "image/png"
    else:
        data, ct = await asyncio.to_thread(morpheus.convert_image, path, fmt)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if download else {}
    return Response(content=data, media_type=ct, headers=headers)


@app.get("/image/gallery")
async def image_gallery(n: int = 20):
    rows = await asyncio.to_thread(morpheus._db_gallery, n)
    return {"images": rows}


# ══ Video generation ("Oneiroi") endpoints — Phase 3 ════════════════════════
# Async job model (returns job_id + ETA immediately); the render runs in the
# background under morpheus.gpu_lock. Prompt goes through the SAME safety floor as
# image gen. NOT registered as a Hermes tool yet — that + the input-image floor
# gate + values audit are Phase 4 (Captain sign-off).
_video_seq = 0
_VIDEO_ACTIVE = {"queued", "evicting", "starting", "loading", "rendering", "saving"}


@app.post("/morpheus/video")
async def morpheus_video(request: Request, body: dict, background_tasks: BackgroundTasks):
    global _video_seq
    positive = (body.get("positive") or body.get("prompt") or "").strip()
    if not positive:
        raise HTTPException(400, "positive prompt is required")
    negative = (body.get("negative_prompt") or body.get("negative") or "").strip()
    preset = body.get("preset", morpheus.DEFAULT_VIDEO_PRESET)
    if preset not in morpheus.VIDEO_PRESETS:
        raise HTTPException(400, f"unknown preset; choose from {list(morpheus.VIDEO_PRESETS)}")

    # Safety: FLOOR → interlock → profile (shared gate, identical for all Morpheus gen).
    _morpheus_floor_gate(positive, negative, request)

    params = {"positive": positive, "negative": negative, "preset": preset,
              "seed": int(body.get("seed", -1))}
    job_id = morpheus.create_job()
    # I2V: animate an EXISTING Morpheus render (already floored at creation). The
    # input-image floor gate for arbitrary uploads is Phase 4 — only existing
    # gallery renders are accepted here.
    src_job = (body.get("source_job_id") or "").strip()
    if src_job:
        # I2V input-image gate: accept ONLY a real gallery-render job UUID. The
        # strict UUID shape (36 chars, hex+hyphen) forbids path separators/dots,
        # so this can never traverse out of IMAGE_DIR to animate an un-floored
        # image. Existing renders were floor-passed at creation → provenance-safe.
        if not (len(src_job) == 36 and all(c in "0123456789abcdef-" for c in src_job)):
            raise HTTPException(400, "invalid source_job_id")
        src_path = morpheus.IMAGE_DIR / f"{src_job}.png"
        if not src_path.resolve().parent == morpheus.IMAGE_DIR.resolve():
            raise HTTPException(400, "invalid source_job_id")
        if not src_path.exists():
            raise HTTPException(404, "source render not found")
        params["_comfy_image"] = await asyncio.to_thread(
            morpheus.prepare_video_source, str(src_path), job_id)

    _video_seq += 1
    eta = morpheus.video_eta(preset)
    morpheus.jobs[job_id].update(kind="video", preset=preset, eta_s=eta, created_seq=_video_seq)
    background_tasks.add_task(morpheus.run_video, job_id, params)
    return {"job_id": job_id, "preset": preset, "eta_s": eta,
            "label": morpheus.VIDEO_PRESETS[preset]["label"],
            "mode": "i2v" if src_job else "t2v"}


@app.get("/morpheus/jobs/{job_id}")
async def morpheus_job_status(job_id: str):
    rec = morpheus.jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "Unknown job")
    ahead = sum(1 for r in morpheus.jobs.values()
                if r.get("kind") == "video" and r.get("state") in _VIDEO_ACTIVE
                and r.get("created_seq", 0) < rec.get("created_seq", 0))
    return {**rec, "queue_position": ahead}   # 0 = active / next up


@app.delete("/morpheus/jobs/{job_id}")
async def morpheus_job_cancel(job_id: str):
    rec = morpheus.jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "Unknown job")
    if rec.get("state") in ("done", "error", "cancelled"):
        return {"job_id": job_id, "state": rec.get("state"), "already_terminal": True}
    was_rendering = rec.get("state") == "rendering" and rec.get("prompt_id")
    rec.update(state="cancelled", error="cancelled by user")
    # Only /interrupt if THIS job is the one actually running on ComfyUI — otherwise
    # a queued cancel would kill someone else's active render. run_video's finally
    # still frees VRAM; the queued-cancel case bails right after acquiring the lock.
    if was_rendering:
        async with httpx.AsyncClient() as http:
            try:
                await http.post(f"{morpheus.COMFY_HOST}/interrupt", timeout=10.0)
                await http.post(f"{morpheus.COMFY_HOST}/free",
                                json={"unload_models": True, "free_memory": True}, timeout=10.0)
            except Exception as e:
                log.warning("video cancel interrupt/free failed: %s", e)
    return {"job_id": job_id, "state": "cancelled", "interrupted": bool(was_rendering)}


async def _resume_read_input(file, resume_text):
    """Return (text, source_flags, error). Pasted text → source_flags None (pure
    plain-text mode). A file → parsed text + its source-level format flags. On
    failure → (None, None, message)."""
    if resume_text and resume_text.strip():
        return resume_text, None, None
    if file is None or not getattr(file, "filename", ""):
        return None, None, "Provide either resume_text or a .txt/.docx/.pdf file."
    data = await file.read()
    if len(data) > 5_000_000:
        return None, None, "File too large (max 5 MB)."
    suffix = Path(file.filename).suffix.lower() or ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        text, flags = resume.parse_resume_file(tmp_path)
    finally:
        os.unlink(tmp_path)
    if text is None:
        return None, None, "; ".join(flags) or "Could not parse the file."
    return text, flags, None


async def _resolve_jd(job_description, job_url):
    """Return (jd_text, error). Pasted JD text wins; otherwise best-effort URL
    fetch through Ariadne's validation gate (outbound-only to the public URL).
    A failed/unreadable URL yields the paste-the-text fallback error."""
    if job_description and job_description.strip():
        return job_description, None
    if job_url and job_url.strip():
        jd = await asyncio.to_thread(resume.fetch_jd, job_url)
        if jd.startswith("["):
            return "", jd.strip("[]")
        return jd, None
    return "", None


@app.post("/resume/analyze")
async def resume_analyze_endpoint(
    file: UploadFile = File(None),
    resume_text: str = Form(""),
    job_description: str = Form(""),
    job_url: str = Form(""),
):
    text, flags, err = await _resume_read_input(file, resume_text)
    if err:
        raise HTTPException(400, err)
    jd, jd_err = await _resolve_jd(job_description, job_url)
    if jd_err:
        raise HTTPException(400, jd_err)
    analysis = await asyncio.to_thread(resume.analyze_resume, text, jd, flags)
    return {"analysis": analysis}


@app.post("/resume/build")
async def resume_build_endpoint(
    file: UploadFile = File(None),
    resume_text: str = Form(""),
    job_description: str = Form(""),
    job_url: str = Form(""),
):
    text, flags, err = await _resume_read_input(file, resume_text)
    if err:
        raise HTTPException(400, err)
    jd, jd_err = await _resolve_jd(job_description, job_url)
    if jd_err:
        raise HTTPException(400, jd_err)
    result = await asyncio.to_thread(resume.build_ats_resume, text, jd)
    return {"result": result}


@app.get("/resume/file/{rid}")
async def resume_file(rid: str):
    """Download a built ATS resume .docx. IDs are validated in the module
    (12-hex, path-confined to the resumes dir)."""
    path = resume.get_resume_path(rid)
    if not path:
        raise HTTPException(404, "Resume not found")
    return FileResponse(
        str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="ats_resume_{rid}.docx"'},
    )


@app.get("/morpheus/video/file/{job_id}")
async def morpheus_video_file(job_id: str, download: int = 0):
    path = morpheus.VIDEO_DIR / f"{job_id}.mp4"
    if not path.exists():
        raise HTTPException(404, "Video not found")
    headers = {"Content-Disposition": f'attachment; filename="ph3b3_{job_id}.mp4"'} if download else {}
    return FileResponse(str(path), media_type="video/mp4", headers=headers)


@app.get("/morpheus/video/thumb/{job_id}")
async def morpheus_video_thumb(job_id: str):
    path = morpheus.VIDEO_DIR / f"{job_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(str(path), media_type="image/jpeg")


@app.delete("/image/{job_id}")
async def image_delete(job_id: str):
    return await asyncio.to_thread(morpheus._db_delete, job_id)


def _prune_image_subdirs() -> None:
    """Remove empty subdirectories inside IMAGE_DIR. Never touches IMAGE_DIR itself."""
    root = morpheus.IMAGE_DIR.resolve()
    for child in sorted(root.iterdir(), reverse=True):
        if child.is_dir():
            try:
                if not any(child.iterdir()):
                    child.rmdir()
            except Exception:
                pass


@app.post("/morpheus/delete_all")
async def morpheus_delete_all():
    job_ids = await asyncio.to_thread(morpheus._db_all_job_ids)
    if not job_ids:
        return {"deleted": 0, "failed": [], "freed_bytes": 0}
    results = []
    for job_id in job_ids:
        r = await asyncio.to_thread(morpheus._db_delete, job_id)
        results.append((job_id, r))
    await asyncio.to_thread(_prune_image_subdirs)
    deleted = sum(1 for _, r in results if r["ok"])
    failed = [{"job_id": jid, "reason": r["reason"]} for jid, r in results if not r["ok"]]
    freed = sum(r.get("freed_bytes", 0) for _, r in results if r["ok"])
    return {"deleted": deleted, "failed": failed, "freed_bytes": freed}


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

if __name__ == "__main__":
    log.info(f"Ph3b3 starting — {HOST}:{PORT}")
    ssl_kwargs = {}
    if SSL_CERT and SSL_KEY:
        ssl_kwargs = {"ssl_certfile": SSL_CERT, "ssl_keyfile": SSL_KEY}
        log.info(f"HTTPS enabled — cert: {SSL_CERT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning",
                timeout_keep_alive=30, **ssl_kwargs)
