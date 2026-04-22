import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
import time
from data.variables import Timestamp

# FFmpeg / yt-dlp config 

FFMPEG_OPTIONS = {
    'options': '-vn',
    'before_options': (
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
        '-reconnect_on_network_error 1'
    )
}

YTDL_OPTIONS = {
    'format': 'bestaudio[abr<=96]/bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'cookiefile': 'config/cookies.txt',
    'skip_download': True,
    'socket_timeout': 10,
    'retries': 3,
    'concurrent_fragment_downloads': 4,
}

YTDL_FLAT_OPTIONS = {
    **YTDL_OPTIONS,
    'extract_flat': 'in_playlist',
}

ytdl      = yt_dlp.YoutubeDL(YTDL_OPTIONS)
ytdl_flat = yt_dlp.YoutubeDL(YTDL_FLAT_OPTIONS)


# Song────

class Song:
    __slots__ = ('title', 'url', 'webpage_url', 'thumbnail', 'duration', 'requester')

    def __init__(self, data: dict, requester=None):
        self.title       = data.get('title', 'Unknown')
        self.url         = data.get('url', '')
        self.webpage_url = data.get('webpage_url', data.get('url', ''))
        self.thumbnail   = data.get('thumbnail', '')
        self.duration    = data.get('duration') or 0
        self.requester   = requester

    def duration_str(self) -> str:
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    @classmethod
    async def resolve(cls, query: str, requester=None) -> 'Song':
        data = await asyncio.to_thread(_extract_single, query)
        if data is None:
            raise ValueError(f"Could not resolve: {query}")
        return cls(data, requester)


def _extract_single(query: str) -> dict | None:
    try:
        info = ytdl.extract_info(query, download=False)
        if info is None:
            return None
        if 'entries' in info:
            entries = [e for e in info['entries'] if e]
            return entries[0] if entries else None
        return info
    except Exception as e:
        print(f"[yt-dlp] extract error: {e}")
        return None


async def _extract_playlist_flat(url: str) -> list[dict]:
    try:
        info = await asyncio.to_thread(lambda: ytdl_flat.extract_info(url, download=False))
        if info is None:
            return []
        entries = info.get('entries', [info])
        return [e for e in entries if e]
    except Exception as e:
        print(f"[yt-dlp] playlist extract error: {e}")
        return []


# Guild state ─

class GuildPlayer:
    def __init__(self):
        self.queue:         list[Song]                 = []
        self.history:       list[Song]                 = []
        self.current:       Song | None                = None
        self.text_channel:  discord.TextChannel | None = None
        self.embed_msg:     discord.Message | None     = None
        self.loop:          bool  = False
        self.loop_queue:    bool  = False
        self.radio:         bool  = False
        self.radio_preview: list[Song] = []   # up to 2 preloaded radio songs
        self.start_time:    float = 0.0
        self.eq_swapping:   bool  = False
        self.paused:        bool  = False     # track pause state for button emoji

    @property
    def elapsed(self) -> int:
        return int(time.time() - self.start_time) if self.start_time else 0

    def clear(self):
        self.queue.clear()
        self.history.clear()
        self.radio_preview.clear()
        self.current     = None
        self.loop        = False
        self.loop_queue  = False
        self.radio       = False
        self.start_time  = 0.0
        self.eq_swapping = False
        self.paused      = False


# UI─

EMOJI_PAUSE  = "<:play_pause:1496237032538898574>"
EMOJI_PLAY   = "<:play:1496534605245841549>"
EMOJI_PREV   = "<:previous:1496237002230726666>"
EMOJI_NEXT   = "<:next:1496237059940028437>"
EMOJI_STOP   = "<:stop:1496536014620201235>"


