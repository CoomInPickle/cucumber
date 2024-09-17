import discord
from discord.ext import commands
from data.variables import timestamp, DEV_USER

# Check function to restrict commands to DEV_USER
def is_dev_user():
    async def predicate(ctx):
        return ctx.author.id == DEV_USER
    return commands.check(predicate)

class DevCommands(commands.Cog):
    def __init__(self, client):
        self.client = client

    # Command to list servers the bot is in
    @commands.command(name="servers", help="List servers the bot is in")
    @is_dev_user()
    async def servers(self, ctx):
        try:
            await self.list_servers(ctx)
            await ctx.message.add_reaction("\N{THUMBS UP SIGN}")  # Thumbs up if successful
        except Exception as e:
            print(f"{timestamp} Error in 'servers' command: {e}")
            await ctx.message.add_reaction("\N{CROSS MARK}")  # Cross mark if there's an error

    # Command to leave a specific server
    @commands.command(name="leave", help="Leave a specified server")
    @is_dev_user()
    async def leave(self, ctx, *, server_name: str):
        try:
            await self.leave_server(ctx, server_name)
            await ctx.message.add_reaction("\N{THUMBS UP SIGN}")  # Thumbs up if successful
        except Exception as e:
            print(f"{timestamp} Error in 'leave' command: {e}")
            await ctx.message.add_reaction("\N{CROSS MARK}")  # Cross mark if there's an error

    # Helper function to list all servers the bot is in
    async def list_servers(self, ctx):
        guilds = self.client.guilds
        server_names = "\n".join(guild.name for guild in guilds)
        await ctx.send(f"Servers the bot is in:\n{server_names}")

    # Helper function to leave a specified server
    async def leave_server(self, ctx, server_name: str):
        guild = discord.utils.find(lambda g: g.name == server_name, self.client.guilds)

        if guild:
            # Try to find a suitable channel to send the goodbye message
            channel = None

            # Fallback: get the first text channel it has permission to send a message in
            if not channel:
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        channel = ch
                        break

            # Send a message if a channel is found
            if channel:
                await channel.send(f"The bot is now leaving the server: {guild.name}. Goodbye!")

            # Leave the server
            await guild.leave()

            # Confirm action to the user who issued the command
            await ctx.send(f"Successfully left the server: {server_name}")
        else:
            await ctx.send(f"Server not found: {server_name}")

# Setup function to load the cog
"""
async def setup(client):
    await client.add_cog(DevCommands(client))
"""