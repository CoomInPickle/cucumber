"""
Per-guild role-based permission framework.

Permissions are grouped into "categories" — just a string key like "music".
For each category a guild can:
  - enable/disable the gate (disabled = open to everyone, the default)
  - pick which roles are allowed to use it

Right now only the "music" category is actually enforced anywhere (see
cogs/music.py, cogs/music_eq.py, cogs/music_radio.py) and configured from
the dashboard's Music Settings page. Adding a new gated feature later is
just:

    from data.permissions import require

    @app_commands.command(...)
    async def my_command(self, interaction: discord.Interaction):
        if not await require(interaction, "my_category"):
            return
        ...

...plus a small section in the dashboard that reads/writes the
"my_category" key via GET/POST /api/guild/{gid}/permissions (same object,
different key — see cogs/dashboard.py).

Server admins (Administrator / Manage Server) and the guild owner always
bypass every category, so nobody can accidentally lock themselves out.
"""

import json
import os

import discord

GUILDS_DIR = "data/guilds"


def _path(guild_id) -> str:
    return os.path.join(GUILDS_DIR, str(guild_id), "permissions.json")


def load_permissions(guild_id) -> dict:
    path = _path(guild_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_permissions(guild_id, data: dict):
    path = _path(guild_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_category(guild_id, category: str) -> dict:
    cfg = load_permissions(guild_id).get(category, {})
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "roles": [str(r) for r in cfg.get("roles", [])],
    }


def is_allowed(member: discord.Member, category: str) -> bool:
    """
    True if `member` may use commands gated under `category`.
    Fail-open: an unconfigured or disabled category lets everyone through.
    """
    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild or member.id == member.guild.owner_id:
        return True

    cfg = get_category(member.guild.id, category)
    if not cfg["enabled"]:
        return True

    allowed_roles = set(cfg["roles"])
    if not allowed_roles:
        # Gate is on but no roles picked yet — only admins/owner get through.
        return False

    member_role_ids = {str(r.id) for r in member.roles}
    return bool(allowed_roles & member_role_ids)


async def require(interaction: discord.Interaction, category: str) -> bool:
    """
    Convenience for slash commands / button callbacks. Returns True if
    allowed; otherwise sends an ephemeral denial and returns False.

        if not await require(interaction, "music"):
            return
    """
    if is_allowed(interaction.user, category):
        return True

    msg = f"🚫 You don't have permission to use {category} commands in this server."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass
    return False