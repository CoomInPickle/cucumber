import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import audioop
import random
import time
import json
import os
import shlex
import difflib
from data.variables import Timestamp
from data.ytdlp_pool import extract_single as _extract_single, extract_playlist_flat as _extract_playlist_flat
from data.spotify import (
    is_spotify_url as _is_spotify_url,
    resolve as _resolve_spotify,
    is_enabled_for_guild as _spotify_enabled_for_guild,
)
from data.deezer import (
    is_deezer_url as _is_deezer_url,
    resolve as _resolve_deezer,
)
FFMPEG_OPTIONS = {
    'options': '-vn',
    'before_options': (
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
        '-reconnect_on_network_error 1 -reconnect_on_http_error 403,429'
    )
}

EMOJI_PAUSE = "<:play_pause:1496237032538898574>"
EMOJI_PLAY  = "<:play:1496534605245841549>"
EMOJI_PREV  = "<:previous:1496237002230726666>"
EMOJI_NEXT  = "<:next:1496237059940028437>"
EMOJI_STOP  = "<:stop:1496536014620201235>"

FRAME_SIZE    = 3840  # discord.py PCM frame size (20ms @ 48kHz stereo 16-bit)
SETTINGS_PATH = "config/settings.json"

_DEFAULT_SETTINGS = {
    "defaults": {
        "crossfade":  False,
        "radio":      False,
        "loop":       False,
        "loop_queue": False,
    },
    "crossfade_duration": 6.0,
}

def _load_settings() -> dict:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                data = json.load(f)
            # Fill in any missing keys from defaults so old config files still work
            merged = dict(_DEFAULT_SETTINGS)
            merged["defaults"] = {**_DEFAULT_SETTINGS["defaults"], **data.get("defaults", {})}
            merged["crossfade_duration"] = data.get("crossfade_duration", _DEFAULT_SETTINGS["crossfade_duration"])
            return merged
        except Exception as e:
            print(f"[Config] Failed to load settings.json: {e}, using defaults")
    return dict(_DEFAULT_SETTINGS)

# Loaded once at import time. The Music cog re-reads this on each GuildPlayer creation
# so a restart picks up any changes.
_SETTINGS = _load_settings()
FADE_DURATION: float = _SETTINGS["crossfade_duration"]


class MixedSource(discord.AudioSource):
    """
    Holds two audio sources and linearly crossfades from src_a to src_b
    over FADE_DURATION seconds. Once the fade is complete it acts as src_b alone.

    discord.py reads 20ms frames (3840 bytes of signed 16-bit stereo PCM).
    We mix by scaling each frame's samples and summing them with audioop.add.
    """

    def __init__(self, src_a: discord.PCMVolumeTransformer,
                 src_b: discord.PCMVolumeTransformer):
        self.src_a   = src_a
        self.src_b   = src_b
        # How many frames make up the full fade window
        self._total  = int(FADE_DURATION * 50)   # 50 frames per second
        self._frame  = 0
        self._done   = False   # True when src_a is fully faded out

    def read(self) -> bytes:
        if self._done:
            return self.src_b.read()

        self._frame += 1
        progress = min(self._frame / self._total, 1.0)

        # Scale factors: a fades from 1→0, b fades from 0→1
        vol_a = 1.0 - progress
        vol_b = progress

        frame_a = self.src_a.read()
        frame_b = self.src_b.read()

        if not frame_a and not frame_b:
            return b""

        # Pad whichever ran short
        size = max(len(frame_a), len(frame_b)) or FRAME_SIZE
        frame_a = frame_a.ljust(size, b'\x00')
        frame_b = frame_b.ljust(size, b'\x00')

        # Apply per-source volume scaling then mix
        scaled_a = audioop.mul(frame_a, 2, vol_a)
        scaled_b = audioop.mul(frame_b, 2, vol_b)
        mixed    = audioop.add(scaled_a, scaled_b, 2)

        if progress >= 1.0:
            self._done = True
            self.src_a.cleanup()

        return mixed

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        try:
            self.src_a.cleanup()
        except Exception:
            pass
        try:
            self.src_b.cleanup()
        except Exception:
            pass


import re as _re

_TITLE_NOISE = _re.compile(
    r'\s*[\(\[（【][^\)\]）】]*?'
    r'(?:official|lyrics?|audio|video|hd|hq|4k|remaster|explicit|clean|live|acoustic|radio\s*edit|visuali[sz]er|\d{4})'
    r'[^\)\]）】]*?'
    r'[\)\]）】]',
    _re.IGNORECASE
)

