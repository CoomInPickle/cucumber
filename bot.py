import discord
from discord.ext import commands, tasks
import os
import asyncio
import Joking
from data.variables import BOT_TOKEN, APPLICATION_ID, timestamp


# Bot Setup
client = commands.Bot(command_prefix=commands.when_mentioned, intents=discord.Intents.default(), application_id=APPLICATION_ID)

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
