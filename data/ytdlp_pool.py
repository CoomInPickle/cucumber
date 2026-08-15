"""
Shared process pool for yt-dlp extraction.

extract_info() is CPU-heavy (big JSON parsing, format selection, regex).
Running it via asyncio.to_thread() puts it on a normal thread, which still
fights the GIL with the thread inside discord.py that sends audio frames on
a strict 20ms clock. That's what causes the stutter when a new track loads.
Running it in a separate process instead gives it real parallelism since
processes don't share a GIL.

Each worker process builds its own YoutubeDL instance once, in the pool
initializer, and reuses it for every task that lands on that worker.
"""

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor

import yt_dlp
from data.variables import Timestamp

YTDL_OPTIONS = {
    'format': 'bestaudio[abr<=96]/bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'cookiefile': 'config/cookies.txt',
    'skip_download': True,
    'socket_timeout': 10,
    'retries': 3,
    'concurrent_fragment_downloads': 4,
    'extractor_args': {
        'youtubepot-bgutilhttp': {'base_url': ['http://bgutil-provider:4416']},
    },
}

YTDL_FLAT_OPTIONS = {
    **YTDL_OPTIONS,
    'extract_flat': 'in_playlist',
}

GENERIC_OPTIONS = {
    **YTDL_OPTIONS,
    'format': 'bestvideo+bestaudio/best',
}

# Built once per worker process by _worker_init, then reused for every task
# that lands on that worker.
_ytdl = None
_ytdl_flat = None
_ytdl_generic = None


def _worker_init():
    global _ytdl, _ytdl_flat, _ytdl_generic
    _ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
    _ytdl_flat = yt_dlp.YoutubeDL(YTDL_FLAT_OPTIONS)
    _ytdl_generic = yt_dlp.YoutubeDL(GENERIC_OPTIONS)

def _worker_extract_single(query: str):
    try:
        info = _ytdl.extract_info(query, download=False)
        if info is None:
            return None
        if 'entries' in info:
            entries = [e for e in info['entries'] if e]
            return entries[0] if entries else None
        return info
    except Exception as e:
        print(f"{Timestamp()} [yt-dlp] extract error: {e}")
        return None


def _worker_extract_playlist_flat(url: str):
    try:
        info = _ytdl_flat.extract_info(url, download=False)
        if info is None:
            return []
        entries = info.get('entries', [info])
        return [e for e in entries if e]
    except Exception as e:
        print(f"{Timestamp()} [yt-dlp] playlist extract error: {e}")
        return []


def _worker_extract_generic(query: str):
    try:
        info = _ytdl_generic.extract_info(query, download=False)
        if info is None:
            return None
        if 'entries' in info:
            entries = [e for e in info['entries'] if e]
            return entries[0] if entries else None
        return info
    except Exception as e:
        print(f"{Timestamp()} [yt-dlp] generic extract error: {e}")
        return None

_pool: ProcessPoolExecutor | None = None


def get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        workers = int(os.getenv("YTDLP_WORKERS", "3"))
        _pool = ProcessPoolExecutor(max_workers=workers, initializer=_worker_init)
        print(f"{Timestamp()} [yt-dlp] Process pool started ({workers} workers)")
    return _pool


# Drop-in async replacements for the old to_thread calls.

async def extract_single(query: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(get_pool(), _worker_extract_single, query)


async def extract_playlist_flat(url: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(get_pool(), _worker_extract_playlist_flat, url)


async def extract_generic(query: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(get_pool(), _worker_extract_generic, query)