import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from data.variables import timestamp

# Variables
load_dotenv()
# Function to dynamically generate a timestamp for logs
def current_timestamp():
    return timestamp

class DevCommands(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{current_timestamp()} dev_commands cog loaded")

    # Autocomplete function to suggest server names, scoped to 'leave' command only
    async def autocomplete_server(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=guild.name, value=guild.name)
            for guild in self.client.guilds if current.lower() in guild.name.lower()
        ]

    # Create a command group for 'dev' commands
    dev_group = app_commands.Group(name="dev", description="Dev related commands")

    # Subcommand for listing servers the bot is in
    @dev_group.command(name="servers", description="List servers the bot is in")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def servers(self, interaction: discord.Interaction):
        await self.list_servers(interaction)

    # Subcommand for leaving a specific server with autocomplete for server names
    @dev_group.command(name="leave", description="Leave a specified server")
    @discord.app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(server=autocomplete_server)  # Attach the autocomplete function here
    async def leave(self, interaction: discord.Interaction, server: str):
        await self.leave_server(interaction, server)

    # Subcommand for 'other_command' (placeholder for future functionality)
    @dev_group.command(name="other_command", description="Placeholder for other command functionality")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def other_command(self, interaction: discord.Interaction):
        await self.other_command(interaction)

    # Helper function to list all servers the bot is in
    async def list_servers(self, interaction: discord.Interaction):
        guilds = self.client.guilds
        server_names = "\n".join(guild.name for guild in guilds)
        await interaction.response.send_message(f"Servers the bot is in:\n{server_names}")

    # Helper function to leave a specified server
    async def leave_server(self, interaction: discord.Interaction, server: str):
        guild = discord.utils.find(lambda g: g.name == server, self.client.guilds)

        if guild:
            # Try to find a suitable channel to send the goodbye message
            channel = None

            # Check if the bot has sent a message before and can access the last channel it sent to
            # (This requires additional tracking that could be implemented based on your bot's behavior)
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
            await interaction.response.send_message(f"Successfully left the server: {server}")
        else:
            await interaction.response.send_message(f"Server not found: {server}")

    # Placeholder for other command functionality
    async def other_command(self, interaction: discord.Interaction):
        await interaction.response.send_message("Placeholder for 'other_command' functionality.")

    # Error handler for 'dev' commands
    @dev_group.error
    async def dev_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.MissingPermissions):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, discord.app_commands.CheckFailure):
            await interaction.response.send_message("You cannot use this command due to a check failure.",
                                                    ephemeral=True)
        else:
            await interaction.response.send_message(f"An error occurred: {error}", ephemeral=True)


# Setup function to load the cog
async def setup(client):
    await client.add_cog(DevCommands(client))
