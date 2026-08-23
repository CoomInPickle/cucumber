"""
Deezer link support.

Unlike Spotify, Deezer's public API (api.deezer.com) requires no
authentication at all for reading catalog data — no client ID/secret,
no OAuth token. Track, album, and playlist lookups are plain GET requests.

Like Spotify, Deezer doesn't hand out freely downloadable audio, so this
module does the same thing data/spotify.py does: turn a Deezer URL into a
list of "Artist - Title" search strings, which cogs/music.py then resolves
on YouTube exactly like a normal /play text search.
"""

import re
import aiohttp
from data.variables import Timestamp

API_BASE = "https://api.deezer.com"

# Deezer URLs look like:
#   https://www.deezer.com/track/1234567890
#   https://www.deezer.com/en/album/1234567890
#   https://www.deezer.com/fr/playlist/1234567890
# Short links (what the mobile app / share sheet actually gives you):
#   https://link.deezer.com/s/34c5NsxOOiokY3YAfSvoE
_TRACK_RE    = re.compile(r"deezer\.com/(?:\w{2}/)?track/(\d+)")
_ALBUM_RE    = re.compile(r"deezer\.com/(?:\w{2}/)?album/(\d+)")
_PLAYLIST_RE = re.compile(r"deezer\.com/(?:\w{2}/)?playlist/(\d+)")
_SHORT_RE    = re.compile(r"link\.deezer\.com/")


async def _resolve_short_link(url: str) -> str:
    """link.deezer.com/s/xxxx just redirects to a normal deezer.com URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return str(resp.url)


async def is_deezer_url(url: str) -> bool:
    if _SHORT_RE.search(url):
        try:
            url = await _resolve_short_link(url)
        except Exception:
            return False
    return bool(_TRACK_RE.search(url) or _ALBUM_RE.search(url) or _PLAYLIST_RE.search(url))


async def _api_get(path: str) -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_BASE}{path}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    print(f"{Timestamp()} [Deezer] API error {resp.status} for {path}")
                    return None
                data = await resp.json()
                if isinstance(data, dict) and data.get("error"):
                    print(f"{Timestamp()} [Deezer] API returned error for {path}: {data['error']}")
                    return None
                return data
    except Exception as e:
        print(f"{Timestamp()} [Deezer] API request error: {e}")
        return None


async def _api_get_full_url(url: str) -> dict | None:
    """Same as _api_get but takes a full URL — used for the 'next' pagination
    links Deezer returns on playlist/album track listings, which are already
    complete URLs rather than API paths."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    print(f"{Timestamp()} [Deezer] Pagination error {resp.status} for {url}")
                    return None
                data = await resp.json()
                if isinstance(data, dict) and data.get("error"):
                    print(f"{Timestamp()} [Deezer] Pagination returned error for {url}: {data['error']}")
                    return None
                return data
    except Exception as e:
        print(f"{Timestamp()} [Deezer] Pagination request error: {e}")
        return None


def _track_query(track: dict | None) -> str | None:
    if not track:
        return None
    title = track.get("title")
    if not title:
        return None
    artist = (track.get("artist") or {}).get("name", "")
    return f"{artist} - {title}" if artist else title


async def resolve(url: str) -> list[str]:
    """
    Given a Deezer track/album/playlist URL, return a list of search query
    strings ("Artist - Track") ready to be handed to Song.resolve() for a
    YouTube search. A single-item list means it was a track link.
    Returns an empty list if nothing was found.
    """
    if _SHORT_RE.search(url):
        try:
            url = await _resolve_short_link(url)
        except Exception:
            return []

    track_match    = _TRACK_RE.search(url)
    album_match    = _ALBUM_RE.search(url)
    playlist_match = _PLAYLIST_RE.search(url)

    if track_match:
        data  = await _api_get(f"/track/{track_match.group(1)}")
        query = _track_query(data)
        return [query] if query else []

    if album_match or playlist_match:
        kind = "album" if album_match else "playlist"
        obj_id = (album_match or playlist_match).group(1)
        data = await _api_get(f"/{kind}/{obj_id}")
        if not data:
            return []
        tracks = (data.get("tracks") or {}).get("data", [])
        queries = [q for q in (_track_query(t) for t in tracks) if q]
        return queries

    return []