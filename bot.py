import discord
from discord.ext import commands, tasks
from itertools import cycle
import os
import asyncio
import environ
import datetime
import Joking

# Variables
timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")  # Timestamp for logs

# Read .env file
env = environ.Env()
env.read_env()

# Bot Setup
BOT_TOKEN = env('BOT_TOKEN')
APPLICATION_ID = env("APPLICATION_ID")
client = commands.Bot(command_prefix="!", intents=discord.Intents.all(), application_id=APPLICATION_ID)




bot_status = cycle(["Pickle","Pa"])

@tasks.loop(seconds=30)
async def change_status():
    joke = Joking.DarkJoke()
    await client.change_presence(activity=discord.Game(joke))

@client.event
async def on_ready():
    print(f"{timestamp} Cucumber is connected to Discord")
    change_status.start()

@client.command(name="sync")
async def sync(ctx):
    synced = await client.tree.sync()
    print(f"{timestamp} Synced {len(synced)} command(s).")

async def load():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await client.load_extension(f"cogs.{filename[:-3]}")

async def main():
    async with client:
        await load()
        await client.start(BOT_TOKEN)

asyncio.run(main())
