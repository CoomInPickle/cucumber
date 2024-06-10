import discord
from discord import app_commands
from discord.ext import commands
import datetime
import yt_dlp
import asyncio

# Variables
timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")  # Timestamp for logs

# Ensure FFmpeg is installed on your system and accessible via the command line

# FFmpeg options
ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

# YTDL options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,  # Add this line to suppress most logs
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # Bind to ipv4 since ipv6 addresses cause issues sometimes
}


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        ydl = yt_dlp.YoutubeDL(ytdl_format_options)
        data = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ydl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class MusicView(discord.ui.View):
    def __init__(self, client, cog, embed_message=None):
        super().__init__(timeout=None)
        self.client = client
        self.cog = cog
        self.embed_message = embed_message

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary, custom_id="pause_button")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.pause(interaction)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.success, custom_id="resume_button")
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.resume(interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.danger, custom_id="skip_button")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.skip(interaction)


class Music(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.queue = []
        self.current_embed_message = None
        self.text_channels = {}  # Dictionary to track text channels for each guild

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{timestamp} music cog loaded")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Only process if the bot is in a voice channel
        voice_client = member.guild.voice_client
        if voice_client and voice_client.channel:
            # Check if the bot is alone in the voice channel
            if len(voice_client.channel.members) == 1:
                await asyncio.sleep(60)
                if len(voice_client.channel.members) == 1:
                    await self.cleanup(voice_client)

    async def cleanup(self, voice_client):
        await voice_client.disconnect()
        print(f"{timestamp} Disconnected from {voice_client.channel.name} due to inactivity.")

    async def create_player_embed(self, interaction, player):
        print("create_player_embed_called")
        embed = discord.Embed(title="Now Playing", description=player.title, color=discord.Color.blue())
        embed.set_thumbnail(url=player.thumbnail)
        view = MusicView(self.client, self.current_embed_message)
        self.current_embed_message = await interaction.followup.send(embed=embed, view=view)
        print("followup embed sent")

    async def update_player_embed(self, guild_id, player):
        print("update_player_embed_called")
        embed = discord.Embed(title="Now Playing", description=player.title, color=discord.Color.blue())
        embed.set_thumbnail(url=player.thumbnail)
        view = MusicView(self.client, self.current_embed_message)

        if self.current_embed_message:
            print("deleting current embed message")
            await self.current_embed_message.delete()

        channel = self.text_channels.get(guild_id)
        if channel:
            self.current_embed_message = await channel.send(embed=embed, view=view)
            print("new embed sent")

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

    @app_commands.command(name="play", description="Play a song from a URL or search term")
    async def play(self, interaction: discord.Interaction, url: str):
        voice_state = interaction.user.voice

        if not voice_state or not voice_state.channel:
            await interaction.response.send_message("You are not connected to a voice channel.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if voice_client is None:
            voice_client = await voice_state.channel.connect(self_deaf=True)
        elif voice_client.channel != voice_state.channel:
            await voice_client.move_to(voice_state.channel)

        self.text_channels[interaction.guild_id] = interaction.channel  # Track the text channel

        try:
            print("fetching song")
            await interaction.response.defer(ephemeral=False)  # Defer here
            player = await YTDLSource.from_url(url, loop=self.client.loop, stream=True)
            print(f"{player.title} found")
            if voice_client.is_playing() or self.queue:
                print("trying to queue")
                self.queue.append(player)
                print("song added to queue")
                await interaction.followup.send(f"Added {player.title} to the queue.", ephemeral=False)
            else:
                voice_client.play(player, after=lambda e: self.client.loop.create_task(self.play_next(voice_client)))
                print(f'{timestamp} Now playing: {player.title}')
                await self.create_player_embed(interaction, player)
        except Exception as e:
            await interaction.followup.send(f'An error occurred: {str(e)}', ephemeral=False)

    async def play_next(self, voice_client):
        if self.queue:
            # If there are songs in the queue, play the next one
            player = self.queue.pop(0)
            voice_client.play(player, after=lambda e: self.client.loop.create_task(
                self.play_next(voice_client)) if e is None else print(f'{timestamp} Player error: {e}'))
            print(f'{timestamp} Now playing next song in queue: {player.title}')
            await self.update_player_embed(voice_client.guild.id, player)
        else:
            # If the queue is empty, wait for 5 minutes before disconnecting
            print(f"{timestamp} Queue is empty. Bot will remain in the voice channel for 5 minutes.")
            if self.current_embed_message:
                await self.current_embed_message.delete()
                self.current_embed_message = None
            await asyncio.sleep(300)  # 300 seconds = 5 minutes
            # Check if the queue is still empty after 5 minutes
            if not self.queue:
                print(f"{timestamp} Bot has been idle for 5 minutes. Disconnecting from voice channel.")
                await voice_client.disconnect()

    @app_commands.command(name="pause", description="Pause the currently playing song")
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if voice_client is None or not voice_client.is_playing():
            await interaction.response.send_message("There is no song currently playing.", ephemeral=True)
            return

        voice_client.pause()
        await interaction.response.send_message("Paused the currently playing song.", ephemeral=False)

    @app_commands.command(name="resume", description="Resume the currently paused song")
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if voice_client is None or not voice_client.is_paused():
            await interaction.response.send_message("There is no song currently paused.", ephemeral=True)
            return

        voice_client.resume()
        await interaction.response.send_message("Resumed the currently paused song.", ephemeral=False)

    @app_commands.command(name="skip", description="Skip the currently playing song")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if voice_client is None or not voice_client.is_playing():
            await interaction.response.send_message("There is no song currently playing to skip.", ephemeral=True)
            return

        if self.queue:
            next_song = self.queue[0]
            voice_client.stop()
            await self.create_player_embed(interaction, next_song)
        else:
            voice_client.stop()
            await interaction.channel.send("There are no more songs in the queue.")  # Send directly to the channel
            if self.current_embed_message:
                await self.current_embed_message.delete()
                self.current_embed_message = None


async def setup(client):
    await client.add_cog(Music(client))
