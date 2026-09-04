"""
Spotify link support.

Spotify's API never gives out actual playable audio — it's DRM-locked even
with valid credentials. So a Spotify link can never be the audio source
itself. What this module does instead is read track/playlist/album metadata
from Spotify's official Web API, turn each track into a "Artist - Title"
search string, and hand those strings back to the caller (cogs/music.py),
which then searches YouTube for each one exactly like a normal /play text
search. Functionally, a Spotify link becomes a fancy way of building a
queue — playback itself still comes from YouTube.

Requires two environment variables:
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET

These come from a free Spotify Developer app (client-credentials flow —
no user login involved, just app-level access to public catalog data).
If they're not set, is_spotify_url() / resolve() just quietly do nothing
and Spotify links get treated as a normal search query instead.
"""

import asyncio
import base64
import json
import os
import re
import time
import aiohttp
from data.variables import Timestamp

CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE  = "https://api.spotify.com/v1"

_TRACK_RE    = re.compile(r"open\.spotify\.com/(?:intl-\w+/)?track/([A-Za-z0-9]+)")
_PLAYLIST_RE = re.compile(r"open\.spotify\.com/(?:intl-\w+/)?playlist/([A-Za-z0-9]+)")
_ALBUM_RE    = re.compile(r"open\.spotify\.com/(?:intl-\w+/)?album/([A-Za-z0-9]+)")
_ARTIST_RE   = re.compile(r"open\.spotify\.com/(?:intl-\w+/)?artist/([A-Za-z0-9]+)")
_SHORT_RE    = re.compile(r"spotify\.link/")

# Cached app access token — client-credentials tokens are shared across all
# guilds/users, there's no per-user auth involved here.
_token: str | None = None
_token_expires_at: float = 0.0


async def _resolve_short_link(url: str) -> str:
    """spotify.link/xxxx short links just redirect to a normal open.spotify.com URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return str(resp.url)


async def is_spotify_url(url: str) -> bool:
    if _SHORT_RE.search(url):
        try:
            url = await _resolve_short_link(url)
        except Exception:
            return False
    return bool(
        _TRACK_RE.search(url) or _PLAYLIST_RE.search(url)
        or _ALBUM_RE.search(url) or _ARTIST_RE.search(url)
    )


async def _get_token() -> str | None:
    global _token, _token_expires_at

    if not CLIENT_ID or not CLIENT_SECRET:
        print(f"{Timestamp()} [Spotify] SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET not set — Spotify links disabled.")
        return None

    if _token and time.time() < _token_expires_at:
        return _token

    auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, headers=headers, data=data,
                                     timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    print(f"{Timestamp()} [Spotify] Token request failed: HTTP {resp.status}")
                    return None
                payload = await resp.json()
    except Exception as e:
        print(f"{Timestamp()} [Spotify] Token request error: {e}")
        return None

    _token = payload.get("access_token")
    # Refresh a bit early so we never hand out a token that's about to expire mid-request
    _token_expires_at = time.time() + payload.get("expires_in", 3600) - 60
    return _token


async def _api_get(path: str, params: dict | None = None) -> dict | None:
    token = await _get_token()
    if not token:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_BASE}{path}" if path.startswith("/") else path,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    print(f"{Timestamp()} [Spotify] API error {resp.status} for {path}")
                    return None
                return await resp.json()
    except Exception as e:
        print(f"{Timestamp()} [Spotify] API request error: {e}")
        return None


_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
    re.DOTALL
)


async def _scrape_embed_playlist(playlist_id: str) -> list[str]:
    url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    print(f"{Timestamp()} [Spotify] Embed page HTTP {resp.status} for playlist {playlist_id}")
                    return []
                html = await resp.text()
    except Exception as e:
        print(f"{Timestamp()} [Spotify] Embed page fetch error: {e}")
        return []

    match = _NEXT_DATA_RE.search(html)
    if not match:
        print(f"{Timestamp()} [Spotify] Could not find embed data for playlist {playlist_id}")
        return []

    try:
        data = json.loads(match.group(1))
        tracks = data["props"]["pageProps"]["state"]["data"]["entity"]["trackList"]
    except (KeyError, TypeError, json.JSONDecodeError):
        print(f"{Timestamp()} [Spotify] Unexpected embed page structure for playlist {playlist_id}")
        return []

    queries = []
    for track in tracks:
        title = track.get("title")
        subtitle = track.get("subtitle")
        if title and subtitle:
            queries.append(f"{subtitle} - {title}")
        elif title:
            queries.append(title)
    return queries


def _track_query(track: dict | None) -> str | None:
    if not track:
        return None
    name = track.get("name")
    if not name:
        return None
    artists = [a.get("name", "") for a in (track.get("artists") or []) if a.get("name")]
    artist_str = ", ".join(artists)
    return f"{artist_str} - {name}" if artist_str else name


ARTIST_ALBUM_CAP = 8
ARTIST_TRACK_CAP = 60


async def _artist_tracks(artist_id: str) -> list[str]:
    """Spotify removed Get Artist's Top Tracks in the Feb 2026 API cut, and
    Get Artist's Albums is unreliable for apps without extended quota access
    (it 400s with a misleading "Invalid limit" message instead of a real
    permissions error). Search is available to every app tier, so this just
    searches for tracks by the artist's name instead — up to 3 pages, since
    /search caps at 10 results per page since Feb 2026."""
    artist = await _api_get(f"/artists/{artist_id}", {"market": "US"})
    if not artist or not artist.get("name"):
        return []
    name = artist["name"]

    seen_ids = set()
    queries = []
    for page in range(3):
        data = await _api_get("/search", {
            "q": f'artist:"{name}"',
            "type": "track",
            "market": "US",
            "limit": 10,
            "offset": page * 10,
        })
        items = (data or {}).get("tracks", {}).get("items", [])
        if not items:
            break
        for track in items:
            tid = track.get("id")
            if not tid or tid in seen_ids:
                continue
            seen_ids.add(tid)
            q = _track_query(track)
            if q:
                queries.append(q)

    return queries


async def resolve(url: str) -> list[str]:
    """
    Given a Spotify track/playlist/album URL, return a list of search query
    strings ("Artist - Track") ready to be handed to Song.resolve() for a
    YouTube search. A single-item list means it was a track link.
    Returns an empty list if credentials aren't set or nothing was found.
    """
    if _SHORT_RE.search(url):
        try:
            url = await _resolve_short_link(url)
        except Exception:
            return []

    track_match    = _TRACK_RE.search(url)
    playlist_match = _PLAYLIST_RE.search(url)
    album_match    = _ALBUM_RE.search(url)
    artist_match   = _ARTIST_RE.search(url)

    if artist_match:
        return await _artist_tracks(artist_match.group(1))

    if track_match:
        data  = await _api_get(f"/tracks/{track_match.group(1)}")
        query = _track_query(data)
        return [query] if query else []

    if playlist_match:
        return await _scrape_embed_playlist(playlist_match.group(1))

    if album_match:
        queries = []
        path   = f"/albums/{album_match.group(1)}/tracks"
        params = {"limit": 50}
        while path:
            data = await _api_get(path, params)
            if not data:
                break
            for track in data.get("items", []):
                query = _track_query(track)
                if query:
                    queries.append(query)
            path   = data.get("next") or None
            params = None
        return queries

    return []


GUILDS_DIR = "data/guilds"


def is_enabled_for_guild(guild_id) -> bool:
    """Spotify link support is opt-in per server, toggled from the dashboard."""
    path = os.path.join(GUILDS_DIR, str(guild_id), "spotify.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return bool(json.load(f).get("enabled", False))
        except Exception:
            pass
    return False
