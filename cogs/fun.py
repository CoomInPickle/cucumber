import discord
from discord.ext import commands, tasks
import asyncio
import random
import os

SOUND_PATH = "sounds/hi.mp3"


class Fun(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client     = client
        self.active_vcs: set[discord.VoiceChannel] = set()
        self.random_sound_task.start()

    def cog_unload(self):
        self.random_sound_task.cancel()

    async def play_sound(self, voice_channel: discord.VoiceChannel):
        if not os.path.exists(SOUND_PATH):
            print("[Fun] Sound file not found:", SOUND_PATH)
            return

        # Don't interrupt the music bot
        for existing_vc in self.client.voice_clients:
            if existing_vc.guild == voice_channel.guild and existing_vc.is_playing():
                print("[Fun] Music is playing — skipping.")
                return

        try:
            vc = await voice_channel.connect()
        except discord.ClientException:
            # Already connected somewhere in this guild
            return
        except Exception as e:
            print(f"[Fun] Could not connect: {e}")
            return

        vc.play(discord.FFmpegPCMAudio(SOUND_PATH, options="-filter:a volume=5.0"))

        while vc.is_playing():
            await asyncio.sleep(0.5)

        await vc.disconnect()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if after.channel and after.channel != before.channel:
            self.active_vcs.add(after.channel)
        # Clean up empty channels from the set
        self.active_vcs = {vc for vc in self.active_vcs if len(vc.members) > 0}

    @tasks.loop(seconds=7200)
    async def random_sound_task(self):
        if not self.active_vcs:
            return

        populated = [vc for vc in self.active_vcs if len(vc.members) > 0]
        if not populated:
            return

        # ~4.25% chance every 2 hours
        if random.random() < 0.0425:
            target = random.choice(populated)
            await self.play_sound(target)

    @random_sound_task.before_loop
    async def before_loop(self):
        await self.client.wait_until_ready()
        for guild in self.client.guilds:
            for vc in guild.voice_channels:
                if len(vc.members) > 0:
                    self.active_vcs.add(vc)
        print("[Fun] Background loop ready.")


async def setup(client):
    await client.add_cog(Fun(client))
