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
    cache = {}

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
        if url in cls.cache:
            data = cls.cache[url]
        else:
            ydl = yt_dlp.YoutubeDL(ytdl_format_options)
            data = await asyncio.to_thread(ydl.extract_info, url, download=not stream)
            if 'entries' in data:
                data = data['entries'][0]
            cls.cache[url] = data
        filename = data['url'] if stream else yt_dlp.YoutubeDL(ytdl_format_options).prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class MusicView(discord.ui.View):
    def __init__(self, client, cog):
        super().__init__(timeout=None)
        self.client = client
        self.cog = cog

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
        self.current_embed_messages = {}
        self.text_channels = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        voice_client = member.guild.voice_client
        if voice_client and voice_client.channel and len(voice_client.channel.members) == 1:
            await asyncio.sleep(300)
            if len(voice_client.channel.members) == 1:
                await self.cleanup(voice_client)

    async def cleanup(self, voice_client):
        guild_id = voice_client.guild.id
        await voice_client.disconnect()
        self.queues[guild_id] = deque()
        msg = self.current_embed_messages.pop(guild_id, None)
        if msg:
            try:
                await msg.delete()
            except discord.errors.NotFound:
                pass
        print(f"{Timestamp()} [{voice_client.guild.name}/{voice_client.channel.name}] Disconnected.")

    async def create_player_embed(self, interaction, player):
        embed = discord.Embed(
            title="Now Playing",
            description=f"{player.title}\nDuration: {player.get_duration()}",
            color=discord.Color.from_rgb(51, 201, 0)
        ).set_thumbnail(url=player.thumbnail)

        view = MusicView(self.client, self)
        guild_id = interaction.guild.id

        msg = self.current_embed_messages.pop(guild_id, None)
        if msg:
            try:
                await msg.delete()
            except discord.errors.NotFound:
                pass

        self.current_embed_messages[guild_id] = await interaction.followup.send(embed=embed, view=view)

    async def update_player_embed(self, guild_id, player):
        # Delete the old embed message if it exists
        msg = self.current_embed_messages.pop(guild_id, None)
        if msg:
            try:
                await msg.delete()
            except discord.errors.NotFound:
                pass

        # Create a fresh embed
        embed = discord.Embed(
            title="Now Playing",
            description=f"{player.title}\nDuration: {player.get_duration()}",
            color=discord.Color.from_rgb(51, 201, 0)
        ).set_thumbnail(url=player.thumbnail)

        # Send a new message and save its reference
        channel = self.text_channels.get(guild_id)
        if channel:
            self.current_embed_messages[guild_id] = await channel.send(embed=embed, view=MusicView(self.client, self))

    @app_commands.command(name="join", description="Join the voice channel.")
    async def join(self, interaction: discord.Interaction):
        channel = interaction.user.voice.channel if interaction.user.voice else None
        if not channel:
            await interaction.response.send_message("You are not connected to a voice channel.", ephemeral=True)
            return

        vc = interaction.guild.voice_client
        if vc:
            await vc.move_to(channel)
        else:
            await channel.connect(self_deaf=True)

        await interaction.response.send_message(f"Joined {channel.name} and deafened!", ephemeral=True)

    @app_commands.command(name="play", description="Play a song from a URL or search term.")
    async def play(self, interaction: discord.Interaction, query: str):
        guild_id = interaction.guild.id
        channel = interaction.user.voice.channel if interaction.user.voice else None
        if not channel:
            await interaction.response.send_message("You are not connected to a voice channel.", ephemeral=True)
            return

        vc = interaction.guild.voice_client
        if not vc:
            vc = await channel.connect(self_deaf=True)
        elif vc.channel != channel:
            await vc.move_to(channel)

        self.text_channels[guild_id] = interaction.channel

        try:
            await interaction.response.defer()
            player = await YTDLSource.from_url(query, stream=True)

            queue = self.queues.setdefault(guild_id, deque())
            if vc.is_playing() or queue:
                queue.append(player)
                await interaction.followup.send(f"Added {player.title} to the queue.")
            else:
                vc.play(player, after=lambda e: self.client.loop.create_task(self.play_next(vc)))
                print(f'{Timestamp()} [{vc.guild.name}/{vc.channel.name}] Now playing: {player.title}')
                await self.create_player_embed(interaction, player)

        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    @app_commands.command(name="leave", description="Leave the voice channel.")
    async def leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("I'm not connected to a voice channel.", ephemeral=True)
            return
        await self.cleanup(vc)
        await interaction.response.send_message("Left the voice channel and cleaned up.", ephemeral=True)

    async def play_next(self, vc):
        guild_id = vc.guild.id
        queue = self.queues.get(guild_id, deque())

        if queue:
            player = queue.popleft()
            vc.play(player, after=lambda e: self.client.loop.create_task(self.play_next(vc)) if not e else print(f"{Timestamp()} Player error: {e}"))
            print(f"{Timestamp()} [{vc.guild.name}/{vc.channel.name}] Now playing next: {player.title}")
            await self.update_player_embed(guild_id, player)
        else:
            await asyncio.sleep(302)
            if vc.is_connected() and not (vc.is_playing() or vc.is_paused()):
                await self.cleanup(vc)

    async def toggle_pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return

        if vc.is_playing():
            vc.pause()
            button.emoji = "<:play_pause:1136672188032893010>"
        else:
            vc.resume()
            button.emoji = "<:play_pause:1136672190033559564>"

        await interaction.response.edit_message(view=button.view)

    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client

        if not vc or not vc.is_playing():
            await interaction.response.send_message("Nothing is playing to skip.", ephemeral=True)
            return

        vc.stop()  # This will trigger the after-callback, which calls play_next()

        await interaction.response.defer()  # Prevent "application did not respond"


async def setup(client):
    await client.add_cog(Music(client))
