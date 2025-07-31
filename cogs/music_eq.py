import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from typing import Optional
import time

PRESETS_PATH = "data/eq_presets.json"

class Equalizer(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.eq_settings = {}
        self.presets = self.load_presets()

    def load_presets(self):
        if os.path.exists(PRESETS_PATH):
            with open(PRESETS_PATH, "r") as f:
                return json.load(f)
        return {}

    def get_ffmpeg_filter(
            self,
            preset: Optional[str] = None,
            bass=None,
            treble=None,
            speed=None,
            pitch=None,
            reverb=False
    ):
        if preset:
            return self.presets.get(preset, "")

        filters = []

        if bass is not None:
            filters.append(f"bass=g={bass}")
        if treble is not None:
            filters.append(f"treble=g={treble}")
        if speed is not None:
            filters.append(f"atempo={speed}")  # 0.5–2.0 range
        if pitch is not None:
            filters.append(f"asetrate=44100*{pitch},aresample=44100")  # 0.5–2.0 range
        if reverb:
            filters.append("aecho=0.8:0.88:60:0.4")  # simple reverb

        return ",".join(filters)

    def rebuild_source(self, data, ffmpeg_filter, offset_seconds=0):
        before_opts = f"-ss {offset_seconds} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        ffmpeg_opts = f"-vn -af {ffmpeg_filter}" if ffmpeg_filter else "-vn"
        source = discord.FFmpegPCMAudio(data['url'], before_options=before_opts, options=ffmpeg_opts)
        source.start_time = time.time() - offset_seconds  # set start_time here
        return source

    async def apply_eq(self, interaction: discord.Interaction, ffmpeg_filter: str):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message("Nothing is playing right now.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        self.eq_settings[guild_id] = ffmpeg_filter

        music_cog = self.client.get_cog("Music")
        if not music_cog or guild_id not in music_cog.current_sources:
            await interaction.response.send_message("Could not find the current track.", ephemeral=True)
            return

        current_player = music_cog.current_sources[guild_id]
        data = current_player.data

        music_cog = self.client.get_cog("Music")
        current_player = music_cog.current_sources[guild_id]
        start_time = getattr(current_player, "start_time", None)


        if start_time is None:
            await interaction.response.send_message("Couldn't track playback time. EQ not applied.", ephemeral=True)
            return

        elapsed = int(time.time() - start_time)
        duration = current_player.duration or 0

        if elapsed >= duration:
            await interaction.response.send_message("Track is almost over, skipping EQ change.", ephemeral=True)
            return
        new_source = self.rebuild_source(data, ffmpeg_filter, offset_seconds=elapsed)
        new_source.start_time = time.time() - elapsed
        vc.stop()
        vc.play(discord.PCMVolumeTransformer(new_source, volume=0.5),
                after=lambda e: self.client.loop.create_task(music_cog.play_next(vc)))

        await interaction.response.send_message(
            f"🎚 Equalizer updated (resumed at {elapsed}s): `{ffmpeg_filter or 'flat'}`")


    async def clear_eq(self, guild_id: int):
        self.eq_settings.pop(guild_id, None)

    @app_commands.command(name="eq", description="Apply a preset EQ filter to the current playback.")
    @app_commands.describe(preset="Choose an EQ preset")
    async def eq_preset(self, interaction: discord.Interaction, preset: str):
        if preset not in self.presets:
            await interaction.response.send_message(f"Preset '{preset}' not found.", ephemeral=True)
            return
        ffmpeg_filter = self.get_ffmpeg_filter(preset=preset)
        await self.apply_eq(interaction, ffmpeg_filter)

    @eq_preset.autocomplete("preset")
    async def eq_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=name, value=name)
            for name in self.presets.keys()
            if current.lower() in name.lower()
        ][:25]

    @app_commands.command(name="eq_custom", description="Customize EQ with more audio effects.")
    async def eq_custom(
            self,
            interaction: discord.Interaction,
            bass: app_commands.Range[int, 0, 10] = 5,
            treble: app_commands.Range[int, 0, 10] = 5,
            speed: app_commands.Range[float, 0.5, 2.0] = 1.0,
            pitch: app_commands.Range[float, 0.5, 2.0] = 1.0,
            reverb: bool = False
    ):
        ffmpeg_filter = self.get_ffmpeg_filter(
            bass=bass,
            treble=treble,
            speed=speed,
            pitch=pitch,
            reverb=reverb
        )
        await self.apply_eq(interaction, ffmpeg_filter)

    @app_commands.command(name="eq_clear", description="Clear the current EQ filter and reset to flat.")
    async def eq_clear(self, interaction: discord.Interaction):
        await self.apply_eq(interaction, "")
        await self.clear_eq(interaction.guild.id)


async def setup(client):
    await client.add_cog(Equalizer(client))
