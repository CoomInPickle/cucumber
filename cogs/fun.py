import discord
from discord.ext import commands, tasks
import asyncio
import random
import os

class Fun(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.active_vcs = set()
        self.random_sound_task.start()

    async def play_sound(self, voice_channel):
        try:
            vc = await voice_channel.connect()
        except discord.ClientException:
            vc = discord.utils.get(self.client.voice_clients, guild=voice_channel.guild)

        if not vc:
            return

        sound_path = "sounds/hi.mp3"
        if not os.path.exists(sound_path):
            return

        vc.play(discord.FFmpegPCMAudio(sound_path, options="-filter:a volume=5.0"))

        while vc.is_playing():
            await asyncio.sleep(1)

        await vc.disconnect()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if after.channel and after.channel != before.channel:
            print(f"[Fun Cog] {member.name} joined {after.channel.name}")
            self.active_vcs.add(after.channel)

    async def preload_active_voice_channels(self):
        await self.client.wait_until_ready()
        for guild in self.client.guilds:
            for vc in guild.voice_channels:
                if len(vc.members) > 0:
                    self.active_vcs.add(vc)

    @tasks.loop(seconds=7200)
    async def random_sound_task(self):
        if not self.active_vcs:
            return

        # Skip if the bot is already in a VC or playing audio
        for vc in self.client.voice_clients:
            if vc.is_connected() or vc.is_playing():
                print("[Fun Cog] Bot is already in use — skipping.")
                return

        if random.random() < 0.04255:
            vc = random.choice(list(self.active_vcs))
            if vc and len(vc.members) > 0:
                await self.play_sound(vc)

    @random_sound_task.before_loop
    async def before_random_sound_task(self):
        await self.client.wait_until_ready()
        await self.preload_active_voice_channels()
        print("[Fun Cog] Background loop ready.")

async def setup(client):
    await client.add_cog(Fun(client))
