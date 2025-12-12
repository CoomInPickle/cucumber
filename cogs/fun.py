import discord
from discord.ext import commands, tasks
import asyncio
import random
import os

class Fun(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.active_vcs = set()
        self.original_names = {}
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

    async def check_existing_cuddles(self):
        CUDDLE_USERS = {338725844002406402, 253906713487474698}
        CUDDLE_NAME = "Cuddling VC 💞"

        for guild in self.client.guilds:
            for channel in guild.voice_channels:
                users = {m.id for m in channel.members}
                if users == CUDDLE_USERS:
                    if channel.id not in self.original_names:
                        self.original_names[channel.id] = channel.name
                    try:
                        await channel.edit(name=CUDDLE_NAME)
                    except:
                        pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if after.channel and after.channel != before.channel:
            print(f"[Fun Cog] {member.name} joined {after.channel.name}")
            self.active_vcs.add(after.channel)

        CUDDLE_USERS = {338725844002406402, 253906713487474698}
        CUDDLE_NAME = "Cuddling VC 💞"

        guild = member.guild

        for channel in guild.voice_channels:
            users = {m.id for m in channel.members}

            if CUDDLE_USERS.issubset(users) and len(users) == 2:
                if channel.id not in self.original_names:
                    self.original_names[channel.id] = channel.name
                if channel.name != CUDDLE_NAME:
                    try:
                        await channel.edit(name=CUDDLE_NAME)
                    except:
                        pass
            else:
                if channel.id in self.original_names:
                    original = self.original_names[channel.id]
                    if channel.name != original:
                        try:
                            await channel.edit(name=original)
                        except:
                            pass
                    del self.original_names[channel.id]

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
        await self.check_existing_cuddles()
        print("[Fun Cog] Background loop ready.")

async def setup(client):
    await client.add_cog(Fun(client))
