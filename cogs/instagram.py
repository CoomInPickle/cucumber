import discord
from discord.ext import commands
import re
import asyncio
import aiohttp
import os
import sys
import io as _io
import subprocess
import tempfile
from io import BytesIO
from yt_dlp import YoutubeDL
from data.variables import Timestamp

INSTAGRAM_PATTERN = re.compile(
    r"(https?://(?:www\.|m\.)?instagram\.com/(?:p|reel|reels|tv)/[A-Za-z0-9_-]+)"
)

IG_USERNAME  = os.getenv("INSTAGRAM_USERNAME")
IG_PASSWORD  = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE = f"config/ig_session_{IG_USERNAME}" if IG_USERNAME else None

YDL_OPTS = {
    "quiet":         True,
    "no_warnings":   True,
    "skip_download": True,
    "noplaylist":    False,
    "cookiefile":    "config/cookies.txt",
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.instagram.com/",
    },
    "format":         "best",
    "source_address": "0.0.0.0",
}

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


def _clean_url(url: str) -> str:
    return re.sub(r'\?.*$', '', url.strip())


def _instaloader_available() -> bool:
    try:
        import instaloader  # noqa: F401
        return True
    except ImportError:
        return False


def _merge_photo_audio(image_path: str, audio_path: str, out_path: str) -> bool:
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-loop", "1", "-i", image_path,
                "-i", audio_path,
                "-c:v", "libx264", "-tune", "stillimage",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                out_path,
            ],
            capture_output=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"{Timestamp()} [Instagram] ffmpeg merge error: {e}")
        return False


