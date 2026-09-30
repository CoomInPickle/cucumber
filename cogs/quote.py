import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
import io
import os
import aiohttp
import asyncio
import random
import re
import shutil
import textwrap
import platform
import tempfile
import time
from data.variables import Timestamp

QUOTE_PATTERN = re.compile(r'[""\'\'"](.+?)[""\'\'\"]\s*(?:-*\s*)?(<@!?\d+>)?', re.DOTALL)
FONT_PATH = (
    "C:/Windows/Fonts/arial.ttf"
    if platform.system() == "Windows"
    else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)
FONT_BOLD_PATH = (
    "C:/Windows/Fonts/arialbd.ttf"
    if platform.system() == "Windows"
    else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
)

QUOTE_SOUND_DIR = "sounds/quote"
SOUND_EXTS      = (".mp3", ".wav", ".ogg", ".m4a", ".opus", ".flac")
VIDEO_SECONDS   = 10

WESTERN_HEADERS = [
    "WANTED: {name}\nFOR SAYING THIS",
    "THE LAST WORDS OF {name}",
    "{name} SPOKE.\nNOBODY WAS SAFE.",
    "A WISE MAN ONCE SAID",
    "THE GOOD, THE BAD\nAND {name}",
    "THE SALOON WENT SILENT.\n{name} HAD SPOKEN.",
    "AND THEN {name}\nSAID THIS",
    "THIS TOWN AIN'T BIG ENOUGH\nFOR {name}'S OPINIONS",
]


