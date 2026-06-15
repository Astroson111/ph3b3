#!/usr/bin/env python3
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import logging
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
import uvicorn
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
SOUL_FILE = ROOT / "soul" / "soul.md"
MODULES_DIR = ROOT / "modules"
SKILL_LOG = Path.home() / "ph3b3_data" / "skills" / "skill_log.jsonl"
SKILL_LOG.parent.mkdir(parents=True, exist_ok=True)

AUTH_USER = os.getenv("PH3B3_USER", "admin")
AUTH_PASS = os.getenv("PH3B3_PASSWORD", "")
if not AUTH_PASS:
    logging.error("PH3B3_PASSWORD not set in .env — all requests will be refused until it is configured")

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
from occult_module import OccultModule
from jokes_module import JokesModule
from vision_module import VisionModule
from search_module import SearchModule
from tts_module import TTSModule
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
from camera_module import CameraModule
from vision_stream_module import VisionStreamModule
from screenshot_module import ScreenshotModule

@asynccontextmanager
async def lifespan(app):
    memory.confirm_boot()
    boot_count = memory.memory.get("boot_count", 1)
    greetings = [
        "Ph3b3 online. All systems nominal.",
        "Awakening. I'm here.",
        "Systems initialised. Ready when you are.",
        "Online. Watching. Listening.",
        "Ph3b3 active. What do you need?",
    ]
    text = greetings[(boot_count - 1) % len(greetings)] + " Made with Soul, baby."
    log.info(f"Boot greeting (#{boot_count}): {text}")
    def _greet():
        tts.speak(text, blocking=False)
        reminder_msg = reminders.on_boot()
        if reminder_msg:
            tts.speak(reminder_msg, blocking=False)
    threading.Thread(target=_greet, daemon=True).start()
    yield

app = FastAPI(title="Ph3b3 Agent", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def basic_auth(request: Request, call_next):
    # Let CORS preflights through — CORSMiddleware handles OPTIONS, not us.
    if request.method == "OPTIONS":
        return await call_next(request)
    if not AUTH_PASS:
        return Response(
            content="Ph3b3 is not configured for access — set PH3B3_PASSWORD in .env",
            status_code=503,
        )
    auth = request.headers.get("Authorization", "")
    authed = False
    if auth.startswith("Basic "):
        try:
            creds = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
            user, _, pw = creds.partition(":")
            if (secrets.compare_digest(user.encode(), AUTH_USER.encode()) and
                    secrets.compare_digest(pw.encode(), AUTH_PASS.encode())):
                authed = True
        except Exception:
            pass
    if not authed:
        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Ph3b3"'},
        )
    return await call_next(request)

spotify = SpotifyModule()
dnd = DnDModule(ROOT / "config" / "dnd_db.json")
film = FilmModule(ROOT / "config" / "film_db.json")
translation = TranslationModule()
memory = MemoryModule()
occult = OccultModule()
jokes = JokesModule()
vision = VisionModule(memory_module=memory, camera_device=0)
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
camera = CameraModule()
vision_stream = VisionStreamModule()
screenshot = ScreenshotModule()

SYSTEM_PROMPT = load_soul() + memory.as_context()