class MusicView(discord.ui.View):
    def __init__(self, cog: 'Music', guild_id: int, paused: bool = False):
        super().__init__(timeout=None)
        self.cog      = cog
        self.guild_id = guild_id
        # Set the correct play/pause emoji on creation
        self.pause_resume_button.emoji = discord.PartialEmoji.from_str(
            EMOJI_PLAY if paused else EMOJI_PAUSE
        )

    @discord.ui.button(emoji=discord.PartialEmoji.from_str(EMOJI_PREV), style=discord.ButtonStyle.primary)
    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.go_back(interaction)

    @discord.ui.button(emoji=discord.PartialEmoji.from_str(EMOJI_PAUSE), style=discord.ButtonStyle.primary)
    async def pause_resume_button(self, interaction: discord.Interaction, btn: discord.ui.Button):
        await self.cog.toggle_pause_resume(interaction, btn)

    @discord.ui.button(emoji=discord.PartialEmoji.from_str(EMOJI_NEXT), style=discord.ButtonStyle.primary)
    async def skip_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.do_skip(interaction)

    @discord.ui.button(emoji=discord.PartialEmoji.from_str(EMOJI_STOP), style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.do_stop(interaction)


# Cog

class Music(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client   = client
        self._players: dict[int, GuildPlayer] = {}

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer()
        return self._players[guild_id]

    # ── embed

    def _build_embed(self, song: Song, gp: GuildPlayer, vc: discord.VoiceClient) -> discord.Embed:
        title = "Now Playing"
        if gp.radio:
            title += "  •  Radio"

        embed = discord.Embed(
            title=title,
            description=f"**[{song.title}]({song.webpage_url})**\n`{song.duration_str()}`",
            color=discord.Color.from_rgb(51, 201, 0)
        )
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        if song.requester:
            embed.set_footer(
                text=f"Requested by {song.requester.display_name}",
                icon_url=song.requester.display_avatar.url
            )
        upcoming = gp.queue[:3]
        if upcoming:
            embed.add_field(
                name=f"{EMOJI_NEXT} Up next",
                value="\n".join(f"`{i+1}.` {s.title}" for i, s in enumerate(upcoming)),
                inline=False
            )
        return embed

    async def _send_now_playing(self, guild_id: int, song: Song, vc: discord.VoiceClient):
        gp = self.get_player(guild_id)
        await self._delete_embed(gp)
        if gp.text_channel:
            gp.embed_msg = await gp.text_channel.send(
                embed=self._build_embed(song, gp, vc),
                view=MusicView(self, guild_id, paused=False)
            )

    async def _delete_embed(self, gp: GuildPlayer):
        if gp.embed_msg:
            try:
                await gp.embed_msg.delete()
            except discord.NotFound:
                pass
            gp.embed_msg = None

    # playback

    async def _play_song(self, vc: discord.VoiceClient, song: Song, guild_id: int):
        gp            = self.get_player(guild_id)
        gp.current    = song
        gp.start_time = time.time()
        gp.paused     = False

        eq_cog    = self.client.get_cog("Equalizer")
        eq_filter = eq_cog.eq_settings.get(guild_id, "") if eq_cog else ""

        opts = dict(FFMPEG_OPTIONS)
        if eq_filter:
            opts['options'] = f"-vn -af {eq_filter}"

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song.url, **opts),
            volume=0.5
        )

        def after_play(err):
            if err:
                print(f"[Music] Playback error: {err}")
            self.client.loop.create_task(self._advance(vc, guild_id))

        vc.play(source, after=after_play)
        await self._send_now_playing(guild_id, song, vc)
        print(f"{Timestamp()} [{vc.guild.name}] Now playing: {song.title}")

        # Trigger background radio preload as soon as a song starts
        if gp.radio and len(gp.radio_preview) < 2:
            radio_cog = self.client.get_cog("Radio")
            if radio_cog:
                asyncio.create_task(radio_cog.preload(guild_id, song))

    async def _advance(self, vc: discord.VoiceClient, guild_id: int):
        if not vc.is_connected():
            return
        gp = self.get_player(guild_id)
        if gp.eq_swapping:
            return

        current = gp.current

        if current:
            if gp.loop:
                try:
                    fresh = await Song.resolve(current.webpage_url, current.requester)
                    await self._play_song(vc, fresh, guild_id)
                except Exception as e:
                    print(f"[Music] Loop re-resolve failed: {e}")
                return

            gp.history.append(current)
            if len(gp.history) > 50:
                gp.history.pop(0)

            if gp.loop_queue:
                gp.queue.append(current)

        # Normal queue first
        if gp.queue:
            next_song = gp.queue.pop(0)
            await self._play_song(vc, next_song, guild_id)
            return

        # Queue empty — use radio preview if available
        if gp.radio:
            radio_cog = self.client.get_cog("Radio")
            if radio_cog:
                # Pop from preloaded preview, or fetch on the spot as fallback
                if gp.radio_preview:
                    next_song = gp.radio_preview.pop(0)
                else:
                    next_song = await radio_cog.fetch_next(guild_id, current)

                if next_song:
                    await self._play_song(vc, next_song, guild_id)
                    return

        gp.current = None
        await self._delete_embed(gp)
        await self._delayed_cleanup(vc, guild_id)

    async def _delayed_cleanup(self, vc: discord.VoiceClient, guild_id: int):
        await asyncio.sleep(300)
        gp = self.get_player(guild_id)
        if vc.is_connected() and not vc.is_playing() and not vc.is_paused() and not gp.queue:
            await self._cleanup(vc, guild_id)

    async def _cleanup(self, vc: discord.VoiceClient, guild_id: int):
        gp = self.get_player(guild_id)
        await self._delete_embed(gp)
        eq_cog = self.client.get_cog("Equalizer")
        if eq_cog:
            await eq_cog.clear_eq(guild_id)
        gp.clear()
        await vc.disconnect()
        print(f"{Timestamp()} [{vc.guild.name}] Disconnected (cleanup).")

    async def _resolve_queue_background(self, gp: GuildPlayer, entries: list[dict], requester):
        for i, entry in enumerate(entries):
            url = entry.get('url') or entry.get('webpage_url', '')
            if not url:
                continue
            try:
                data = await asyncio.to_thread(_extract_single, url)
                if data and i < len(gp.queue):
                    gp.queue[i] = Song(data, requester)
            except Exception:
                pass
            await asyncio.sleep(0.3)

    # voice events

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        vc = member.guild.voice_client
        if vc and vc.channel and len(vc.channel.members) == 1:
            await asyncio.sleep(300)
            if vc.is_connected() and len(vc.channel.members) == 1:
                await self._cleanup(vc, member.guild.id)

    # button actions

    async def toggle_pause_resume(self, interaction: discord.Interaction,
                                   btn: discord.ui.Button):
        vc = interaction.guild.voice_client
        gp = self.get_player(interaction.guild.id)
        if not vc:
            return await interaction.response.send_message("Not in a voice channel.", ephemeral=True)

        if vc.is_playing():
            vc.pause()
            gp.paused = True
            btn.emoji = discord.PartialEmoji.from_str(EMOJI_PLAY)
        elif vc.is_paused():
            vc.resume()
            gp.paused = False
            btn.emoji = discord.PartialEmoji.from_str(EMOJI_PAUSE)
        else:
            return await interaction.response.send_message("Nothing is playing.", ephemeral=True)

        await interaction.response.edit_message(view=btn.view)

    async def do_skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        gp = self.get_player(interaction.guild.id)
        if not vc or not (vc.is_playing() or vc.is_paused()):
            # If radio is on and nothing is queued yet, don't say "nothing to skip"
            if gp.radio:
                return await interaction.response.send_message(
                    "Radio is loading the next song…", ephemeral=True)
            return await interaction.response.send_message("Nothing to skip.", ephemeral=True)
        vc.stop()
        await interaction.response.defer()

    async def go_back(self, interaction: discord.Interaction):
        gp = self.get_player(interaction.guild.id)
        vc = interaction.guild.voice_client
        if not gp.history:
            return await interaction.response.send_message("No previous songs.", ephemeral=True)
        prev = gp.history.pop()
        if gp.current:
            gp.queue.insert(0, gp.current)
        gp.queue.insert(0, prev)
        gp.current = None
        vc.stop()
        await interaction.response.defer()

    async def do_stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not connected.", ephemeral=True)
        await self._cleanup(vc, interaction.guild.id)
        await interaction.response.send_message("👋 Stopped.", ephemeral=True)

    # slash commands

    @app_commands.command(name="play", description="Play a song or YouTube playlist from a URL or search.")
    @app_commands.describe(query="URL or search term")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            return await interaction.response.send_message("Join a voice channel first.", ephemeral=True)

        await interaction.response.defer()

        guild_id = interaction.guild.id
        gp       = self.get_player(guild_id)
        channel  = interaction.user.voice.channel

        vc = interaction.guild.voice_client
        if not vc:
            vc = await channel.connect(self_deaf=True)
        elif vc.channel != channel:
            await vc.move_to(channel)

        gp.text_channel = interaction.channel

        flat = await _extract_playlist_flat(query)
        is_playlist = len(flat) > 1

        if is_playlist:
            first_data = await asyncio.to_thread(
                _extract_single, flat[0].get('url') or flat[0].get('webpage_url', ''))
            if not first_data:
                return await interaction.followup.send("Couldn't load first track.", ephemeral=True)
            first_song = Song(first_data, interaction.user)
            for entry in flat[1:]:
                stub             = Song.__new__(Song)
                stub.title       = entry.get('title', 'Unknown')
                stub.url         = entry.get('url') or entry.get('webpage_url', '')
                stub.webpage_url = stub.url
                stub.thumbnail   = entry.get('thumbnail', '')
                stub.duration    = entry.get('duration') or 0
                stub.requester   = interaction.user
                gp.queue.append(stub)
            asyncio.create_task(self._resolve_queue_background(gp, flat[1:], interaction.user))
            if vc.is_playing() or vc.is_paused():
                gp.queue.insert(0, first_song)
                await interaction.followup.send(f"Added playlist — **{len(flat)} tracks** to queue.")
            else:
                await interaction.followup.send(f"Loaded playlist — **{len(flat)} tracks**.")
                await self._play_song(vc, first_song, guild_id)
            return

        try:
            song = await Song.resolve(query, interaction.user)
        except Exception as e:
            return await interaction.followup.send(f"Error: {e}", ephemeral=True)

        if vc.is_playing() or vc.is_paused() or gp.queue:
            gp.queue.append(song)
            await interaction.followup.send(f"Added **{song.title}** to queue (position {len(gp.queue)}).")
        else:
            await interaction.followup.send(f"Playing **{song.title}**")
            await self._play_song(vc, song, guild_id)

    @app_commands.command(name="skip", description="Skip the current song.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        gp = self.get_player(interaction.guild.id)
        if not vc or not (vc.is_playing() or vc.is_paused()):
            if gp.radio:
                return await interaction.response.send_message("Radio is loading the next song…", ephemeral=True)
            return await interaction.response.send_message("Nothing to skip.", ephemeral=True)
        vc.stop()
        await interaction.response.send_message("⏭ Skipped.", ephemeral=True)

    @app_commands.command(name="back", description="Go back to the previous song.")
    async def back(self, interaction: discord.Interaction):
        await self.go_back(interaction)

    @app_commands.command(name="leave", description="Stop music and leave.")
    async def leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not connected.", ephemeral=True)
        await self._cleanup(vc, interaction.guild.id)
        await interaction.response.send_message("👋 Left.", ephemeral=True)

    @app_commands.command(name="nowplaying", description="Show what's currently playing.")
    async def nowplaying(self, interaction: discord.Interaction):
        gp = self.get_player(interaction.guild.id)
        vc = interaction.guild.voice_client
        if not gp.current:
            return await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        await interaction.response.send_message(embed=self._build_embed(gp.current, gp, vc))

    @app_commands.command(name="loop", description="Toggle loop for the current song.")
    async def loop_cmd(self, interaction: discord.Interaction):
        gp = self.get_player(interaction.guild.id)
        gp.loop = not gp.loop
        if gp.loop:
            gp.loop_queue = False
            if gp.radio:
                gp.radio = False
                gp.radio_preview.clear()
                return await interaction.response.send_message(
                    "Loop enabled. Radio mode disabled.", ephemeral=True)
        await interaction.response.send_message(
            f"Loop {'enabled' if gp.loop else 'disabled'}.", ephemeral=True)

    @app_commands.command(name="loopqueue", description="Toggle loop for the entire queue.")
    async def loopqueue_cmd(self, interaction: discord.Interaction):
        gp = self.get_player(interaction.guild.id)
        gp.loop_queue = not gp.loop_queue
        if gp.loop_queue:
            gp.loop = False
            if gp.radio:
                gp.radio = False
                gp.radio_preview.clear()
                return await interaction.response.send_message(
                    "Queue loop enabled. Radio mode disabled.", ephemeral=True)
        await interaction.response.send_message(
            f"Queue loop {'enabled' if gp.loop_queue else 'disabled'}.", ephemeral=True)

    @app_commands.command(name="remove", description="Remove a song from the queue by position.")
    @app_commands.describe(position="Position in the queue (1 = next up)")
    async def remove(self, interaction: discord.Interaction, position: int):
        gp = self.get_player(interaction.guild.id)
        if position < 1 or position > len(gp.queue):
            return await interaction.response.send_message("Invalid position.", ephemeral=True)
        removed = gp.queue.pop(position - 1)
        await interaction.response.send_message(f"🗑 Removed **{removed.title}**.", ephemeral=True)

    @app_commands.command(name="clearqueue", description="Clear the entire queue.")
    async def clearqueue(self, interaction: discord.Interaction):
        gp = self.get_player(interaction.guild.id)
        gp.queue.clear()
        await interaction.response.send_message("🧹 Queue cleared.", ephemeral=True)

    @property
    def queues(self) -> dict:
        return {gid: p.queue for gid, p in self._players.items()}

    def get_current(self, guild_id: int) -> Song | None:
        return self._players.get(guild_id, GuildPlayer()).current


async def setup(client):
    await client.add_cog(Music(client))