def _clean_title(raw: str) -> str:
    title = _TITLE_NOISE.sub('', raw)
    title = _re.sub(r'\s*-\s*Topic\s*$', '', title, flags=_re.IGNORECASE)
    return title.strip(' -\u2013\u2014')


def _same_song(a_title: str, b_title: str, a_dur: int, b_dur: int) -> bool:
    """
    Rough check that two yt-dlp search results are actually the same track.
    Used to decide whether it's safe to mix the audio from one search result
    with the title/thumbnail from another — if they don't match, doing that
    gives you the wrong song with the "right" thumbnail.
    """
    if a_dur and b_dur and abs(a_dur - b_dur) > 12:
        return False
    ratio = difflib.SequenceMatcher(
        None, _clean_title(a_title).lower(), _clean_title(b_title).lower()
    ).ratio()
    return ratio >= 0.55


class Song:
    __slots__ = ('title', 'url', 'webpage_url', 'thumbnail', 'duration', 'requester', 'http_headers')

    def __init__(self, data: dict, requester=None):
        raw_title        = data.get('title', 'Unknown')
        self.title       = _clean_title(raw_title)
        self.url         = data.get('url', '')
        self.webpage_url = data.get('webpage_url', data.get('url', ''))
        self.thumbnail   = data.get('thumbnail', '')
        self.duration    = data.get('duration') or 0
        self.requester   = requester
        # yt-dlp's media URLs can require the same HTTP headers used during extraction.
        # Keep these with the resolved stream so ffmpeg makes an equivalent request.
        self.http_headers = dict(data.get('http_headers') or {})

    def duration_str(self) -> str:
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    @classmethod
    async def resolve(cls, query: str, requester=None) -> 'Song':
        is_url = query.startswith('http://') or query.startswith('https://')

        if is_url:
            # Direct URL — just resolve normally, no metadata enrichment needed
            data = await _extract_single(query)
            if data is None:
                raise ValueError(f"Could not resolve: {query}")
            return cls(data, requester)

        # For text searches, fetch lyrics video (audio) and official video (metadata) in parallel.
        # Lyrics videos have clean audio with no intros; official videos have the right
        # title, thumbnail, and album art.
        lyrics_query   = f"{query} lyrics"
        official_query = f"{query} official"

        lyrics_data, official_data = await asyncio.gather(
            _extract_single(lyrics_query),
            _extract_single(official_query),
            return_exceptions=True
        )

        # If both failed we have nothing
        if lyrics_data is None and official_data is None:
            raise ValueError(f"Could not resolve: {query}")

        # Use lyrics data as the base (has the audio URL we want)
        base = lyrics_data if lyrics_data and not isinstance(lyrics_data, Exception) else official_data
        if isinstance(base, Exception) or base is None:
            raise ValueError(f"Could not resolve: {query}")

        # Overlay title and thumbnail from the official result — but ONLY if it's
        # actually the same song as what we're about to play. The lyrics search and
        # official search are two independent YouTube searches; if their top hits
        # aren't the same track, mixing them gives you the wrong audio with a
        # mismatched (but "correct-looking") title/thumbnail.
        have_both = (
            official_data and not isinstance(official_data, Exception)
            and lyrics_data and not isinstance(lyrics_data, Exception)
        )
        if have_both and _same_song(
            lyrics_data.get('title', ''), official_data.get('title', ''),
            lyrics_data.get('duration') or 0, official_data.get('duration') or 0,
        ):
            base = dict(base)   # don't mutate the original
            base['title']     = official_data.get('title', base.get('title', 'Unknown'))
            base['thumbnail'] = _best_thumbnail(official_data) or base.get('thumbnail', '')
        # else: keep base's own title/thumbnail — self-consistent with the audio
        # that's actually going to play.

        return cls(base, requester)

    @classmethod
    async def resolve_fast(cls, query: str, requester=None) -> 'Song':
        """Single-search resolve — used when playback lands on an unresolved
        Spotify/Deezer stub (e.g. shuffle + fast skip) and needs something
        playable immediately. Skips the lyrics+official double-search that
        Song.resolve() normally does, since that doubles yt-dlp process-pool
        load at exactly the moment it's already under pressure from the
        background resolver. The background resolver will still overwrite
        this queue slot with the fully-enriched version once it gets to it."""
        data = await _extract_single(f"ytsearch1:{query}")
        if data is None:
            raise ValueError(f"Could not resolve: {query}")
        return cls(data, requester)