def _build_quote_image(avatar_bytes: bytes, quote_text: str, display_name: str) -> io.BytesIO:
    size = 800
    half = size // 2

    avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size))

    gradient = Image.new("L", (size, 1))
    for x in range(size):
        alpha = int(255 * (x / half)) if x < half else 255
        gradient.putpixel((x, 0), alpha)

    alpha_mask    = gradient.resize((size, size))
    black_overlay = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    black_overlay.putalpha(alpha_mask)

    img  = Image.alpha_composite(avatar_img, black_overlay)
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(FONT_PATH, 32)
    except OSError:
        font = ImageFont.load_default()

    wrapped = textwrap.wrap(f'"{quote_text}"', width=20)
    bbox    = draw.textbbox((0, 0), "A", font=font)
    line_h  = (bbox[3] - bbox[1]) + 6
    total_h = len(wrapped) * line_h + 30
    y       = (size - total_h) // 2
    x       = half + 20

    for line in wrapped:
        draw.text((x, y), line, font=font, fill="white")
        y += line_h

    draw.text((x, y + 10), f"– {display_name}", font=font, fill="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _pick_sound() -> str | None:
    if not os.path.isdir(QUOTE_SOUND_DIR):
        return None
    files = [
        os.path.join(QUOTE_SOUND_DIR, f)
        for f in os.listdir(QUOTE_SOUND_DIR)
        if f.lower().endswith(SOUND_EXTS)
    ]
    return random.choice(files) if files else None


async def _build_quote_video(avatar_bytes: bytes, quote_text: str, display_name: str,
                             sound_path: str) -> io.BytesIO | None:
    header = random.choice(WESTERN_HEADERS).format(name=display_name.upper())
    quote  = "\n".join(textwrap.wrap(f'"{quote_text}"', width=26))
    author = f"- {display_name}"

    bold       = FONT_BOLD_PATH if os.path.exists(FONT_BOLD_PATH) else FONT_PATH
    sound_path = os.path.abspath(sound_path)

    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(FONT_PATH, os.path.join(tmp, "font.ttf"))
        shutil.copy(bold, os.path.join(tmp, "bold.ttf"))
        with open(os.path.join(tmp, "avatar.png"), "wb") as f:
            f.write(avatar_bytes)
        for name, text in (("header", header), ("quote", quote), ("author", author)):
            with open(os.path.join(tmp, f"{name}.txt"), "w", encoding="utf-8") as f:
                f.write(text)

        def dt(name, font, size, color, y, start):
            return (
                f"drawtext=fontfile={font}:textfile={name}.txt:expansion=none:"
                f"fontsize={size}:fontcolor={color}:borderw=3:bordercolor=black:"
                f"line_spacing=10:x=(w-text_w)/2:y={y}:"
                f"alpha='min(max((t-{start})/0.4,0),1)'"
            )

        slide_x = "W-(W-(W-w)/2)*(1-pow(1-min(t/1.4,1),2))"

        filter_complex = (
            "[1:v]scale=520:520,format=rgba,"
            "colorchannelmixer=rr=.393:rg=.769:rb=.189:gr=.349:gg=.686:gb=.168:"
            "br=.272:bg=.534:bb=.131:aa=0.55[av];"
            f"[0:v][av]overlay=x='{slide_x}':y=(H-h)/2:format=auto,"
            + dt("header", "bold.ttf", 34, "0xE8C56A", 50, 1.0) + ","
            + dt("quote", "bold.ttf", 42, "white", "(h-text_h)/2", 1.6) + ","
            + dt("author", "font.ttf", 34, "0xE8C56A", "h-100", 2.4) +
            ",format=yuv420p[v]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=720x720:r=25:d={VIDEO_SECONDS}",
            "-loop", "1", "-framerate", "25", "-i", "avatar.png",
            "-i", sound_path,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "2:a",
            "-t", str(VIDEO_SECONDS), "-shortest",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "out.mp4",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=tmp,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
        except asyncio.TimeoutError:
            proc.kill()
            print(f"{Timestamp()} [Quote] ffmpeg timed out")
            return None

        out_path = os.path.join(tmp, "out.mp4")
        if proc.returncode != 0 or not os.path.exists(out_path):
            print(f"{Timestamp()} [Quote] ffmpeg failed: {stderr.decode(errors='ignore')[:800]}")
            return None

        with open(out_path, "rb") as f:
            return io.BytesIO(f.read())


class Quote(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self._quote_cache = {}
        self._cache_ttl = 600

    async def _get_quotes(self, guild: discord.Guild):
        quotes_channel = discord.utils.find(
            lambda c: "quote" in c.name.lower(),
            guild.text_channels
        )
        if not quotes_channel:
            return None, "Couldn't find a `#quotes` channel."

        now    = time.time()
        cached = self._quote_cache.get(quotes_channel.id)

        if cached and now - cached[0] < self._cache_ttl:
            quotes = cached[1]
        else:
            messages = [m async for m in quotes_channel.history(limit=None)]
            quotes   = []

            for msg in messages:
                for text, mention in QUOTE_PATTERN.findall(msg.content):
                    text = text.strip()
                    if not text:
                        continue
                    user = msg.mentions[0] if msg.mentions else msg.author
                    quotes.append((text, user, msg))

            self._quote_cache[quotes_channel.id] = (now, quotes)

        if not quotes:
            return None, "No valid quotes found in the quotes channel."
        return quotes, None

    @app_commands.command(name="quote", description="Show a random quote image from the #quotes channel.")
    @app_commands.describe(sound="Make it a black western-style video with a random sound instead of an image")
    async def quote(self, interaction: discord.Interaction, sound: bool = False):
        await interaction.response.defer()

        sound_path = None
        if sound:
            sound_path = _pick_sound()
            if not sound_path:
                return await interaction.followup.send(
                    f"No sound files found in `{QUOTE_SOUND_DIR}/`.")

        quotes, err = await self._get_quotes(interaction.guild)
        if err:
            return await interaction.followup.send(err)

        quote_text, user, msg = random.choice(quotes)

        async with aiohttp.ClientSession() as session:
            async with session.get(user.display_avatar.replace(size=512, format="png").url) as resp:
                avatar_bytes = await resp.read()

        msg_url = f"https://discord.com/channels/{msg.guild.id}/{msg.channel.id}/{msg.id}"

        if sound:
            video = await _build_quote_video(avatar_bytes, quote_text, user.display_name, sound_path)
            if video is None:
                return await interaction.followup.send("Couldn't render the video (check the bot log).")
            try:
                return await interaction.followup.send(
                    content=msg_url,
                    file=discord.File(video, filename="quote.mp4")
                )
            except discord.HTTPException as e:
                return await interaction.followup.send(f"Upload failed: {e}")

        buf = await asyncio.to_thread(_build_quote_image, avatar_bytes, quote_text, user.display_name)

        await interaction.followup.send(
            content=msg_url,
            file=discord.File(buf, filename="quote.png")
        )


async def setup(client):
    await client.add_cog(Quote(client))