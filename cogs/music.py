import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
from collections import deque
from data.variables import Timestamp


ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}


ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')
        self.duration = data.get('duration')

    def get_duration(self):
        minutes, seconds = divmod(self.duration, 60)
        return f"{int(minutes)}:{int(seconds):02d}"

    @classmethod
    async def from_url(cls, url, *, stream=False):
        ydl = yt_dlp.YoutubeDL(ytdl_format_options)
        data = await asyncio.to_thread(ydl.extract_info, url, download=not stream)

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ydl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class MusicView(discord.ui.View):
    def __init__(self, client, cog, embed_message=None):
        super().__init__(timeout=None)
        self.client = client
        self.cog = cog
        self.embed_message = embed_message

    @discord.ui.button(emoji="<:back:1136672186397114378>", style=discord.ButtonStyle.primary, custom_id="back_button")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.back(interaction)

    @discord.ui.button(emoji="<:play_pause:1136672190033559564>", style=discord.ButtonStyle.primary, custom_id="toggle_pause_resume_button")
    async def toggle_pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.toggle_pause_resume(interaction, button)

    @discord.ui.button(emoji="<:skip_next:1136672179728175215>", style=discord.ButtonStyle.primary, custom_id="skip_button")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.skip(interaction)


class Music(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.queues = {}
        self.played_songs = {}
        self.current_embed_messages = {}
        self.text_channels = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        voice_client = member.guild.voice_client
        if voice_client and voice_client.channel:
            if len(voice_client.channel.members) == 1:
                await asyncio.sleep(300)
                if len(voice_client.channel.members) == 1:
                    await self.cleanup(voice_client)

    async def cleanup(self, voice_client):
        guild_id = voice_client.guild.id
        await voice_client.disconnect()
        self.queues[guild_id] = []
        self.played_songs[guild_id] = deque()
        if guild_id in self.current_embed_messages:
            try:
                await self.current_embed_messages[guild_id].delete()
            except discord.errors.NotFound:
                pass
            del self.current_embed_messages[guild_id]
            print(f"{Timestamp()} [{voice_client.guild.name}/{voice_client.channel.name}] Disconnected.")


    async def create_player_embed(self, interaction, player):
        embed = discord.Embed(
            title="Now Playing",
            description=f"{player.title}\nDuration: {player.get_duration()}",
            color=discord.Color.from_rgb(51, 201, 0)
        )
        embed.set_thumbnail(url=player.thumbnail)
        view = MusicView(self.client, self)
        guild_id = interaction.guild.id
        if guild_id in self.current_embed_messages:
            try:
                await self.current_embed_messages[guild_id].delete()
            except discord.errors.NotFound:
                pass
        self.current_embed_messages[guild_id] = await interaction.followup.send(embed=embed, view=view)

    async def update_player_embed(self, guild_id, player):
        embed = discord.Embed(
            title="Now Playing",
            description=f"{player.title}\nDuration: {player.get_duration()}",
            color=discord.Color.from_rgb(51, 201, 0)
        )
        embed.set_thumbnail(url=player.thumbnail)
        view = MusicView(self.client, self)

        if guild_id in self.current_embed_messages:
            try:
                await self.current_embed_messages[guild_id].delete()
            except discord.errors.NotFound:
                pass

        channel = self.text_channels.get(guild_id)
        if channel:
            self.current_embed_messages[guild_id] = await channel.send(embed=embed, view=view)

    @app_commands.command(name="join", description="Test join vc")
    async def join(self, interaction: discord.Interaction):
        voice_state = interaction.user.voice
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message("You are not connected to a voice channel.", ephemeral=True)
            return
        channel = voice_state.channel
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.move_to(channel)
        else:
            await channel.connect(self_deaf=True)

        await interaction.response.send_message(f"Joined {channel.name} and deafened!", ephemeral=True)

    @app_commands.command(name="play", description="Play a song from a URL or search term (e.g., /play <url/name>)")
    async def play(self, interaction: discord.Interaction, url: str):
        guild_id = interaction.guild.id
        voice_state = interaction.user.voice

        if not voice_state or not voice_state.channel:
            await interaction.response.send_message("You are not connected to a voice channel.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if voice_client is None:
            voice_client = await voice_state.channel.connect(self_deaf=True)
        elif voice_client.channel != voice_state.channel:
            await voice_client.move_to(voice_state.channel)

        self.text_channels[guild_id] = interaction.channel

        try:
            try:
                await interaction.response.defer(ephemeral=False)
            except discord.errors.InvalidInteraction:
                await interaction.followup.send("An issue occurred while deferring the interaction.", ephemeral=True)
                return

            player = await YTDLSource.from_url(url, stream=True)
            if voice_client.is_playing() or self.queues.get(guild_id):
                if guild_id not in self.queues:
                    self.queues[guild_id] = []
                self.queues[guild_id].append(player)
                await interaction.followup.send(f"Added {player.title} to the queue.", ephemeral=False)
            else:
                if guild_id not in self.played_songs:
                    self.played_songs[guild_id] = deque()
                voice_client.play(player, after=lambda e: self.client.loop.create_task(self.play_next(voice_client)))
                print(
                    f'{Timestamp()} [{voice_client.guild.name}/{voice_client.channel.name}] Now playing: {player.title}')
                await self.create_player_embed(interaction, player)
        except Exception as e:
            await interaction.followup.send(f'An error occurred: {str(e)}', ephemeral=True)

    @app_commands.command(name="leave", description="Leave the voice channel and clean up")
    async def leave(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if voice_client is None:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=True)
            return

        await self.cleanup(voice_client)
        await interaction.response.send_message("Left the voice channel and cleaned up.", ephemeral=True)

    async def play_next(self, voice_client):
        guild_id = voice_client.guild.id
        if guild_id in self.queues and self.queues[guild_id]:
            player = self.queues[guild_id].pop(0)
            if guild_id not in self.played_songs:
                self.played_songs[guild_id] = deque()
            self.played_songs[guild_id].appendleft(player)
            voice_client.play(player, after=lambda e: self.client.loop.create_task(
                self.play_next(voice_client)) if e is None else print(
                f'{Timestamp()} [{voice_client.guild.name}/{voice_client.channel.name}] Player error: {e}'))
            print(
                f'{Timestamp()} [{voice_client.guild.name}/{voice_client.channel.name}] Now playing next song in queue: {player.title}')
            await self.update_player_embed(guild_id, player)
        else:
            await asyncio.sleep(2)
            if voice_client.is_connected() and (voice_client.is_playing() or voice_client.is_paused()):
                pass
            else:
                await asyncio.sleep(300)

                if not self.queues.get(guild_id) and voice_client.is_connected() and not (voice_client.is_playing() or voice_client.is_paused()):
                    if guild_id in self.current_embed_messages:
                        try:
                            await self.current_embed_messages[guild_id].delete()
                        except discord.errors.NotFound:
                            pass
                    await voice_client.disconnect()

    async def toggle_pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client

        if voice_client is None or not (voice_client.is_playing() or voice_client.is_paused()):
            await interaction.response.defer()
            return

        if voice_client.is_playing():
            voice_client.pause()
            button.emoji = "<:play_pause:1136672188032893010>"
        elif voice_client.is_paused():
            voice_client.resume()
            button.emoji = "<:play_pause:1136672190033559564>"

        await interaction.response.edit_message(view=button.view)
        await interaction.response.defer()

    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild.id

        if voice_client is None or not voice_client.is_playing():
            await interaction.response.defer()
            return

        if self.queues.get(guild_id):
            next_song = self.queues[guild_id].pop(0)
            voice_client.stop()
            voice_client.play(next_song, after=lambda e: self.client.loop.create_task(self.play_next(voice_client)))
            await self.update_player_embed(guild_id, next_song)
        else:
            voice_client.stop()
            if guild_id in self.current_embed_messages:
                try:
                    await self.current_embed_messages[guild_id].delete()
                    self.current_embed_messages.pop(guild_id, None)
                except discord.errors.NotFound:
                    pass

        await interaction.response.defer()

    async def back(self, interaction: discord.Interaction): #CURRENTLY NOT WORKING
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild.id

        if voice_client is None or not voice_client.is_playing():
            await interaction.response.defer()
            print("Not in voice channel or no song is playing.")
            return

        if len(self.played_songs.get(guild_id, [])) > 0:
            previous_song = self.played_songs[guild_id].pop()
            current_song = voice_client.source
            if guild_id not in self.queues:
                self.queues[guild_id] = []
            self.queues[guild_id].insert(0, current_song)
            voice_client.stop()
            voice_client.play(previous_song, after=lambda e: self.client.loop.create_task(self.play_next(voice_client)))
            await self.update_player_embed(guild_id, previous_song)
        else:
            print("No previous song in the history.")
            await interaction.response.send_message("No previous song to play.", ephemeral=True)
        await interaction.response.defer()

    async def on_play_song(self, guild_id, player):
        if guild_id in self.played_songs and self.played_songs[guild_id] and self.played_songs[guild_id][-1].url == player.url:
            return
        if guild_id not in self.played_songs:
            self.played_songs[guild_id] = deque()
        self.played_songs[guild_id].append(player)


async def setup(client):
    await client.add_cog(Music(client))
