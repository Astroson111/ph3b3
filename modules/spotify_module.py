import os
import logging
import asyncio

log = logging.getLogger("ph3b3.spotify")

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    SPOTIPY_AVAILABLE = True
except ImportError:
    SPOTIPY_AVAILABLE = False
    log.warning("spotipy not installed. Run: pip install spotipy")

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "user-library-read",
]

class SpotifyModule:
    def __init__(self):
        self._sp = None
        self._mock = not SPOTIPY_AVAILABLE or not os.getenv("SPOTIPY_CLIENT_ID")
        if self._mock:
            log.info("Spotify running in MOCK mode")
        else:
            try:
                self._sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                    scope=" ".join(SCOPES),
                    open_browser=False,
                    cache_path=os.path.expanduser("~/.ph3b3_spotify_cache")
                ))
                log.info("Spotify connected")
            except Exception as e:
                log.error(f"Spotify init failed: {e}")
                self._mock = True

    async def play(self, query, search_type="track"):
        if self._mock: return f"[MOCK] Playing: {query}"
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: self._sp.search(q=query, type=search_type, limit=1))
            items = result.get(f"{search_type}s", {}).get("items", [])
            if not items: return f"Nothing found for '{query}'"
            item = items[0]
            uri = item["uri"]
            name = item.get("name", query)
            if search_type == "track":
                await loop.run_in_executor(None, lambda: self._sp.start_playback(uris=[uri]))
                artist = item["artists"][0]["name"] if item.get("artists") else ""
                return f"Playing '{name}' by {artist}"
            else:
                await loop.run_in_executor(None, lambda: self._sp.start_playback(context_uri=uri))
                return f"Playing {search_type}: {name}"
        except Exception as e:
            return f"Spotify error: {e}"

    async def control(self, action, volume=None):
        if self._mock: return f"[MOCK] Spotify: {action}"
        try:
            loop = asyncio.get_event_loop()
            actions = {
                "pause": lambda: self._sp.pause_playback(),
                "resume": lambda: self._sp.start_playback(),
                "skip": lambda: self._sp.next_track(),
                "previous": lambda: self._sp.previous_track(),
                "shuffle_on": lambda: self._sp.shuffle(True),
                "shuffle_off": lambda: self._sp.shuffle(False),
            }
            if action in actions:
                await loop.run_in_executor(None, actions[action])
                return f"Done: {action}"
            return f"Unknown action: {action}"
        except Exception as e:
            return f"Spotify error: {e}"

    async def now_playing(self):
        if self._mock: return "[MOCK] Now playing: Boards of Canada - Roygbiv"
        try:
            loop = asyncio.get_event_loop()
            current = await loop.run_in_executor(None, lambda: self._sp.currently_playing())
            if not current or not current.get("is_playing"): return "Nothing playing."
            item = current.get("item", {})
            name = item.get("name", "Unknown")
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            return f"'{name}' by {artists}"
        except Exception as e:
            return f"Spotify error: {e}"

    async def queue(self, query):
        if self._mock: return f"[MOCK] Queued: {query}"
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: self._sp.search(q=query, type="track", limit=1))
            items = result.get("tracks", {}).get("items", [])
            if not items: return f"Nothing found for '{query}'"
            item = items[0]
            await loop.run_in_executor(None, lambda: self._sp.add_to_queue(item["uri"]))
            return f"Queued '{item['name']}'"
        except Exception as e:
            return f"Spotify error: {e}"
