import discord
from discord.ext import commands, tasks
import os
import asyncio
import Joking
from data.variables import BOT_TOKEN, APPLICATION_ID, Timestamp
import logging.handlers

# Bot Setup
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True  # optional, for other commands

client = commands.Bot(command_prefix=commands.when_mentioned, intents=intents, application_id=APPLICATION_ID)
discord.utils.setup_logging(level=logging.INFO, root=False)

@tasks.loop(seconds=30)
async def change_status():
    joke = Joking.DarkJoke()
    await client.change_presence(activity=discord.Game(joke))

@client.event
async def on_ready():
    print(f"{Timestamp()} Cucumber is connected to Discord")
    change_status.start()


@client.command(name="sync")
async def sync(ctx):
    try:
        synced = await client.tree.sync()
        print(f"{Timestamp()} Synced {len(synced)} command(s).")
        await ctx.message.add_reaction("\N{THUMBS UP SIGN}")

    except Exception as e:
        print(f"{Timestamp()} Failed to sync commands: {e}")
        await ctx.message.add_reaction("\N{CROSS MARK}")


async def load():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            try:
                await client.load_extension(f"cogs.{filename[:-3]}")
                print(f"{Timestamp()} Successfully loaded {filename}")
            except discord.ext.commands.errors.NoEntryPointError:
                print(f"{Timestamp()} Failed to load {filename}: setup function not found.")
            except Exception as e:
                print(f"{Timestamp()} Failed to load {filename}: {e}")

async def main():
    async with client:
        await load()
        await client.start(BOT_TOKEN)

asyncio.run(main())
