import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from data.variables import Timestamp

GUILDS_DIR = "data/guilds"


def _guild_dir(guild_id: str) -> str:
    path = os.path.join(GUILDS_DIR, str(guild_id))
    os.makedirs(path, exist_ok=True)
    return path


def _embeds_path(guild_id: str) -> str:
    return os.path.join(_guild_dir(guild_id), "embeds.json")


def load_embeds(guild_id: str) -> dict:
    path = _embeds_path(str(guild_id))
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_embeds(guild_id: str, data: dict):
    with open(_embeds_path(str(guild_id)), "w") as f:
        json.dump(data, f, indent=2)


def safe_url(url):
    if not url:
        return None

    url = str(url).strip()

    if url.startswith(("http://", "https://")):
        return url

    return None


def _build_discord_embed(embed_data: dict) -> discord.Embed:
    """Convert our stored embed dict into a discord.Embed object."""
    color_hex = embed_data.get("color", "#5865F2").lstrip("#")
    try:
        color = discord.Color(int(color_hex, 16))
    except Exception:
        color = discord.Color.blurple()

    em = discord.Embed(
        title=embed_data.get("title") or None,
        description=embed_data.get("description") or None,
        color=color,
    )

    # Embed URL
    em.url = safe_url(embed_data.get("url"))

    # Author
    author = embed_data.get("author", {})
    if author.get("name"):
        em.set_author(
            name=author["name"],
            url=safe_url(author.get("url")),
            icon_url=safe_url(author.get("icon_url")),
        )

    # Thumbnail
    thumb = safe_url(embed_data.get("thumbnail"))
    if thumb:
        em.set_thumbnail(url=thumb)

    # Image
    image = safe_url(embed_data.get("image"))
    if image:
        em.set_image(url=image)

    # Fields
    for field in embed_data.get("fields", []):
        em.add_field(
            name=field.get("name", "\u200b"),
            value=field.get("value", "\u200b"),
            inline=field.get("inline", False),
        )

    # Footer
    footer = embed_data.get("footer", {})
    if footer.get("text"):
        em.set_footer(
            text=footer["text"],
            icon_url=safe_url(footer.get("icon_url")),
        )

    return em


class Embeds(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client


    @app_commands.command(name="embed", description="Send a saved embed to this channel.")
    @app_commands.describe(name="Name of the embed to send")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def send_embed(self, interaction: discord.Interaction, name: str):
        guild_id = str(interaction.guild.id)
        embeds = load_embeds(guild_id)

        # name-keyed: key IS the name (lowercased with dashes)
        key = name.lower().replace(' ', '-')
        embed_data = embeds.get(key) or embeds.get(name)

        if not embed_data:
            return await interaction.response.send_message(
                f"No embed named `{name}` found. Create one in the dashboard.", ephemeral=True
            )

        content = embed_data.get("content") or None
        em = _build_discord_embed(embed_data)

        await interaction.response.send_message(content=content, embed=em)
        print(f"{Timestamp()} [Embeds] Sent embed '{key}' in {interaction.guild.name}")

    @send_embed.autocomplete("name")
    async def embed_autocomplete(self, interaction: discord.Interaction, current: str):
        guild_id = str(interaction.guild.id)
        embeds = load_embeds(guild_id)
        # keys are the names
        return [
            app_commands.Choice(name=key, value=key)
            for key in embeds
            if current.lower() in key.lower()
        ][:25]

    @app_commands.command(name="embeds", description="List all saved embeds for this server.")
    async def list_embeds(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        embeds = load_embeds(guild_id)

        if not embeds:
            return await interaction.response.send_message(
                "No embeds saved yet. Create some in the dashboard.", ephemeral=True
            )

        lines = [f"`{key}`" for key in embeds]
        em = discord.Embed(
            title="Saved Embeds",
            description="\n".join(lines),
            color=discord.Color.from_rgb(51, 201, 0),
        )
        await interaction.response.send_message(embed=em, ephemeral=True)


async def setup(client):
    await client.add_cog(Embeds(client))