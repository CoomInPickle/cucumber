import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio
import time
from typing import Optional

PRESETS_PATH = "config/eq_presets.json"

class Equalizer(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client      = client
        self.eq_settings: dict[int, str] = {}
        self.presets     = self._load_presets()

    def _load_presets(self) -> dict:
        if os.path.exists(PRESETS_PATH):
            with open(PRESETS_PATH) as f:
                return json.load(f)
        return {}

    def build_filter(
        self,
        preset: Optional[str]   = None,
        bass:   Optional[int]   = None,
        treble: Optional[int]   = None,
        speed:  Optional[float] = None,
        pitch:  Optional[float] = None,
        reverb: bool            = False,
    ) -> str:
        if preset:
            return self.presets.get(preset, "")
        filters = []
        if bass   is not None: filters.append(f"bass=g={bass}")
        if treble is not None: filters.append(f"treble=g={treble}")
        if speed  is not None: filters.append(f"atempo={speed:.2f}")
        if pitch  is not None: filters.append(f"asetrate=44100*{pitch:.2f},aresample=44100")
        if reverb:              filters.append("aecho=0.8:0.88:60:0.4")
        return ",".join(filters)

    async def _apply_filter(self, interaction: discord.Interaction, ffmpeg_filter: str):
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message(
                "Nothing is playing right now.", ephemeral=True)

        guild_id  = interaction.guild.id
        music_cog = self.client.get_cog("Music")
        if not music_cog:
            return await interaction.response.send_message("Music cog unavailable.", ephemeral=True)

        gp = music_cog.get_player(guild_id)
        if not gp.current:
            return await interaction.response.send_message(
                "Could not find the current track.", ephemeral=True)

        song    = gp.current
        elapsed = gp.elapsed

        if song.duration and elapsed >= song.duration - 2:
            return await interaction.response.send_message(
                "Track is almost over, EQ not applied.", ephemeral=True)

        self.eq_settings[guild_id] = ffmpeg_filter

        before_opts = (
            f"-ss {elapsed} "
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        )
        af_opts = f"-vn -af {ffmpeg_filter}" if ffmpeg_filter else "-vn"

        try:
            new_source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(song.url, before_options=before_opts, options=af_opts),
                volume=0.5
            )
        except Exception as e:
            return await interaction.response.send_message(f"FFmpeg error: {e}", ephemeral=True)

        # Set flag BEFORE stop so _advance ignores the stop-triggered callback
        gp.eq_swapping = True
        vc.stop()
        await asyncio.sleep(0.05)

        def after_eq(err):
            if err:
                print(f"[EQ] Playback error: {err}")
            gp.eq_swapping = False
            self.client.loop.create_task(music_cog._advance(vc, guild_id))

        # Adjust start_time so elapsed tracking stays correct after the seek
        gp.start_time = time.time() - elapsed
        vc.play(new_source, after=after_eq)

        label = ffmpeg_filter or "flat"
        await interaction.response.send_message(
            f"🎚 EQ applied: `{label}` (resumed at {elapsed}s)")

    async def clear_eq(self, guild_id: int):
        self.eq_settings.pop(guild_id, None)

    # slash commands

    @app_commands.command(name="eq", description="Apply a preset EQ filter.")
    @app_commands.describe(preset="Choose a preset")
    async def eq_preset(self, interaction: discord.Interaction, preset: str):
        if preset not in self.presets:
            return await interaction.response.send_message(
                f"Preset `{preset}` not found.", ephemeral=True)
        await self._apply_filter(interaction, self.presets[preset])

    @eq_preset.autocomplete("preset")
    async def eq_autocomplete(self, _: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=n, value=n)
            for n in self.presets if current.lower() in n.lower()
        ][:25]

    @app_commands.command(name="eq_custom", description="Fine-tune EQ manually.")
    async def eq_custom(
        self,
        interaction: discord.Interaction,
        bass:   app_commands.Range[int,   -10, 20]  = 0,
        treble: app_commands.Range[int,   -10, 20]  = 0,
        speed:  app_commands.Range[float, 0.5, 2.0] = 1.0,
        pitch:  app_commands.Range[float, 0.5, 2.0] = 1.0,
        reverb: bool = False,
    ):
        f = self.build_filter(bass=bass, treble=treble, speed=speed, pitch=pitch, reverb=reverb)
        await self._apply_filter(interaction, f)

    @app_commands.command(name="eq_clear", description="Reset EQ to flat.")
    async def eq_clear(self, interaction: discord.Interaction):
        await self._apply_filter(interaction, "")
        await self.clear_eq(interaction.guild.id)


async def setup(client):
    await client.add_cog(Equalizer(client))
