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
    try:
        synced = await client.tree.sync()
        print(f"{timestamp} Synced {len(synced)} command(s).")

        # React with a thumbs up (Unicode value) if the sync is successful
        await ctx.message.add_reaction("\N{THUMBS UP SIGN}")

    except Exception as e:
        # Print the error for logging purposes
        print(f"{timestamp} Failed to sync commands: {e}")

        # React with a cross mark (Unicode value) if there was an issue
        await ctx.message.add_reaction("\N{CROSS MARK}")


async def load():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            try:
                # Attempt to load the extension
                await client.load_extension(f"cogs.{filename[:-3]}")
                print(f"{timestamp} Successfully loaded {filename}")
            except discord.ext.commands.errors.NoEntryPointError:
                # Handle the error if there is no setup function in the cog
                print(f"{timestamp} Failed to load {filename}: setup function not found.")
            except Exception as e:
                # Catch any other exceptions and print them for debugging
                print(f"{timestamp} Failed to load {filename}: {e}")


async def main():
    async with client:
        await load()
        await client.start(BOT_TOKEN)

asyncio.run(main())