def _best_thumbnail(data: dict) -> str:
    """Pick the highest-resolution thumbnail from a yt-dlp info dict."""
    thumbs = data.get('thumbnails') or []

    if thumbs:
        # Sort by resolution (width * height), falling back to 0 if missing
        def res(t):
            return (t.get('width') or 0) * (t.get('height') or 0)

        with_url = [t for t in thumbs if t.get('url')]
        if with_url:
            best = max(with_url, key=res)
            url = best['url']
            # YouTube often has a maxresdefault that isn't in the thumbnails list —
            # swap it in if the URL looks like a YouTube video thumbnail
            import re as _r
            yt_vid = _r.search(r'/vi(?:_webp)?/([A-Za-z0-9_-]{11})/', url)
            if yt_vid:
                maxres = f"https://i.ytimg.com/vi/{yt_vid.group(1)}/maxresdefault.jpg"
                return maxres
            return url

    return data.get('thumbnail', '')


class GuildPlayer:
    def __init__(self):
        cfg = _load_settings()   # re-read on each player creation so restarts pick up changes
        d   = cfg.get("defaults", {})

        self.queue:         list[Song]                 = []
        self.history:       list[Song]                 = []
        self.current:       Song | None                = None
        self.text_channel:  discord.TextChannel | None = None
        self.embed_msg:     discord.Message | None     = None
        self.loop:          bool  = bool(d.get("loop",       False))
        self.loop_queue:    bool  = bool(d.get("loop_queue", False))
        self.radio:         bool  = bool(d.get("radio",      False))
        self.radio_preview: list[Song] = []
        self.start_time:    float = 0.0
        self.eq_swapping:   bool  = False
        self.paused:        bool  = False
        self.fade:          bool  = bool(d.get("crossfade",  False))
        self.fading:        bool  = False
        self.next_song:     Song | None = None
        self._fade_task:    asyncio.Task | None = None
        self.queue_msg:     discord.Message | None = None
        self._last_skip:    float = 0.0

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
        self.fade        = False
        self.fading      = False
        self.next_song   = None
        if self._fade_task:
            self._fade_task.cancel()
        self._fade_task = None
        self.queue_msg  = None
        self._last_skip = 0.0


class MusicView(discord.ui.View):
    def __init__(self, cog: 'Music', guild_id: int, paused: bool = False):
        super().__init__(timeout=None)
        self.cog      = cog
        self.guild_id = guild_id
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


