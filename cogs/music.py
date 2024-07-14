import discord
from discord import app_commands
from discord.ext import commands
import datetime
import yt_dlp
import asyncio
from collections import deque

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
        self.duration = data.get('duration')

    def get_duration(self):
        minutes, seconds = divmod(self.duration, 60)
        return f"{int(minutes)}:{int(seconds):02d}"

    @classmethod
    async def from_url(cls, url, *, stream=False):
        ydl = yt_dlp.YoutubeDL(ytdl_format_options)
        data = await asyncio.to_thread(ydl.extract_info, url, download=not stream)

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
        self.queue = []
        self.played_songs = deque()  # Deque to track played songs
        self.current_embed_message = None
        self.text_channels = {}
        self.is_paused = False

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
        embed = discord.Embed(
            title="Now Playing",
            description=f"{player.title}\nDuration: {player.get_duration()}",
            color=discord.Color.from_rgb(51, 201, 0)
        )
        embed.set_thumbnail(url=player.thumbnail)
        view = MusicView(self.client, self)
        if self.current_embed_message:
            await self.current_embed_message.delete()
        self.current_embed_message = await interaction.followup.send(embed=embed, view=view)

    async def update_player_embed(self, guild_id, player):
        embed = discord.Embed(
            title="Now Playing",
            description=f"{player.title}\nDuration: {player.get_duration()}",
            color=discord.Color.from_rgb(51, 201, 0)
        )
        embed.set_thumbnail(url=player.thumbnail)
        view = MusicView(self.client, self)

        if self.current_embed_message:
            try:
                await self.current_embed_message.delete()
            except discord.errors.NotFound:
                pass

        channel = self.text_channels.get(guild_id)
        if channel:
            self.current_embed_message = await channel.send(embed=embed, view=view)

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
            await interaction.response.defer(ephemeral=False)  # Defer here
            player = await YTDLSource.from_url(url, stream=True)
            if voice_client.is_playing() or self.queue:
                self.queue.append(player)
                await interaction.followup.send(f"Added {player.title} to the queue.", ephemeral=False)
            else:
                voice_client.play(player, after=lambda e: self.client.loop.create_task(self.play_next(voice_client)))
                print(f'{timestamp} Now playing: {player.title}')
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
        if self.queue:
            player = self.queue.pop(0)
            self.played_songs.appendleft(player)  # Move the played song to played_songs
            voice_client.play(player, after=lambda e: self.client.loop.create_task(
                self.play_next(voice_client)) if e is None else print(f'{timestamp} Player error: {e}'))
            print(f'{timestamp} Now playing next song in queue: {player.title}')
            await self.update_player_embed(voice_client.guild.id, player)
        else:
            await asyncio.sleep(2)  # Wait a short period to ensure correct state check
            # Check if voice_client is connected and either playing or paused
            if voice_client.is_connected() and (voice_client.is_playing() or voice_client.is_paused()):
                print(f"{timestamp} Queue is empty but a song is currently playing or paused.")
            else:
                print(f"{timestamp} Queue is empty and no song is playing or paused.")
                print(f"{timestamp} Bot will remain in the voice channel for 5 minutes.")
                await asyncio.sleep(300)
                # Check again after 5 minutes
                if not self.queue and voice_client.is_connected() and not (
                        voice_client.is_playing() or voice_client.is_paused()):
                    print(f"{timestamp} Bot has been idle for 5 minutes. Disconnecting from voice channel.")
                    if self.current_embed_message:
                        try:
                            await self.current_embed_message.delete()
                        except discord.errors.NotFound:
                            pass  # Handle case where message is already deleted or doesn't exist
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
        await interaction.response.defer()  # Defer to prevent "application not responding"

    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if voice_client is None or not voice_client.is_playing():
            await interaction.response.defer()
            return

        if self.queue:
            next_song = self.queue.pop(0)
            voice_client.stop()
            voice_client.play(next_song, after=lambda e: self.client.loop.create_task(self.play_next(voice_client)))
            await self.update_player_embed(voice_client.guild.id, next_song)
        else:
            voice_client.stop()
            if self.current_embed_message:
                try:
                    await self.current_embed_message.delete()
                    self.current_embed_message = None
                except discord.errors.NotFound:
                    pass

        await interaction.response.defer()  # Defer to prevent "application not responding"

    async def back(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if voice_client is None or not voice_client.is_playing():
            await interaction.response.defer()
            print("Not in voice channel or no song is playing.")
            return

        if len(self.played_songs) > 0:
            previous_song = self.played_songs.pop()  # Get and remove the last played song
            current_song = voice_client.source
            self.queue.insert(0, current_song)
            voice_client.stop()  # Stop the current song playback

            # Play the previous song
            voice_client.play(previous_song, after=lambda e: self.client.loop.create_task(self.play_next(voice_client)))
            await self.update_player_embed(voice_client.guild.id, previous_song)
        else:
            print("No previous song in the history.")
            await interaction.response.send_message("No previous song to play.", ephemeral=True)

        await interaction.response.defer()  # Defer to prevent "application not responding"

    async def on_play_song(self, player):
        if self.played_songs and self.played_songs[-1].url == player.url:
            return  # Avoid adding duplicate songs
        self.played_songs.append(player)



async def setup(client):
    await client.add_cog(Music(client))
