import discord
from discord import app_commands
from discord.ext import commands


class QueueView(discord.ui.View):
    def __init__(self, queue, current_song, *, page=0, items_per_page=10):
        super().__init__(timeout=None)
        self.queue = queue
        self.current_song = current_song
        self.page = page
        self.items_per_page = items_per_page
        self.total_pages = max(1, (len(queue) + items_per_page - 1) // items_per_page)

        # Only add buttons if more than 1 page
        if self.total_pages > 1:
            self.prev_button = self.PreviousPageButton()
            self.next_button = self.NextPageButton()
            self.add_item(self.prev_button)
            self.add_item(self.next_button)
            self.update_button_states()

    def update_button_states(self):
        # Disable previous if on first page, disable next if on last page
        if self.total_pages <= 1:
            return
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    async def update_message(self, interaction: discord.Interaction):
        self.update_button_states()
        await interaction.response.edit_message(embed=self.get_queue_embed(), view=self)

    class PreviousPageButton(discord.ui.Button):
        def __init__(self):
            super().__init__(style=discord.ButtonStyle.primary, label="Previous", disabled=True)

        async def callback(self, interaction: discord.Interaction):
            view: QueueView = self.view
            if view.page > 0:
                view.page -= 1
                # Enable/disable buttons appropriately
                self.disabled = view.page == 0
                view.children[1].disabled = False  # next button
                await interaction.response.edit_message(embed=view.get_queue_embed(), view=view)

    class NextPageButton(discord.ui.Button):
        def __init__(self):
            super().__init__(style=discord.ButtonStyle.primary, label="Next")

        async def callback(self, interaction: discord.Interaction):
            view: QueueView = self.view
            if view.page < view.total_pages - 1:
                view.page += 1
                # Enable/disable buttons appropriately
                self.disabled = view.page == view.total_pages - 1
                view.children[0].disabled = False  # previous button
                await interaction.response.edit_message(embed=view.get_queue_embed(), view=view)

    def get_queue_embed(self):
        start = self.page * self.items_per_page
        end = start + self.items_per_page
        queue_page = list(self.queue)[start:end]

        description = f"**Now Playing:** {self.current_song.title if self.current_song else 'None'}\n\n"
        description += "**Next up:**\n"

        if not queue_page:
            description += "_No more songs in the queue._"
        else:
            for i, song in enumerate(queue_page, start=start + 1):
                description += f"{i}. {song.title}\n"

        embed = discord.Embed(
            title="Music Queue",
            description=description,
            color=discord.Color.from_rgb(51, 201, 0)
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
        vc = interaction.guild.voice_client
        current_song = None
        if vc and vc.source:
            current_song = vc.source

        if not current_song:
            await interaction.response.send_message("There is no song currently playing.", ephemeral=True)
            return

        if not queue:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return

        view = QueueView(queue, current_song)
        await interaction.response.send_message(embed=view.get_queue_embed(), view=view)


async def setup(client):
    await client.add_cog(QueueCommands(client))