class Music(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client   = client
        self._players: dict[int, GuildPlayer] = {}

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer()
        return self._players[guild_id]

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

    def _make_raw_source(self, song: Song, eq_filter: str = "") -> discord.PCMVolumeTransformer:
        options = f"-vn -af {eq_filter}" if eq_filter else "-vn"

        # YouTube media URLs are signed and can reject a request if ffmpeg does not
        # reproduce the headers yt-dlp used to obtain the URL. This is especially
        # common when the URL is handed from yt-dlp to a separate ffmpeg process.
        # Keep the important extraction headers on the Song and pass them through.
        before = FFMPEG_OPTIONS['before_options']
        headers = dict(song.http_headers or {})
        for key in ('Host', 'Content-Length', 'Accept-Encoding', 'Connection'):
            headers.pop(key, None)

        if headers:
            header_blob = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())
            before += f" -headers {shlex.quote(header_blob)}"

        return discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(
                song.url,
                before_options=before,
                options=options
            ),
            volume=0.5
        )

    async def _play_song(self, vc: discord.VoiceClient, song: Song, guild_id: int,
                          crossfade_from: discord.PCMVolumeTransformer | None = None):
        gp = self.get_player(guild_id)

        # Spotify/Deezer stubs start as just a search-string title with no url —
        # if playback reaches one before the background resolver gets to it
        # (e.g. shuffle + fast skip), resolve it here instead of trying to
        # play an empty audio source. Uses resolve_fast (single search) rather
        # than the full lyrics+official double-search, since that doubles
        # yt-dlp process-pool load at exactly the moment it's already busy.
        if not song.url and not song.webpage_url:
            try:
                song = await Song.resolve_fast(song.title, song.requester)
            except Exception as e:
                print(f"{Timestamp()} [Music] On-demand resolve failed for '{song.title}': {e}")
                return await self._advance(vc, guild_id)

        gp.current    = song
        gp.start_time = time.time()
        gp.paused = False
        gp.fading = False
        gp.next_song = None

        eq_cog    = self.client.get_cog("Equalizer")
        eq_filter = eq_cog.eq_settings.get(guild_id, "") if eq_cog else ""

        new_src = self._make_raw_source(song, eq_filter)

        if crossfade_from is not None:
            # Wrap both sources in the mixer — no vc.stop() needed
            source = MixedSource(crossfade_from, new_src)
        else:
            source = new_src

        def after_play(err):
            if err:
                print(f"{Timestamp()} [Music] Playback error: {err}")
            self.client.loop.create_task(self._advance(vc, guild_id))

        if crossfade_from is not None and vc.is_playing():
            # Replace the source in-place — discord.py supports this via vc.source assignment
            vc.source = source
        else:
            vc.play(source, after=after_play)

        await self._send_now_playing(guild_id, song, vc)
        print(f"{Timestamp()} [{vc.guild.name}] Now playing: {song.title}")

        if gp.radio and len(gp.radio_preview) < 2:
            radio_cog = self.client.get_cog("Radio")
            if radio_cog:
                asyncio.create_task(radio_cog.preload(guild_id, song))

        # Schedule the crossfade trigger if fade is on and duration is known
        if gp.fade and song.duration > FADE_DURATION + 2:
            trigger_at = song.duration - FADE_DURATION
            if gp._fade_task:
                gp._fade_task.cancel()
            gp._fade_task = asyncio.create_task(
                self._trigger_crossfade(vc, guild_id, trigger_at)
            )

    async def _trigger_crossfade(self, vc: discord.VoiceClient, guild_id: int, wait: float):
        """
        Waits until (duration - FADE_DURATION) seconds have elapsed, then resolves
        the next song and starts the MixedSource crossfade while the current song
        is still playing.
        """
        await asyncio.sleep(wait)

        gp = self.get_player(guild_id)
        if not vc.is_connected() or not vc.is_playing() or gp.fading:
            return

        # Work out what comes next (same logic as _advance, without consuming yet)
        next_song = None
        if gp.queue:
            next_song = gp.queue[0]
        elif gp.radio and gp.radio_preview:
            next_song = gp.radio_preview[0]

        if not next_song:
            return

        # Make sure the next song has a resolved stream URL
        if not next_song.url:
            return

        gp.fading    = True
        gp.next_song = next_song

        # Hold a reference to the outgoing source before we swap
        outgoing = vc.source

        # Consume the next song from whichever list it came from
        if gp.queue and gp.queue[0] is next_song:
            gp.queue.pop(0)
        elif gp.radio and gp.radio_preview and gp.radio_preview[0] is next_song:
            gp.radio_preview.pop(0)

        # Push current into history
        if gp.current:
            gp.history.append(gp.current)
            if len(gp.history) > 50:
                gp.history.pop(0)
            if gp.loop_queue:
                gp.queue.append(gp.current)

        # Start the crossfade — this replaces the source without stopping playback
        await self._play_song(vc, next_song, guild_id, crossfade_from=outgoing)

    async def _advance(self, vc: discord.VoiceClient, guild_id: int):
        if not vc.is_connected():
            return
        gp = self.get_player(guild_id)
        if gp.eq_swapping:
            return

        # If a crossfade already handled the transition, _advance is a no-op
        if gp.fading:
            gp.fading    = False
            gp.next_song = None
            return

        if gp._fade_task and not gp._fade_task.done():
            gp._fade_task.cancel()
            gp._fade_task = None

        current = gp.current

        if current:
            if gp.loop:
                try:
                    fresh = await Song.resolve(current.webpage_url, current.requester)
                    await self._play_song(vc, fresh, guild_id)
                except Exception as e:
                    print(f"{Timestamp()} [Music] Loop re-resolve failed: {e}")
                return

            gp.history.append(current)
            if len(gp.history) > 50:
                gp.history.pop(0)

            if gp.loop_queue:
                gp.queue.append(current)

        if gp.queue:
            next_song = gp.queue.pop(0)
            await self._play_song(vc, next_song, guild_id)
            return

        if gp.radio:
            radio_cog = self.client.get_cog("Radio")
            if radio_cog:
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

    async def _resolve_queue_background(self, gp: GuildPlayer, stubs: list['Song'], entries: list[dict], requester):
        sem = asyncio.Semaphore(4)  # cap concurrent lookups so we don't get rate-limited

        async def _resolve_one(stub: 'Song', entry: dict):
            url = entry.get('url') or entry.get('webpage_url', '')
            if not url:
                return
            async with sem:
                try:
                    data = await _extract_single(url)
                    if not data:
                        return
                    # Match by identity, not position — the queue may have been
                    # shuffled or edited since this stub was queued.
                    try:
                        idx = gp.queue.index(stub)
                    except ValueError:
                        return  # stub is no longer in the queue (removed/cleared)
                    gp.queue[idx] = Song(data, requester)
                except Exception:
                    pass

        await asyncio.gather(*(_resolve_one(stub, entry) for stub, entry in zip(stubs, entries)))

    async def _resolve_spotify_queue_background(self, gp: GuildPlayer, stubs: list['Song'], queries: list[str], requester):
        """Same idea as _resolve_queue_background, but for Spotify-sourced tracks —
        each 'entry' here is just a search string, not a yt-dlp flat-playlist entry,
        so it goes through Song.resolve() (a real YouTube search) instead of a
        direct URL extraction."""
        sem = asyncio.Semaphore(4)  # cap concurrent YouTube searches so we don't get rate-limited

        async def _resolve_one(stub: 'Song', search_query: str):
            async with sem:
                try:
                    song = await Song.resolve(search_query, requester)
                    # Match by identity, not position — the queue may have been
                    # shuffled or edited since this stub was queued.
                    try:
                        idx = gp.queue.index(stub)
                    except ValueError:
                        return  # stub is no longer in the queue (removed/cleared)
                    gp.queue[idx] = song
                except Exception:
                    pass

        await asyncio.gather(*(_resolve_one(stub, q) for stub, q in zip(stubs, queries)))

    async def _play_from_spotify(self, interaction: discord.Interaction, vc: discord.VoiceClient,
                                  gp: GuildPlayer, guild_id: int, url: str):
        """Handles a /play call where the query was a Spotify track/playlist/album
        link. Spotify never gives out actual audio, so this just turns the link
        into one or more "Artist - Title" search strings and resolves each one on
        YouTube exactly like a normal text search — see data/spotify.py."""
        try:
            queries = await _resolve_spotify(url)
        except Exception as e:
            return await interaction.followup.send(f"Couldn't read that Spotify link: {e}", ephemeral=True)

        if not queries:
            return await interaction.followup.send(
                "Couldn't find anything at that Spotify link. Make sure "
                "SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET are set correctly.", ephemeral=True)

        if len(queries) == 1:
            try:
                song = await Song.resolve(queries[0], interaction.user)
            except Exception as e:
                return await interaction.followup.send(f"Error: {e}", ephemeral=True)

            if vc.is_playing() or vc.is_paused() or gp.queue:
                gp.queue.append(song)
                await interaction.followup.send(f"Added **{song.title}** to queue (position {len(gp.queue)}).")
            else:
                await interaction.followup.send(f"Playing **{song.title}**")
                await self._play_song(vc, song, guild_id)
            return

        # Playlist/album — resolve the first track now so playback can start
        # immediately, queue placeholder stubs for the rest, and fill those in
        # for real in the background (same pattern used for YouTube playlists).
        try:
            first_song = await Song.resolve(queries[0], interaction.user)
        except Exception as e:
            return await interaction.followup.send(f"Couldn't resolve the first track: {e}", ephemeral=True)

        stubs = []
        for search_query in queries[1:]:
            stub               = Song.__new__(Song)
            stub.title         = search_query
            stub.url           = ''
            stub.webpage_url   = ''
            stub.thumbnail     = ''
            stub.duration      = 0
            stub.requester     = interaction.user
            stub.http_headers  = {}
            gp.queue.append(stub)
            stubs.append(stub)

        asyncio.create_task(self._resolve_spotify_queue_background(gp, stubs, queries[1:], interaction.user))

        if vc.is_playing() or vc.is_paused():
            gp.queue.insert(0, first_song)
            await interaction.followup.send(f"Added Spotify playlist — **{len(queries)} tracks** to queue.")
        else:
            await interaction.followup.send(f"Loaded Spotify playlist — **{len(queries)} tracks**.")
            await self._play_song(vc, first_song, guild_id)

    async def _play_from_deezer(self, interaction: discord.Interaction, vc: discord.VoiceClient,
                                gp: GuildPlayer, guild_id: int, url: str):
        """Handles a /play call where the query was a Deezer track/album/playlist
        link. Same idea as _play_from_spotify — Deezer doesn't hand out audio,
        so this turns the link into "Artist - Title" search strings and resolves
        each one on YouTube like a normal text search. See data/deezer.py."""
        try:
            queries = await _resolve_deezer(url)
        except Exception as e:
            return await interaction.followup.send(f"Couldn't read that Deezer link: {e}", ephemeral=True)

        if not queries:
            return await interaction.followup.send(
                "Couldn't find anything at that Deezer link.", ephemeral=True)

        if len(queries) == 1:
            try:
                song = await Song.resolve(queries[0], interaction.user)
            except Exception as e:
                return await interaction.followup.send(f"Error: {e}", ephemeral=True)

            if vc.is_playing() or vc.is_paused() or gp.queue:
                gp.queue.append(song)
                await interaction.followup.send(f"Added **{song.title}** to queue (position {len(gp.queue)}).")
            else:
                await interaction.followup.send(f"Playing **{song.title}**")
                await self._play_song(vc, song, guild_id)
            return

        try:
            first_song = await Song.resolve(queries[0], interaction.user)
        except Exception as e:
            return await interaction.followup.send(f"Couldn't resolve the first track: {e}", ephemeral=True)

        stubs = []
        for search_query in queries[1:]:
            stub = Song.__new__(Song)
            stub.title = search_query
            stub.url = ''
            stub.webpage_url = ''
            stub.thumbnail = ''
            stub.duration = 0
            stub.requester = interaction.user
            stub.http_headers = {}
            gp.queue.append(stub)
            stubs.append(stub)

        asyncio.create_task(self._resolve_spotify_queue_background(gp, stubs, queries[1:], interaction.user))

        if vc.is_playing() or vc.is_paused():
            gp.queue.insert(0, first_song)
            await interaction.followup.send(
                f"Added Deezer {'album' if len(queries) else ''} — **{len(queries)} tracks** to queue.")
        else:
            await interaction.followup.send(f"Loaded Deezer — **{len(queries)} tracks**.")
            await self._play_song(vc, first_song, guild_id)


    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        vc = member.guild.voice_client
        if vc and vc.channel and len(vc.channel.members) == 1:
            await asyncio.sleep(300)
            if vc.is_connected() and len(vc.channel.members) == 1:
                await self._cleanup(vc, member.guild.id)

    async def toggle_pause_resume(self, interaction: discord.Interaction, btn: discord.ui.Button):
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
            if gp.radio:
                return await interaction.response.send_message(
                    "Radio is loading the next song.", ephemeral=True)
            return await interaction.response.send_message("Nothing to skip.", ephemeral=True)
        # When radio is on and the preview is empty the next song needs to be fetched first.
        # Rate-limit skips to avoid stacking requests and give a friendly message.
        if gp.radio and not gp.queue and not gp.radio_preview:
            now = time.time()
            if now - gp._last_skip < 12:
                return await interaction.response.send_message(
                    "Woah, slow down there, I can't DJ faster than that.", ephemeral=True)
        gp._last_skip = time.time()
        # Cancel any in-progress fade so skip feels instant
        if gp._fade_task and not gp._fade_task.done():
            gp._fade_task.cancel()
            gp._fade_task = None
        gp.fading = False
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
        if gp._fade_task and not gp._fade_task.done():
            gp._fade_task.cancel()
            gp._fade_task = None
        gp.fading = False
        vc.stop()
        await interaction.response.defer()

    async def do_stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not connected.", ephemeral=True)
        await self._cleanup(vc, interaction.guild.id)
        await interaction.response.send_message("👋 Cya Later.")

    @app_commands.command(name="play", description="Play a song, album, or playlist from a URL or search.")
    @app_commands.describe(
        query="URL, album name, or search term",
        priority="Insert this song next in the queue instead of at the end"
    )
    async def play(self, interaction: discord.Interaction, query: str, priority: bool = False):
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

        is_url = query.startswith('http://') or query.startswith('https://')

        if is_url and await _is_spotify_url(query):
            if not _spotify_enabled_for_guild(guild_id):
                return await interaction.followup.send(
                    "Spotify links aren't enabled for this server. "
                    "An admin can turn them on from the dashboard.", ephemeral=True)
            return await self._play_from_spotify(interaction, vc, gp, guild_id, query)

        if is_url and await _is_deezer_url(query):
            return await self._play_from_deezer(interaction, vc, gp, guild_id, query)

        flat   = await _extract_playlist_flat(query)
        flat   = await _extract_playlist_flat(query)

        # For text queries that resolve to a single track, try album search as fallback
        if len(flat) <= 1 and not is_url:
            album_flat = await _extract_playlist_flat(f"ytsearch1:{query} full album")
            if len(album_flat) > 1:
                flat = album_flat

        is_playlist = len(flat) > 1

        if is_playlist:
            first_data = await _extract_single(
                flat[0].get('url') or flat[0].get('webpage_url', ''))
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
            if priority:
                gp.queue.insert(0, song)
                await interaction.followup.send(f"⏫ **{song.title}** added to the front of the queue.")
            else:
                gp.queue.append(song)
                await interaction.followup.send(f"Added **{song.title}** to queue (position {len(gp.queue)}).")
        else:
            await interaction.followup.send(f"Playing **{song.title}**")
            await self._play_song(vc, song, guild_id)

    @app_commands.command(name="shuffle", description="Shuffle the current queue.")
    async def shuffle(self, interaction: discord.Interaction):
        gp = self.get_player(interaction.guild.id)
        if not gp.queue:
            return await interaction.response.send_message("Queue is empty.", ephemeral=True)
        random.shuffle(gp.queue)
        await interaction.response.send_message(
            f"🔀 Shuffled **{len(gp.queue)}** song(s).", ephemeral=True
        )

    @app_commands.command(name="skip", description="Skip the current song.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        gp = self.get_player(interaction.guild.id)
        if not vc or not (vc.is_playing() or vc.is_paused()):
            if gp.radio:
                return await interaction.response.send_message("Radio is loading the next song.", ephemeral=True)
            return await interaction.response.send_message("Nothing to skip.", ephemeral=True)
        if gp.radio and not gp.queue and not gp.radio_preview:
            now = time.time()
            if now - gp._last_skip < 12:
                return await interaction.response.send_message(
                    "Woah, slow down there, I can't DJ faster than that.", ephemeral=True)
        gp._last_skip = time.time()
        if gp._fade_task and not gp._fade_task.done():
            gp._fade_task.cancel()
            gp._fade_task = None
        gp.fading = False
        vc.stop()
        await interaction.response.send_message("Skipped.", ephemeral=True)

    @app_commands.command(name="back", description="Go back to the previous song.")
    async def back(self, interaction: discord.Interaction):
        await self.go_back(interaction)

    @app_commands.command(name="leave", description="Stop music and leave.")
    async def leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Not connected.", ephemeral=True)
        await self._cleanup(vc, interaction.guild.id)
        await interaction.response.send_message("👋 Cya Later.")

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

    @app_commands.command(name="fade", description="Toggle crossfade between songs.")
    async def fade_cmd(self, interaction: discord.Interaction):
        gp = self.get_player(interaction.guild.id)
        gp.fade = not gp.fade
        await interaction.response.send_message(
            f"Crossfade {'enabled' if gp.fade else 'disabled'}.", ephemeral=True)

    @app_commands.command(name="remove", description="Remove a song from the queue by position.")
    @app_commands.describe(position="Position in the queue (1 = next up)")
    async def remove(self, interaction: discord.Interaction, position: int):
        gp = self.get_player(interaction.guild.id)
        if position < 1 or position > len(gp.queue):
            return await interaction.response.send_message("Invalid position.", ephemeral=True)
        removed = gp.queue.pop(position - 1)
        await interaction.response.send_message(f"Removed **{removed.title}**.", ephemeral=True)

    @app_commands.command(name="clearqueue", description="Clear the entire queue.")
    async def clearqueue(self, interaction: discord.Interaction):
        gp = self.get_player(interaction.guild.id)
        gp.queue.clear()
        await interaction.response.send_message("Queue cleared.", ephemeral=True)

    @property
    def queues(self) -> dict:
        return {gid: p.queue for gid, p in self._players.items()}

    def get_current(self, guild_id: int) -> Song | None:
        return self._players.get(guild_id, GuildPlayer()).current


async def setup(client):
    await client.add_cog(Music(client))
