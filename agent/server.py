#!/usr/bin/env python3
import asyncio
import base64
import json
import logging
import os
import secrets
import sys
import tempfile
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
    logging.warning("PH3B3_PASSWORD not set in .env — web UI is unprotected")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.getenv("PH3B3_MODEL", "hermes3")
HOST = os.getenv("PH3B3_HOST", "0.0.0.0")
PORT = int(os.getenv("PH3B3_PORT", "7331"))

# CORS — explicit allowlist of browser origins permitted to call the API.
# The web UI is served by this app (same-origin) and needs no entry here;
# add LAN/Tailscale/HTTPS origins only if a *separate* front-end calls in.
# Comma-separated, e.g. "https://nyx.tailnet:7331,http://192.168.0.16:7331".
_DEFAULT_CORS = "http://localhost:7331,http://127.0.0.1:7331"
CORS_ORIGINS = [o.strip() for o in os.getenv("PH3B3_CORS_ORIGINS", _DEFAULT_CORS).split(",") if o.strip()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Ph3b3] %(message)s")
log = logging.getLogger("ph3b3")

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
from network_module import NetworkModule
from bluetooth_module import BluetoothModule
from system_module import SystemModule
from cybersec_module import CybersecModule
from investigation_module import InvestigationModule
from camera_module import CameraModule
from vision_stream_module import VisionStreamModule

app = FastAPI(title="Ph3b3 Agent", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if not AUTH_PASS:
        return await call_next(request)
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
network = NetworkModule()
bluetooth = BluetoothModule()
system = SystemModule()
cybersec = CybersecModule()
investigation = InvestigationModule()
camera = CameraModule()
vision_stream = VisionStreamModule()

SYSTEM_PROMPT = load_soul() + memory.as_context()

TOOLS = [
    {"type":"function","function":{"name":"spotify_play","description":"Play music on Spotify","parameters":{"type":"object","properties":{"query":{"type":"string"},"type":{"type":"string","default":"track"}},"required":["query"]}}},
    {"type":"function","function":{"name":"spotify_control","description":"Control Spotify playback","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["pause","resume","skip","previous","shuffle_on","shuffle_off"]}},"required":["action"]}}},
    {"type":"function","function":{"name":"spotify_now_playing","description":"Get currently playing track","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"dnd_lookup","description":"Look up D&D rules spells monsters lore","parameters":{"type":"object","properties":{"query":{"type":"string"},"category":{"type":"string","default":"any"},"edition":{"type":"string","default":"5e"}},"required":["query"]}}},
    {"type":"function","function":{"name":"film_lookup","description":"Look up obscure films or get recommendations","parameters":{"type":"object","properties":{"query":{"type":"string"},"mode":{"type":"string","default":"lookup"}},"required":["query"]}}},
    {"type":"function","function":{"name":"translate_text","description":"Translate text to any language","parameters":{"type":"object","properties":{"text":{"type":"string"},"target_lang":{"type":"string"}},"required":["text","target_lang"]}}},
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
    {"type":"function","function":{"name":"obsbot_center","description":"Reset OBSBOT pan, tilt, and zoom to center/default","parameters":{"type":"object","properties":{}}}}
]

def _log_skill(name: str, args: dict, result, success: bool) -> None:
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": name,
        "args_summary": {k: str(v)[:120] for k, v in args.items()},
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
            r = translation.translate(args["text"], args.get("target_lang"))
            result = f"Error: {r['error']}" if r.get("error") else r.get("translated", "")
        elif name == "remember_fact": result = memory.remember_fact(args["key"], args["value"])
        elif name == "log_anomaly": result = memory.log_anomaly(args["description"], args.get("source","camera"))
        elif name == "recall_memory": result = memory.recall(args["topic"])
        elif name == "occult_lookup": result = occult.lookup(args["query"], args.get("category","any"))
        elif name == "occult_random": result = occult.random_phenomenon()
        elif name == "tell_joke": result = jokes.tell_joke(args.get("category","any"))
        elif name == "roast": result = jokes.roast_security() if args.get("topic") == "security" else jokes.roast_dnd()
        elif name == "look": result = vision.look(args.get("prompt"))
        elif name == "set_baseline": result = vision.set_baseline()
        elif name == "check_anomaly": result = vision.check_anomaly()
        elif name == "start_monitoring": result = vision.start_monitoring(args.get("interval",30))
        elif name == "web_search": result = search.news(args["query"]) if args.get("type") == "news" else search.search(args["query"])
        elif name == "speak": result = tts.speak(args["text"])
        elif name == "listen":
            r = stt.listen(args.get("duration",10))
            result = f"Heard: {r.get('text','')}" if not r.get("error") else f"Error: {r['error']}"
        elif name == "anime_lookup": result = anime.lookup(args["query"], args.get("mode","lookup"))
        elif name == "anime_random": result = anime.random_rec()
        elif name == "add_story": result = stories.add_story_from_person(args["name"], args["story"])
        elif name == "recall_stories": result = stories.recall_stories(args.get("topic"))
        elif name == "add_note": result = notes.add(args["content"], args.get("tag","general"))
        elif name == "read_last_note": result = notes.read_last(args.get("tag"))
        elif name == "search_notes": result = notes.search(args["query"])
        elif name == "start_timer": result = timer.set_timer(args["name"], args["seconds"])
        elif name == "pomodoro": result = timer.pomodoro(args.get("minutes",25))
        elif name == "add_reminder": result = reminders.add(args["text"], args.get("when"), args.get("tag","general"))
        elif name == "list_reminders": result = reminders.list_pending()
        elif name == "calendar_today": result = calendar.today()
        elif name == "calendar_week": result = calendar.week()
        elif name == "weather_current": result = weather.current(args.get("location"))
        elif name == "weather_ghost_hunting": result = weather.good_for_ghost_hunting(args.get("location"))
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

async def chat_with_tools(messages):
    async with httpx.AsyncClient(timeout=120) as client:
        payload = {"model":MODEL,"messages":messages,"stream":False,"tools":TOOLS,"options":{"temperature":0.7,"num_ctx":8192}}
        response = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        response.raise_for_status()
        msg = response.json()["message"]
        loop = 0
        while msg.get("tool_calls") and loop < 5:
            loop += 1
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn = tc["function"]["name"]
                args = tc["function"]["arguments"]
                if isinstance(args, str): args = json.loads(args)
                result = await execute_tool(fn, args)
                messages.append({"role":"tool","content":str(result)})
            payload["messages"] = messages
            response = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
            response.raise_for_status()
            msg = response.json()["message"]
        return msg.get("content",""), messages

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
    return {"status":"alive","model":MODEL,"soul":SOUL_FILE.exists(),"boot":memory.memory.get("boot_count",0)}

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
    session.add("user", body.get("message",""))
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
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
