import discord
from discord import app_commands
from discord.ext import commands

EMOJI_NEXT = "<:next:1496237059940028437>"


class QueueView(discord.ui.View):
    ITEMS_PER_PAGE = 10

    def __init__(self, queue: list, current_song, radio_preview: list = None, *, page: int = 0):
        super().__init__(timeout=120)
        self.queue         = queue
        self.current_song  = current_song
        self.radio_preview = radio_preview or []
        self.page          = page
        self.total_pages   = max(1, (len(queue) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        start      = self.page * self.ITEMS_PER_PAGE
        page_songs = self.queue[start: start + self.ITEMS_PER_PAGE]

        lines = []
        if self.current_song:
            lines.append(f"**Now Playing:** {self.current_song.title}")
        else:
            lines.append("**Now Playing:** None")

        lines.append("")
        lines.append(f"{EMOJI_NEXT} **Up Next:**")

        if not self.queue:
            lines.append("_Queue is empty._")
        else:
            for i, song in enumerate(page_songs, start=start + 1):
                dur = f"`{song.duration_str()}`" if hasattr(song, 'duration_str') else ""
                lines.append(f"`{i}.` {song.title} {dur}")

        # Radio preview section
        if self.radio_preview:
            lines.append("")
            lines.append("📻 **Up next from Radio:**")
            for i, song in enumerate(self.radio_preview, start=1):
                dur = f"`{song.duration_str()}`" if hasattr(song, 'duration_str') else ""
                lines.append(f"`~{i}.` {song.title} {dur}")

        embed = discord.Embed(
            title="Music Queue",
            description="\n".join(lines),
            color=discord.Color.from_rgb(51, 201, 0)
        )
        footer = f"Page {self.page + 1}/{self.total_pages}  •  {len(self.queue)} song(s) queued"
        if self.radio_preview:
            footer += "  •  📻 Radio on"
        embed.set_footer(text=footer)
        return embed

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class QueueCommands(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @app_commands.command(name="queue", description="Display the current music queue.")
    async def queue(self, interaction: discord.Interaction):
        music_cog = self.client.get_cog("Music")
        if not music_cog:
            return await interaction.response.send_message("Music cog not found.", ephemeral=True)

        guild_id      = interaction.guild.id
        gp            = music_cog.get_player(guild_id)
        current_song  = gp.current
        queue         = list(gp.queue)
        radio_preview = list(gp.radio_preview) if gp.radio else []

        if not current_song and not queue and not radio_preview:
            return await interaction.response.send_message(
                "Nothing is playing and the queue is empty.", ephemeral=True)

        view = QueueView(queue, current_song, radio_preview)
        await interaction.response.send_message(embed=view.build_embed(), view=view)


async def setup(client):
    await client.add_cog(QueueCommands(client))
