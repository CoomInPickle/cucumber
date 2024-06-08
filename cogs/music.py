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
    'quiet': True,
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


class Music(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{timestamp} music cog loaded")

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

        try:
            await interaction.response.defer(ephemeral=True)
            player = await YTDLSource.from_url(url, loop=self.client.loop, stream=True)
            voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)
            print(f'Now playing: {player.title}')

            # Wait until the voice client starts playing
            while not voice_client.is_playing():
                await asyncio.sleep(1)

            # Voice client started playing, send follow-up message
            await interaction.followup.send(f"Now playing: {player.title}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'An error occurred: {str(e)}', ephemeral=True)


async def setup(client):
    await client.add_cog(Music(client))
