import discord
from discord.ext import commands
import re
import aiohttp
import asyncio
from io import BytesIO
from yt_dlp import YoutubeDL


class Instagram(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pattern = re.compile(
            r"(https?://(?:www\.|m\.)?instagram\.com/(?:p|reel|reels)/[A-Za-z0-9_-]+)"
        )

        self.YDL_OPTS = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "source_address": "0.0.0.0",
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        match = self.pattern.search(message.content)
        if not match:
            return

        url = match.group(1)
        await message.delete()

        try:
            info = await asyncio.to_thread(self.extract_info, url)
            if not info:
                await message.channel.send("⚠️ Could not extract media info from that link.")
                return

            media_url, ext, is_video = self._get_best_media(info)

            if not media_url:
                await message.channel.send("⚠️ Could not find a valid media URL for that post.")
                return

            # Build a nice header message
            short_url = url.split("?")[0]
            msg_text = f"**{message.author.mention} shared a [reel]**"

            async with aiohttp.ClientSession() as session:
                async with session.get(media_url) as resp:
                    if resp.status != 200:
                        await message.channel.send("⚠️ Failed to fetch media.")
                        return
                    data = BytesIO(await resp.read())
                    filename = f"instagram.{ext}"
                    # Discord upload limit (8 MB typical)
                    if data.getbuffer().nbytes > 8 * 1024 * 1024:
                        await message.channel.send(
                            f"{msg_text}\n📎 File too large to upload, but here’s the link:\n{media_url}"
                        )
                    else:
                        await message.channel.send(content=msg_text, file=discord.File(data, filename))
                    data.close()

        except Exception as e:
            print(f"[Instagram Error] {e}")
            await message.channel.send("❌ Error downloading Instagram media.")

    def extract_info(self, url: str):
        with YoutubeDL(self.YDL_OPTS) as ydl:
            try:
                return ydl.extract_info(url, download=False)
            except Exception as e:
                print(f"[yt-dlp Error] {e}")
                return None

    def _get_best_media(self, info: dict):
        media_url, ext, is_video = None, "mp4", False
        if "url" in info and info.get("ext") in ("mp4", "mov", "webm", "mkv"):
            media_url = info["url"]
            ext = info.get("ext", "mp4")
            is_video = True
        elif "formats" in info:
            formats = sorted(info["formats"], key=lambda f: f.get("filesize") or 0, reverse=True)
            for f in formats:
                if f.get("url") and f.get("vcodec") != "none" and f.get("acodec") != "none":
                    media_url = f["url"]
                    ext = f.get("ext", "mp4")
                    is_video = True
                    break
            if not media_url:
                for f in formats:
                    if f.get("url") and f.get("vcodec") != "none":
                        media_url = f["url"]
                        ext = f.get("ext", "mp4")
                        is_video = True
                        break
        if not media_url and info.get("thumbnails"):
            thumb = info["thumbnails"][-1]
            media_url = thumb.get("url")
            ext = "jpg"
            is_video = False

        return media_url, ext, is_video


async def setup(bot):
    await bot.add_cog(Instagram(bot))
