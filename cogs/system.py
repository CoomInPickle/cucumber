import discord
from discord import app_commands
from discord.ext import commands

class system(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @app_commands.command(name="ping", description="test slash command")
    async def ping(self, interaction: discord.Interaction):
        bot_latency = round(self.client.latency * 1000)
        await interaction.response.send_message(f"Pong! {bot_latency} ms.", ephemeral=True)


    @app_commands.command(name="join", description="Join the voice channel.")
    async def join(self, interaction: discord.Interaction):
        channel = interaction.user.voice.channel if interaction.user.voice else None
        if not channel:
            await interaction.response.send_message("You are not connected to a voice channel.", ephemeral=True)
            return

        vc = interaction.guild.voice_client
        if vc:
            await vc.move_to(channel)
        else:
            await channel.connect(self_deaf=True)

        await interaction.response.send_message(f"Joined {channel.name} and deafened!", ephemeral=True)

async def setup(client):
    await client.add_cog(system(client))