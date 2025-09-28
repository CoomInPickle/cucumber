import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
import io
import aiohttp
import random
import re
import textwrap
import os
import platform

class Quote(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @app_commands.command(name="quote", description="Get a random quote image from the #quotes channel.")
    async def quote(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Find the #quotes channel
        quotes_channel = discord.utils.find(lambda c: "quote" in c.name.lower(), interaction.guild.text_channels)
        if not quotes_channel:
            await interaction.followup.send("Couldn't find a channel named `quotes`.")
            return

        messages = [msg async for msg in quotes_channel.history(limit=None)]
        quotes = []

        for msg in messages:
            # Match all quoted parts with optional mention
            matches = re.findall(r'[“"‘\'](.+?)[”"’\']\s*(?:-*\s*)?(<@!?\d+>)?', msg.content, re.DOTALL)

            for text, mention in matches:
                text = text.strip()
                if not text:
                    continue

                if msg.mentions:
                    user = msg.mentions[0]
                else:
                    user = msg.author

                quotes.append((text, user, msg))

        if not quotes:
            await interaction.followup.send("No valid quotes found in #quotes.")
            return

        quote_text, user, msg = random.choice(quotes)

        avatar_url = user.display_avatar.replace(size=512).url
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                avatar_bytes = await resp.read()

        # Image size
        size = 800
        half = size // 2

        # Load and resize avatar
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size))

        gradient = Image.new("L", (size, 1))
        for x in range(size):
            alpha = int(255 * (x / half)) if x < half else 255
            gradient.putpixel((x, 0), alpha)

        alpha_mask = gradient.resize((size, size))
        black_overlay = Image.new("RGBA", (size, size), (0, 0, 0, 255))
        black_overlay.putalpha(alpha_mask)

        # Combine avatar + overlay
        img = Image.alpha_composite(avatar_img, black_overlay)

        # Draw text
        draw = ImageDraw.Draw(img)

        def get_font():
            if platform.system() == "Windows":
                return ImageFont.truetype("arial.ttf", 32)
            else:
                return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)

        try:
            font = get_font()
        except:
            font = ImageFont.load_default()

        quote_full = f'"{quote_text}"'
        author = f"– {user.display_name}"

        wrapped_lines = textwrap.wrap(quote_full, width=20)

        bbox = draw.textbbox((0, 0), "A", font=font)
        line_height = (bbox[3] - bbox[1]) + 6
        author_spacing = 30
        total_height = len(wrapped_lines) * line_height + author_spacing
        y_start = (size - total_height) // 2
        x_start = half + 20


        for i, line in enumerate(wrapped_lines):
            y = y_start + i * line_height
            draw.text((x_start, y), line, font=font, fill="white")


        y = y_start + len(wrapped_lines) * line_height + 10
        draw.text((x_start, y), author, font=font, fill="white")

        # Save to buffer
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        file = discord.File(buffer, filename="quote.png")

        msg_url = f"https://discord.com/channels/{msg.guild.id}/{msg.channel.id}/{msg.id}"

        await interaction.followup.send(content=f"{msg_url}", file=file)

async def setup(client):
    await client.add_cog(Quote(client))
