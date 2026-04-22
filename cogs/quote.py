import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
import io
import aiohttp
import random
import re
import textwrap
import platform

QUOTE_PATTERN = re.compile(r'[""\'\'"](.+?)[""\'\'\"]\s*(?:-*\s*)?(<@!?\d+>)?', re.DOTALL)
FONT_PATH = (
    "arial.ttf"
    if platform.system() == "Windows"
    else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)


class Quote(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @app_commands.command(name="quote", description="Show a random quote image from the #quotes channel.")
    async def quote(self, interaction: discord.Interaction):
        await interaction.response.defer()

        quotes_channel = discord.utils.find(
            lambda c: "quote" in c.name.lower(),
            interaction.guild.text_channels
        )
        if not quotes_channel:
            return await interaction.followup.send("Couldn't find a `#quotes` channel.")

        messages = [m async for m in quotes_channel.history(limit=None)]
        quotes   = []

        for msg in messages:
            for text, mention in QUOTE_PATTERN.findall(msg.content):
                text = text.strip()
                if not text:
                    continue
                user = msg.mentions[0] if msg.mentions else msg.author
                quotes.append((text, user, msg))

        if not quotes:
            return await interaction.followup.send("No valid quotes found in the quotes channel.")

        quote_text, user, msg = random.choice(quotes)

        # fetch avatar 
        async with aiohttp.ClientSession() as session:
            async with session.get(user.display_avatar.replace(size=512).url) as resp:
                avatar_bytes = await resp.read()

        # compose image 
        size = 800
        half = size // 2

        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size))

        # Left-to-right gradient mask: dark on left, transparent on right side reversed
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

        wrapped      = textwrap.wrap(f'"{quote_text}"', width=20)
        bbox         = draw.textbbox((0, 0), "A", font=font)
        line_h       = (bbox[3] - bbox[1]) + 6
        total_h      = len(wrapped) * line_h + 30
        y            = (size - total_h) // 2
        x            = half + 20

        for line in wrapped:
            draw.text((x, y), line, font=font, fill="white")
            y += line_h

        draw.text((x, y + 10), f"– {user.display_name}", font=font, fill="white")

        # send
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        msg_url = f"https://discord.com/channels/{msg.guild.id}/{msg.channel.id}/{msg.id}"
        await interaction.followup.send(
            content=msg_url,
            file=discord.File(buf, filename="quote.png")
        )


async def setup(client):
    await client.add_cog(Quote(client))
