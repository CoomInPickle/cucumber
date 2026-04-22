import discord
from discord.ext import commands
import re
import asyncio
import aiohttp
from io import BytesIO
from yt_dlp import YoutubeDL

INSTAGRAM_PATTERN = re.compile(
    r"(https?://(?:www\.|m\.)?instagram\.com/(?:p|reel|reels|tv)/[A-Za-z0-9_-]+)"
)

# yt-dlp options
YDL_OPTS = {
    "quiet":         True,
    "no_warnings":   True,
    "skip_download": True,
    "format":        "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best",
    "merge_output_format": "mp4",
    "source_address": "0.0.0.0",
}

MAX_BYTES   = 24 * 1024 * 1024   # 24 MB — safe below Discord's 25 MB limit
CHUNK_SIZE  = 1024 * 512         # 512 KB read chunks


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
            print(f"[Instagram] extract error: {e}")
            await message.channel.send("❌ Could not extract media from that link.")
            return

        if not info:
            await message.channel.send("⚠️ No media found at that link.")
            return

        media_url, ext, is_video = self._best_url(info)
        if not media_url:
            await message.channel.send("⚠️ Couldn't find a downloadable URL for that post.")
            return

        label  = "reel" if is_video else "photo"
        header = f"**{message.author.mention} shared an Instagram {label}**"

        # Pull cookies yt-dlp used so the CDN request is authenticated
        cookies = self._get_cookies(info)

        async with aiohttp.ClientSession(cookie_jar=cookies) as session:
            # HEAD first to check Content-Length without downloading
            try:
                async with session.head(media_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as head:
                    content_length = int(head.headers.get("Content-Length", 0))
                    if content_length > MAX_BYTES:
                        await message.channel.send(f"{header}\n⚠️ File is too large to upload ({content_length // (1024*1024)} MB).")
                        return
            except Exception:
                pass  # HEAD failed — try downloading anyway

            # Download
            try:
                async with session.get(media_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        await message.channel.send(f"{header}\n⚠️ Failed to fetch media (HTTP {resp.status}).")
                        return

                    buf = BytesIO()
                    async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                        buf.write(chunk)
                        if buf.tell() > MAX_BYTES:
                            buf.close()
                            await message.channel.send(f"{header}\n⚠️ File too large to upload.")
                            return

            except asyncio.TimeoutError:
                await message.channel.send(f"{header}\n⚠️ Download timed out.")
                return
            except Exception as e:
                print(f"[Instagram] download error: {e}")
                await message.channel.send(f"{header}\n⚠️ Download failed.")
                return

        buf.seek(0)
        try:
            await message.channel.send(
                content=header,
                file=discord.File(buf, filename=f"instagram.{ext}")
            )
        except discord.HTTPException as e:
            await message.channel.send(f"{header}\n⚠️ Upload failed: {e}")
        finally:
            buf.close()

    # helpers

    def _extract(self, url: str) -> dict | None:
        with YoutubeDL(YDL_OPTS) as ydl:
            try:
                return ydl.extract_info(url, download=False)
            except Exception as e:
                print(f"[yt-dlp Instagram] {e}")
                return None

    def _best_url(self, info: dict) -> tuple[str | None, str, bool]:
        # Direct URL
        if info.get("url") and info.get("ext") in ("mp4", "mov", "webm"):
            return info["url"], info.get("ext", "mp4"), True

        if "formats" in info:
            fmts = info["formats"]
            combined = [f for f in fmts
                        if f.get("url") and f.get("vcodec") != "none" and f.get("acodec") != "none"]
            if combined:
                best = max(combined, key=lambda f: f.get("height") or 0)
                return best["url"], best.get("ext", "mp4"), True
            video = [f for f in fmts if f.get("url") and f.get("vcodec") != "none"]
            if video:
                best = max(video, key=lambda f: f.get("height") or 0)
                return best["url"], best.get("ext", "mp4"), True

        thumbs = info.get("thumbnails", [])
        if thumbs:
            return thumbs[-1].get("url"), "jpg", False

        return None, "mp4", False

    def _get_cookies(self, info: dict) -> aiohttp.CookieJar:
        """Build an aiohttp CookieJar from yt-dlp's http_headers if available."""
        jar = aiohttp.CookieJar(unsafe=True)
        # yt-dlp doesn't expose cookies directly in info, but we can
        # pass the same cookiefile to requests via headers if needed.
        # For now return an empty jar — CDN URLs are usually pre-signed.
        return jar


async def setup(bot):
    await bot.add_cog(Instagram(bot))
