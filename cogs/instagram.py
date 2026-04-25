import discord
from discord.ext import commands
import re
import asyncio
import aiohttp
from io import BytesIO
from yt_dlp import YoutubeDL
from data.variables import Timestamp

INSTAGRAM_PATTERN = re.compile(
    r"(https?://(?:www\.|m\.)?instagram\.com/(?:p|reel|reels|tv)/[A-Za-z0-9_-]+)"
)

# Instagram requires cookies for most content since 2023.
# Place a cookies.txt (Netscape format) in config/ — same file used by music.
# Without it, public reels may still work but photos and carousels often won't.
YDL_OPTS = {
    "quiet":              False,
    "no_warnings":        False,
    "skip_download":      True,
    "noplaylist":         False,   # False so carousel entries are fetched
    "cookiefile":         "config/cookies.txt",
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.instagram.com/",
    },
    # Use "best" without video requirement so image posts don't raise ExtractorError
    "format": "best",
    "source_address": "0.0.0.0",
}

# Headers to use when downloading the actual media file
DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.instagram.com/",
}

MAX_BYTES  = 24 * 1024 * 1024
CHUNK_SIZE = 512 * 1024


class Instagram(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        match = INSTAGRAM_PATTERN.search(message.content)
        if not match:
            return

        url = match.group(1).split("?")[0]

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        try:
            info = await asyncio.to_thread(self._extract, url)
        except Exception as e:
            print(f"{Timestamp()} [Instagram] extract exception: {e}")
            await message.channel.send("⚠️ Could not extract media from that link.")
            return

        if not info:
            await message.channel.send("⚠️ Could not extract media from that link.")
            return

        # Carousels come back as a playlist with entries
        entries = info.get("entries")
        if entries:
            entries = [e for e in entries if e]
        else:
            entries = [info]

        # Label based on first entry
        first = entries[0]
        label = "reel" if self._is_video(first) else "photo"
        if len(entries) > 1:
            label = "post"
        header = f"**{message.author.mention} shared an Instagram {label}**"

        files = []
        for entry in entries[:10]:
            media_url, ext = self._pick_url(entry)
            if not media_url:
                print(f"{Timestamp()} [Instagram] no URL found for entry: {entry.get('id', '?')}")
                continue
            buf = await self._download(media_url)
            if buf:
                files.append(discord.File(buf, filename=f"instagram.{ext}"))
            else:
                print(f"{Timestamp()} [Instagram] download failed for {media_url[:80]}")

        if not files:
            await message.channel.send(f"{header}\nCould not download the media.")
            return

        try:
            await message.channel.send(content=header, files=files)
        except discord.HTTPException as e:
            await message.channel.send(f"{header}\nUpload failed: {e}")
        finally:
            for f in files:
                try:
                    f.fp.close()
                except Exception:
                    pass

    async def _download(self, url: str) -> BytesIO | None:
        async with aiohttp.ClientSession(headers=DOWNLOAD_HEADERS) as session:
            # HEAD first to avoid downloading something too large
            try:
                async with session.head(url, allow_redirects=True,
                                        timeout=aiohttp.ClientTimeout(total=10)) as head:
                    size = int(head.headers.get("Content-Length", 0))
                    if size > MAX_BYTES:
                        print(f"{Timestamp()} [Instagram] file too large: {size // (1024*1024)} MB")
                        return None
            except Exception:
                pass  # HEAD failed, try GET anyway

            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        print(f"{Timestamp()} [Instagram] HTTP {resp.status} for {url[:80]}")
                        return None
                    buf = BytesIO()
                    async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                        buf.write(chunk)
                        if buf.tell() > MAX_BYTES:
                            buf.close()
                            print(f"{Timestamp()} [Instagram] file exceeded size limit mid-download")
                            return None
                    buf.seek(0)
                    return buf
            except Exception as e:
                print(f"{Timestamp()} [Instagram] download error: {e}")
                return None

    def _extract(self, url: str) -> dict | None:
        with YoutubeDL(YDL_OPTS) as ydl:
            try:
                return ydl.extract_info(url, download=False)
            except Exception as e:
                print(f"{Timestamp()} [Instagram] yt-dlp error: {e}")
                return None

    def _is_video(self, info: dict) -> bool:
        if info.get("ext") in ("mp4", "mov", "webm", "mkv"):
            return True
        if "formats" in info:
            return any(
                f.get("vcodec") not in (None, "none")
                for f in info["formats"] if f.get("url")
            )
        return False

    def _pick_url(self, info: dict) -> tuple[str | None, str]:
        """Return (url, extension) for the best available media in this entry."""

        # Direct URL with a known video extension
        if info.get("url") and info.get("ext") in ("mp4", "mov", "webm", "mkv"):
            return info["url"], info["ext"]

        # Pick from formats list
        if "formats" in info:
            fmts = info["formats"]

            # Best combined audio+video
            combined = [
                f for f in fmts
                if f.get("url")
                and f.get("vcodec") not in (None, "none")
                and f.get("acodec") not in (None, "none")
            ]
            if combined:
                best = max(combined, key=lambda f: f.get("height") or 0)
                return best["url"], best.get("ext", "mp4")

            # Video-only fallback
            video = [
                f for f in fmts
                if f.get("url") and f.get("vcodec") not in (None, "none")
            ]
            if video:
                best = max(video, key=lambda f: f.get("height") or 0)
                return best["url"], best.get("ext", "mp4")

        # Any direct URL at all (covers some photo formats yt-dlp returns)
        if info.get("url"):
            ext = info.get("ext", "jpg")
            return info["url"], ext

        # Thumbnail as last resort (photos often only have this)
        thumbs = info.get("thumbnails") or []
        # yt-dlp orders thumbnails smallest-first, so take the last one
        for thumb in reversed(thumbs):
            if thumb.get("url"):
                return thumb["url"], "jpg"

        return None, "jpg"


async def setup(bot):
    await bot.add_cog(Instagram(bot))