class Instagram(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._il = None

    async def cog_load(self):
        if not _instaloader_available():
            print(f"{Timestamp()} [Instagram] instaloader not installed.")
            return
        if not IG_USERNAME or not IG_PASSWORD:
            print(f"{Timestamp()} [Instagram] No IG credentials set — instaloader disabled.")
            return
        await asyncio.to_thread(self._login)

    def _login(self):
        import instaloader

        loader = instaloader.Instaloader(
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
            max_connection_attempts=1,
        )

        if SESSION_FILE and os.path.exists(SESSION_FILE):
            try:
                loader.load_session_from_file(IG_USERNAME, SESSION_FILE)
                loader.test_login()
                print(f"{Timestamp()} [Instagram] Session restored for {IG_USERNAME}.")
                self._il = loader
                return
            except Exception as e:
                print(f"{Timestamp()} [Instagram] Saved session invalid ({e}), re-logging in...")

        try:
            loader.login(IG_USERNAME, IG_PASSWORD)
            if SESSION_FILE:
                loader.save_session_to_file(SESSION_FILE)
            print(f"{Timestamp()} [Instagram] Logged in as {IG_USERNAME}.")
            self._il = loader
        except Exception as e:
            print(f"{Timestamp()} [Instagram] Login failed: {e}")

    async def _fetch_via_instaloader(self, shortcode: str) -> list[tuple[BytesIO, str]]:
        if self._il is None:
            return []

        import instaloader

        def _download():
            results = []
            old_stderr = sys.stderr
            sys.stderr = _io.StringIO()
            try:
                post = instaloader.Post.from_shortcode(self._il.context, shortcode)
                with tempfile.TemporaryDirectory() as tmpdir:
                    self._il.dirname_pattern  = tmpdir
                    self._il.filename_pattern = "{shortcode}"
                    self._il.download_post(post, target=tmpdir)

                    base_map: dict[str, dict] = {}
                    for fname in sorted(os.listdir(tmpdir)):
                        if '.' not in fname:
                            continue
                        base, ext = fname.rsplit('.', 1)
                        ext = ext.lower()
                        if ext not in ('jpg', 'jpeg', 'png', 'webp', 'mp4', 'm4a', 'aac'):
                            continue
                        base_map.setdefault(base, {})[ext] = os.path.join(tmpdir, fname)

                    for base, exts in base_map.items():
                        image_path = (exts.get('jpg') or exts.get('jpeg')
                                      or exts.get('png') or exts.get('webp'))
                        video_path = exts.get('mp4')
                        audio_path = exts.get('m4a') or exts.get('aac')

                        if video_path:
                            with open(video_path, 'rb') as fh:
                                buf = BytesIO(fh.read())
                                buf.seek(0)
                                results.append((buf, 'mp4'))
                        elif image_path and audio_path:
                            out_path = os.path.join(tmpdir, f"{base}_merged.mp4")
                            if _merge_photo_audio(image_path, audio_path, out_path):
                                with open(out_path, 'rb') as fh:
                                    buf = BytesIO(fh.read())
                                    buf.seek(0)
                                    results.append((buf, 'mp4'))
                            else:
                                with open(image_path, 'rb') as fh:
                                    buf = BytesIO(fh.read())
                                    buf.seek(0)
                                    results.append((buf, 'jpg'))
                        elif image_path:
                            with open(image_path, 'rb') as fh:
                                buf = BytesIO(fh.read())
                                buf.seek(0)
                                results.append((buf, 'jpg'))

            except Exception as e:
                print(f"{Timestamp()} [Instagram] instaloader error: {e}", file=old_stderr)
            finally:
                sys.stderr = old_stderr
            return results

        return await asyncio.to_thread(_download)

    def _extract_ytdlp(self, url: str) -> dict | None:
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
        if info.get("url") and info.get("ext") in ("mp4", "mov", "webm", "mkv"):
            return info["url"], info["ext"]

        if "formats" in info:
            fmts = info["formats"]

            combined = [
                f for f in fmts
                if f.get("url")
                and f.get("vcodec") not in (None, "none")
                and f.get("acodec") not in (None, "none")
            ]
            if combined:
                best = max(combined, key=lambda f: f.get("height") or 0)
                return best["url"], best.get("ext", "mp4")

            video = [
                f for f in fmts
                if f.get("url") and f.get("vcodec") not in (None, "none")
            ]
            if video:
                best = max(video, key=lambda f: f.get("height") or 0)
                return best["url"], best.get("ext", "mp4")

            images = [
                f for f in fmts
                if f.get("url")
                and f.get("vcodec") in (None, "none")
                and f.get("acodec") in (None, "none")
            ]
            if images:
                best = max(images, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
                return best["url"], best.get("ext", "jpg")

        if info.get("url"):
            return info["url"], info.get("ext", "jpg")

        thumbs = info.get("thumbnails") or []
        if thumbs:
            with_url = [t for t in thumbs if t.get("url")]
            if with_url:
                best = max(with_url, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
                return best["url"], "jpg"

        return None, "jpg"

    async def _download_url(self, url: str) -> BytesIO | None:
        async with aiohttp.ClientSession(headers=DOWNLOAD_HEADERS) as session:
            try:
                async with session.head(url, allow_redirects=True,
                                        timeout=aiohttp.ClientTimeout(total=10)) as head:
                    size = int(head.headers.get("Content-Length", 0))
                    if size > MAX_BYTES:
                        print(f"{Timestamp()} [Instagram] file too large: {size // (1024*1024)} MB")
                        return None
            except Exception:
                pass

            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        print(f"{Timestamp()} [Instagram] HTTP {resp.status} for {url[:80]}")
                        return None
                    buf = BytesIO()
                    async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                        buf.write(chunk)
                        if buf.tell() > MAX_BYTES:
                            print(f"{Timestamp()} [Instagram] file exceeded size limit mid-download")
                            return None
                    buf.seek(0)
                    return buf
            except Exception as e:
                print(f"{Timestamp()} [Instagram] download error: {e}")
                return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        match = INSTAGRAM_PATTERN.search(message.content)
        if not match:
            return

        raw_url   = match.group(1)
        clean_url = _clean_url(raw_url)

        shortcode_match = re.search(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', clean_url)
        shortcode = shortcode_match.group(1) if shortcode_match else None

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        files = []
        label = "post"

        info = await asyncio.to_thread(self._extract_ytdlp, clean_url)
        if info:
            entries = info.get("entries") or [info]
            entries = [e for e in entries if e]

            first = entries[0]
            label = "reel" if self._is_video(first) else "photo"
            if len(entries) > 1:
                label = "post"

            for entry in entries[:10]:
                media_url, ext = self._pick_url(entry)
                if not media_url:
                    continue
                buf = await self._download_url(media_url)
                if buf:
                    files.append(discord.File(buf, filename=f"instagram.{ext}"))

        if not files and shortcode:
            print(f"{Timestamp()} [Instagram] yt-dlp got nothing, trying instaloader...")
            results = await self._fetch_via_instaloader(shortcode)
            for buf, ext in results:
                if buf.getbuffer().nbytes <= MAX_BYTES:
                    files.append(discord.File(buf, filename=f"instagram.{ext}"))
            if results:
                label = "reel" if any(ext == "mp4" for _, ext in results) else "photo"
                if len(results) > 1:
                    label = "post"

        header = f"**{message.author.mention} shared an Instagram {label}**"

        if not files:
            await message.channel.send(f"{header}\n{clean_url}")
            return

        try:
            await message.channel.send(content=header, files=files)
        except discord.HTTPException as e:
            await message.channel.send(f"{header}\n{clean_url}\n_(Upload failed: {e})_")
        finally:
            for f in files:
                try:
                    f.fp.close()
                except Exception:
                    pass


async def setup(bot):
    await bot.add_cog(Instagram(bot))
