import discord
from discord import app_commands
from discord.ext import commands
import datetime

# Variables
timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")  # Timestamp for logs

class system(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{timestamp} system cog loaded")

    @app_commands.command(name="ping", description="test slash command")
    async def ping(self, interaction: discord.Interaction):
        bot_latency = round(self.client.latency * 1000)
        await interaction.response.send_message(f"Pong! {bot_latency} ms.", ephemeral=True)


async def setup(client):
    await client.add_cog(system(client))