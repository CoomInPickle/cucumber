# music_queue.py
import discord
from discord import app_commands
from discord.ext import commands

class QueueView(discord.ui.View):
    def __init__(self, cog, queue, current_song, page=0):
        super().__init__(timeout=None)
        self.cog = cog
        self.queue = queue
        self.current_song = current_song
        self.page = page
        self.items_per_page = 10
        self.total_pages = (len(queue) + self.items_per_page - 1) // self.items_per_page

        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        self.add_item(self.previous_button)
        self.add_item(self.next_button)

    @discord.ui.button(label="<", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_queue_embed(), view=self)

    @discord.ui.button(label=">", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction):
        if self.page < self.total_pages - 1:
            self.page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_queue_embed(), view=self)

    def get_queue_embed(self):
        start = self.page * self.items_per_page
        end = start + self.items_per_page
        queue_page = self.queue[start:end]

        description = f"**Now Playing:** {self.current_song.title}\n\n"
        description += f"**Next up:**\n"

        for i, song in enumerate(queue_page, start=start + 1):
            description += f"{i}. {song.title}\n"

        embed = discord.Embed(
            title="Music Queue",
            description=description,
            color=discord.Color.from_rgb(51, 201, 0)  # Set the color to (51, 201, 0)
        )
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages}")
        return embed

class QueueCommands(commands.Cog):
    def __init__(self, client):
        self.client = client

    @app_commands.command(name="queue", description="Displays the music queue.")
    async def queue(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        music_cog = self.client.get_cog("Music")

        if not music_cog:
            await interaction.response.send_message("Music cog not found.", ephemeral=True)
            return

        queue = music_cog.queues.get(guild_id, [])
        current_song = interaction.guild.voice_client.source if interaction.guild.voice_client else None

        if not current_song:
            await interaction.response.send_message("There is no song currently playing.", ephemeral=True)
            return

        if not queue:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return
        else:
            view = QueueView(music_cog, queue, current_song)
            await interaction.response.send_message(embed=view.get_queue_embed(), view=view)

async def setup(client):
    await client.add_cog(QueueCommands(client))