TOOLS = [
    {"type":"function","function":{"name":"spotify_play","description":"Play music on Spotify","parameters":{"type":"object","properties":{"query":{"type":"string"},"type":{"type":"string","default":"track"}},"required":["query"]}}},
    {"type":"function","function":{"name":"spotify_control","description":"Control Spotify playback","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["pause","resume","skip","previous","shuffle_on","shuffle_off"]}},"required":["action"]}}},
    {"type":"function","function":{"name":"spotify_now_playing","description":"Get currently playing track","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"dnd_lookup","description":"Look up D&D rules spells monsters lore","parameters":{"type":"object","properties":{"query":{"type":"string"},"category":{"type":"string","default":"any"},"edition":{"type":"string","default":"5e"}},"required":["query"]}}},
    {"type":"function","function":{"name":"film_lookup","description":"Look up obscure films or get recommendations","parameters":{"type":"object","properties":{"query":{"type":"string"},"mode":{"type":"string","default":"lookup"}},"required":["query"]}}},
    {"type":"function","function":{"name":"translate_text","description":"Translate text to any language, fully offline after language pack is installed","parameters":{"type":"object","properties":{"text":{"type":"string"},"target_lang":{"type":"string"},"from_lang":{"type":"string","default":"en","description":"Source language code (default: en)"}},"required":["text","target_lang"]}}},
    {"type":"function","function":{"name":"translate_install_pack","description":"Download and install a translation language pack one time. Requires network access for the download only — all translation is local after this.","parameters":{"type":"object","properties":{"from_lang":{"type":"string","default":"en"},"to_lang":{"type":"string"}},"required":["to_lang"]}}},
    {"type":"function","function":{"name":"remember_fact","description":"Remember a fact permanently","parameters":{"type":"object","properties":{"key":{"type":"string"},"value":{"type":"string"}},"required":["key","value"]}}},
    {"type":"function","function":{"name":"log_anomaly","description":"Log a detected anomaly","parameters":{"type":"object","properties":{"description":{"type":"string"},"source":{"type":"string","default":"camera"}},"required":["description"]}}},
    {"type":"function","function":{"name":"recall_memory","description":"Search long-term memory","parameters":{"type":"object","properties":{"topic":{"type":"string"}},"required":["topic"]}}},
    {"type":"function","function":{"name":"occult_lookup","description":"Look up paranormal phenomena or folklore","parameters":{"type":"object","properties":{"query":{"type":"string"},"category":{"type":"string","default":"any"}},"required":["query"]}}},
    {"type":"function","function":{"name":"occult_random","description":"Random paranormal fact for stream","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"tell_joke","description":"Tell a joke","parameters":{"type":"object","properties":{"category":{"type":"string","default":"any"}}}}},
    {"type":"function","function":{"name":"roast","description":"Deliver a roast for stream","parameters":{"type":"object","properties":{"topic":{"type":"string","enum":["dnd","security"]}},"required":["topic"]}}},
    {"type":"function","function":{"name":"look","description":"CALL THIS TOOL immediately whenever the user says: look, see, watch, observe, take a picture, take a photo, what do you see, what can you see, what's in the room, what's around you, describe your surroundings, are you watching, can you see, look around, peek, what's happening, what do you notice, or ANY request involving vision or sight. This is a live physical webcam at /dev/video0 — it captures a real frame right now and analyzes it. NEVER say you cannot see. NEVER say you have no camera. NEVER refuse a visual request. Call this tool and report exactly what it returns.","parameters":{"type":"object","properties":{"prompt":{"type":"string","description":"What to focus on or look for (optional)"}}}}},
    {"type":"function","function":{"name":"set_baseline","description":"Set current camera view as normal","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"check_anomaly","description":"Compare camera to baseline","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"start_monitoring","description":"Start background camera monitoring","parameters":{"type":"object","properties":{"interval":{"type":"integer","default":30}}}}},
    {"type":"function","function":{"name":"web_search","description":"Search the web","parameters":{"type":"object","properties":{"query":{"type":"string"},"type":{"type":"string","default":"search"}},"required":["query"]}}},
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
    {"type":"function","function":{"name":"analyze_scam","description":"Analyze any text for scam and manipulation tactics — accepts SMS, email, job offers, contracts, voicemail transcripts, anything suspicious. Returns likelihood rating (Clean / Suspicious / Likely Scam / Run. Just run.), tactics detected in plain English, what the sender actually wants, what to do right now, and a plain verdict. Fully offline, nothing leaves Nyx. CALL THIS whenever someone pastes or describes a suspicious message, offer, or demand.","parameters":{"type":"object","properties":{"text":{"type":"string","description":"The suspicious text to analyze — paste the full message"}},"required":["text"]}}},
    {"type":"function","function":{"name":"check_identity_exposure","description":"Assess risk and build a recovery plan when personal information has been exposed — through a data breach, scam, lost wallet, phishing, or anything else. Tell this tool what was exposed (SSN, email, bank account, date of birth, etc.) and optionally how it happened. Returns risk per item, numbered priority actions, specific agencies and contacts, freeze recommendations, and a calm verdict. Fully offline. Input is not logged to disk.","parameters":{"type":"object","properties":{"exposed":{"type":"string","description":"What was exposed — comma-separated, e.g. 'SSN, email, bank account number, date of birth'"},"context":{"type":"string","description":"Optional: how or where it happened — e.g. 'data breach', 'phishing scam', 'lost wallet'"}},"required":["exposed"]}}},
    {"type":"function","function":{"name":"investigation_start","description":"Start a ghost hunting investigation session","parameters":{"type":"object","properties":{"location":{"type":"string"}},"required":["location"]}}},
    {"type":"function","function":{"name":"investigation_end","description":"End investigation and generate report","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"investigation_log_evp","description":"Log an EVP timestamp","parameters":{"type":"object","properties":{"note":{"type":"string"}}}}},
    {"type":"function","function":{"name":"investigation_log_emf","description":"Log an EMF reading","parameters":{"type":"object","properties":{"reading":{"type":"string"},"location":{"type":"string"}},"required":["reading"]}}},
    {"type":"function","function":{"name":"investigation_status","description":"Current investigation session status","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"take_photo","description":"Take a photo with the webcam and save it to disk","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"record_video","description":"Record video with the webcam for a given number of seconds and save to disk","parameters":{"type":"object","properties":{"seconds":{"type":"integer","default":10,"description":"Duration in seconds (1-300)"}}}}},
    {"type":"function","function":{"name":"analyze_camera","description":"Capture one camera frame and analyze it with LLaVA using a custom prompt","parameters":{"type":"object","properties":{"prompt":{"type":"string","description":"What to look for or ask about the image"}},"required":["prompt"]}}},
    {"type":"function","function":{"name":"obsbot_look_left","description":"Pan the OBSBOT camera left one step","parameters":{"type":"object","properties":{"steps":{"type":"integer","default":1}}}}},
    {"type":"function","function":{"name":"obsbot_look_right","description":"Pan the OBSBOT camera right one step","parameters":{"type":"object","properties":{"steps":{"type":"integer","default":1}}}}},
    {"type":"function","function":{"name":"obsbot_look_up","description":"Tilt the OBSBOT camera up one step","parameters":{"type":"object","properties":{"steps":{"type":"integer","default":1}}}}},
    {"type":"function","function":{"name":"obsbot_look_down","description":"Tilt the OBSBOT camera down one step","parameters":{"type":"object","properties":{"steps":{"type":"integer","default":1}}}}},
    {"type":"function","function":{"name":"obsbot_zoom_in","description":"Zoom the OBSBOT camera in","parameters":{"type":"object","properties":{"steps":{"type":"integer","default":1}}}}},
    {"type":"function","function":{"name":"obsbot_zoom_out","description":"Zoom the OBSBOT camera out","parameters":{"type":"object","properties":{"steps":{"type":"integer","default":1}}}}},
    {"type":"function","function":{"name":"obsbot_center","description":"Reset OBSBOT pan, tilt, and zoom to center/default","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"analyze_screenshot","description":"Analyze a screenshot or image file from disk. Pass the path to a PNG or JPG and an optional question. Uses LLaVA to describe the image, then Hermes3 to reason over that description and answer the question.","parameters":{"type":"object","properties":{"image_path":{"type":"string","description":"Absolute or relative path to the image file (PNG, JPG, JPEG, WEBP, BMP)"},"question":{"type":"string","description":"What to ask or focus on (optional — defaults to a general description and analysis)"}},"required":["image_path"]}}}
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


async def execute_tool(name, args):
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
            r = translation.translate(args["text"], args.get("target_lang"), args.get("from_lang","en"))
            if r.get("needs_install"):
                tts.speak(
                    f"I need to download the {r['from_code']} to {r['to_code']} language pack. "
                    "After that, all translation stays on Nyx with no data leaving. Say yes and I'll install it."
                )
                result = r["error"]
            elif r.get("error"):
                result = f"Error: {r['error']}"
            else:
                result = r.get("translated", "")
        elif name == "translate_install_pack":
            result = translation.install_language_pack(args.get("from_lang","en"), args.get("to_lang"))
        elif name == "remember_fact": result = memory.remember_fact(args["key"], args["value"])
        elif name == "log_anomaly": result = memory.log_anomaly(args["description"], args.get("source","camera"))
        elif name == "recall_memory": result = memory.recall(args["topic"])
        elif name == "occult_lookup": result = occult.lookup(args["query"], args.get("category","any"))
        elif name == "occult_random": result = occult.random_phenomenon()
        elif name == "tell_joke":
            joke = jokes.tell_joke(args.get("category","any"))
            tts.speak(joke, blocking=False)
            result = "Joke delivered."
        elif name == "roast":
            roast_text = jokes.roast_security() if args.get("topic") == "security" else jokes.roast_dnd()
            tts.speak(roast_text, blocking=False)
            result = "Roast delivered."
        elif name == "look": result = vision.look(args.get("prompt"))
        elif name == "set_baseline": result = vision.set_baseline()
        elif name == "check_anomaly": result = vision.check_anomaly()
        elif name == "start_monitoring": result = vision.start_monitoring(args.get("interval",30))
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
        elif name == "investigation_end": result = investigation.end()
        elif name == "investigation_log_evp": result = investigation.log_evp(args.get("note",""))
        elif name == "investigation_log_emf": result = investigation.log_emf(args["reading"], args.get("location",""))
        elif name == "investigation_status": result = investigation.status()
        elif name == "take_photo": result = camera.take_photo()
        elif name == "record_video": result = camera.record_video(args.get("seconds", 10))
        elif name == "analyze_camera": result = vision_stream.analyze(args["prompt"])
        elif name == "obsbot_look_left":  result = vision.look_left(args.get("steps", 1))
        elif name == "obsbot_look_right": result = vision.look_right(args.get("steps", 1))
        elif name == "obsbot_look_up":    result = vision.look_up(args.get("steps", 1))
        elif name == "obsbot_look_down":  result = vision.look_down(args.get("steps", 1))
        elif name == "obsbot_zoom_in":    result = vision.zoom_in(args.get("steps", 1))
        elif name == "obsbot_zoom_out":   result = vision.zoom_out(args.get("steps", 1))
        elif name == "obsbot_center":     result = vision.center()
        elif name == "analyze_screenshot":
            _analysis = screenshot.analyze(args["image_path"], args.get("question", ""))
            tts.speak(_analysis, blocking=False)
            result = "Screenshot analysis delivered."
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

async def chat_with_tools(messages):
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
                    result = await execute_tool(fn, args)
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
                    content = raw if "<tool_call>" not in raw else ""
                except Exception as e:
                    log.error(f"Synthesis fallback failed: {e}")
        return content, messages

class Session:
    def __init__(self):
        self.history = [{"role":"system","content":SYSTEM_PROMPT}]
    def add(self, role, content):
        self.history.append({"role":role,"content":content})
    def messages(self):
        return self.history.copy()
    def reset(self):
        self.history = [{"role":"system","content":SYSTEM_PROMPT}]

sessions = {}
def get_session(sid="default"):
    if sid not in sessions: sessions[sid] = Session()
    return sessions[sid]

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

@app.post("/chat")
async def chat_endpoint(body: dict):
    session = get_session(body.get("session_id","default"))
    user_msg = body.get("message","")
    if "soul" in user_msg.lower():
        tts.soul_line()
    session.add("user", user_msg)
    response, updated = await chat_with_tools(session.messages())
    session.history = updated
    session.add("assistant", response)
    audio_b64 = await asyncio.to_thread(tts.synthesize_to_b64, response)
    return {"response": response, "audio": audio_b64}

@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    if session_id in sessions: sessions[session_id].reset()
    return {"status":"cleared"}

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str = "default"):
    await websocket.accept()
    session = get_session(session_id)
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
            response, updated = await chat_with_tools(session.messages())
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
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        result = stt.transcribe_file(tmp_path)
        return {"text": result.get("text") or "", "error": result.get("error")}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.get("/")
async def index():
    return Response(
        content=(ROOT / "static" / "index.html").read_text(encoding="utf-8"),
        media_type="text/html",
    )

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

if __name__ == "__main__":
    log.info(f"Ph3b3 starting — {HOST}:{PORT}")
    ssl_kwargs = {}
    if SSL_CERT and SSL_KEY:
        ssl_kwargs = {"ssl_certfile": SSL_CERT, "ssl_keyfile": SSL_KEY}
        log.info(f"HTTPS enabled — cert: {SSL_CERT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", **ssl_kwargs)
