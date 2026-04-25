import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re

from cogs.music import Song, _extract_single, _extract_playlist_flat

YT_ID_RE    = re.compile(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")
PRELOAD_MAX = 2   # keep this many songs ready in gp.radio_preview


class Radio(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client  = client
        self._seeds: dict[int, str] = {}          # guild_id → current seed video ID
        self._preloading: set[int]  = set()       # guard against concurrent preloads

    def _music(self):
        return self.client.get_cog("Music")

    @staticmethod
    def _yt_id(url: str) -> str | None:
        m = YT_ID_RE.search(url)
        return m.group(1) if m else None

    async def _resolve_seed_id(self, song: Song) -> str | None:
        vid = self._yt_id(song.webpage_url or "")
        if vid:
            return vid
        try:
            data = await asyncio.to_thread(_extract_single, f"ytsearch1:{song.title}")
            if data:
                return self._yt_id(data.get("webpage_url", ""))
        except Exception:
            pass
        return None

    async def _pick_from_radio(self, seed_id: str, seen: set[str]) -> tuple[dict | None, str | None]:
        """
        Fetch the YouTube Radio mix for seed_id, pick an unseen entry,
        return (chosen_entry_dict, new_seed_id).
        """
        radio_url = f"https://www.youtube.com/watch?v={seed_id}&list=RD{seed_id}"
        try:
            flat = await _extract_playlist_flat(radio_url)
        except Exception:
            return None, None

        if not flat:
            return None, None

        chosen = None
        for entry in flat:
            url = entry.get("url") or entry.get("webpage_url", "")
            if url and url not in seen:
                chosen = entry
                break
        if not chosen:
            chosen = flat[-1]

        new_seed = self._yt_id(chosen.get("url") or chosen.get("webpage_url", ""))
        return chosen, new_seed

    async def fetch_next(self, guild_id: int, current_song: Song) -> Song | None:
        """Fallback: fetch one song on the spot (used when preload isn't ready yet)."""
        seed_id = self._seeds.get(guild_id) or await self._resolve_seed_id(current_song)
        if not seed_id:
            return None
        self._seeds[guild_id] = seed_id

        music_cog = self._music()
        gp        = music_cog.get_player(guild_id) if music_cog else None
        seen      = set()
        if gp:
            seen = {s.webpage_url for s in gp.history if s.webpage_url}
            if current_song.webpage_url:
                seen.add(current_song.webpage_url)

        chosen, new_seed = await self._pick_from_radio(seed_id, seen)
        if not chosen:
            return None
        if new_seed:
            self._seeds[guild_id] = new_seed

        try:
            data = await asyncio.to_thread(
                _extract_single, chosen.get("url") or chosen.get("webpage_url", ""))
            if data:
                return Song(data, current_song.requester)
        except Exception as e:
            print(f"[Radio] fetch_next error: {e}")
        return None

    async def preload(self, guild_id: int, current_song: Song):
        """
        Background task: keep gp.radio_preview stocked with PRELOAD_MAX songs.
        Called from Music._play_song every time a new song starts.
        """
        if guild_id in self._preloading:
            return
        self._preloading.add(guild_id)

        music_cog = self._music()
        if not music_cog:
            self._preloading.discard(guild_id)
            return

        try:
            gp = music_cog.get_player(guild_id)
            while gp.radio and len(gp.radio_preview) < PRELOAD_MAX:
                seed_id = self._seeds.get(guild_id) or await self._resolve_seed_id(current_song)
                if not seed_id:
                    break
                self._seeds[guild_id] = seed_id

                seen = {s.webpage_url for s in gp.history if s.webpage_url}
                seen |= {s.webpage_url for s in gp.radio_preview if s.webpage_url}
                if current_song.webpage_url:
                    seen.add(current_song.webpage_url)

                chosen, new_seed = await self._pick_from_radio(seed_id, seen)
                if not chosen:
                    break
                if new_seed:
                    self._seeds[guild_id] = new_seed

                entry_url = chosen.get("url") or chosen.get("webpage_url", "")
                try:
                    data = await asyncio.to_thread(_extract_single, entry_url)
                    if data:
                        song = Song(data, current_song.requester)
                        gp.radio_preview.append(song)
                        print(f"[Radio] Preloaded: {song.title}")
                except Exception as e:
                    print(f"[Radio] preload error: {e}")
                    break

                await asyncio.sleep(0.2)   # brief pause between preloads
        finally:
            self._preloading.discard(guild_id)

    @app_commands.command(
        name="radio",
        description="Toggle radio mode — auto-plays related songs when the queue ends."
    )
    @app_commands.describe(query="Seed song (optional — uses current song if empty)")
    async def radio(self, interaction: discord.Interaction, query: str = ""):
        music_cog = self._music()
        if not music_cog:
            return await interaction.response.send_message("Music cog not loaded.", ephemeral=True)

        guild_id = interaction.guild.id
        gp       = music_cog.get_player(guild_id)

        # ── toggle OFF ──────────────────────────────────────────────────────
        if gp.radio and not query:
            gp.radio = False
            gp.radio_preview.clear()
            self._seeds.pop(guild_id, None)
            vc = interaction.guild.voice_client
            if gp.current and gp.embed_msg:
                try:
                    await gp.embed_msg.edit(embed=music_cog._build_embed(gp.current, gp, vc))
                except discord.NotFound:
                    pass
            return await interaction.response.send_message("📻 Radio mode **off**.", ephemeral=True)

        # ── toggle ON ───────────────────────────────────────────────────────
        if not interaction.user.voice:
            return await interaction.response.send_message("Join a voice channel first.", ephemeral=True)

        if gp.loop or gp.loop_queue:
            gp.loop = False
            gp.loop_queue = False

        await interaction.response.defer(ephemeral=True)

        vc = interaction.guild.voice_client
        if not vc:
            vc = await interaction.user.voice.channel.connect(self_deaf=True)
        gp.text_channel = interaction.channel

        # Resolve seed
        if query:
            try:
                seed = await Song.resolve(query, interaction.user)
            except Exception as e:
                return await interaction.followup.send(f"Couldn't find that song: {e}", ephemeral=True)
        elif gp.current:
            seed = gp.current
        else:
            return await interaction.followup.send(
                "Nothing is playing. Provide a song name or start playing first.", ephemeral=True)

        seed_id = await self._resolve_seed_id(seed)
        if not seed_id:
            return await interaction.followup.send(
                "Couldn't find a YouTube ID for that song.", ephemeral=True)

        self._seeds[guild_id] = seed_id
        gp.radio = True
        gp.radio_preview.clear()

        # Start preloading immediately
        asyncio.create_task(self.preload(guild_id, seed))

        if not vc.is_playing() and not vc.is_paused() and not gp.current:
            await music_cog._play_song(vc, seed, guild_id)
            return await interaction.followup.send(
                f"Radio mode **on** — playing **{seed.title}**.", ephemeral=True)

        # Refresh embed to show radio indicator
        if gp.current and gp.embed_msg:
            try:
                await gp.embed_msg.edit(embed=music_cog._build_embed(gp.current, gp, vc))
            except discord.NotFound:
                pass

        await interaction.followup.send(
            "Radio mode **on** — will auto-play related songs when the queue ends.",
            ephemeral=True)


async def setup(client):
    await client.add_cog(Radio(client))
