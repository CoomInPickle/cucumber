import discord
from discord.ext import commands
import json
import os
import sys
import asyncio
import logging
from collections import deque
from aiohttp import web
from data.variables import Timestamp

SETTINGS_PATH   = "config/settings.json"
EQ_PRESETS_PATH = "config/eq_presets.json"
DASHBOARD_PORT  = int(os.getenv("DASHBOARD_PORT", 8080))
LOG_MAX_LINES   = 500

_log_buffer: deque = deque(maxlen=LOG_MAX_LINES)


# ── log capture ───────────────────────────────────────────────────────────────
# Intercepts both logging records AND raw print() output so the dashboard
# log page shows everything the bot produces regardless of how it was emitted.

class _LogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        _log_buffer.append(self.format(record))


class _StdoutCapture:
    """Wraps the real stdout, tees every write into the log buffer."""
    def __init__(self, real):
        self._real = real

    def write(self, text: str):
        self._real.write(text)
        stripped = text.strip()
        if stripped:
            _log_buffer.append(stripped)

    def flush(self):
        self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


def _install_log_capture():
    # Capture logging module output
    handler = _LogHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger()
    if not any(isinstance(h, _LogHandler) for h in root.handlers):
        root.addHandler(handler)
    discord_log = logging.getLogger("discord")
    if not any(isinstance(h, _LogHandler) for h in discord_log.handlers):
        discord_log.addHandler(handler)

    # Capture print() output
    if not isinstance(sys.stdout, _StdoutCapture):
        sys.stdout = _StdoutCapture(sys.stdout)


# ── storage helpers ───────────────────────────────────────────────────────────

def _load_json(path: str, default) -> dict | list:
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _save_json(path: str, data: dict | list):
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _guild_path(guild_id: str, filename: str) -> str:
    path = os.path.join("guilds", str(guild_id))
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, filename)


def _load_guild(guild_id: str, filename: str, default) -> dict | list:
    return _load_json(_guild_path(guild_id, filename), default)


def _save_guild(guild_id: str, filename: str, data: dict | list):
    _save_json(_guild_path(guild_id, filename), data)


# ── aiohttp helpers ───────────────────────────────────────────────────────────

def _cors(resp: web.Response) -> web.Response:
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def json_resp(data, status=200) -> web.Response:
    return _cors(web.Response(
        text=json.dumps(data),
        status=status,
        content_type="application/json",
    ))


# ── cog ───────────────────────────────────────────────────────────────────────

class Dashboard(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client  = client
        self._app    = web.Application()
        self._runner = None
        self._site   = None
        _install_log_capture()
        self._setup_routes()

    def _setup_routes(self):
        r = self._app.router
        r.add_get("/",  self._serve_ui)
        r.add_route("OPTIONS", "/{path_info:.*}", self._options)

        # bot-level
        r.add_get ("/api/status",   self._api_status)
        r.add_get ("/api/guilds",   self._api_guilds)
        r.add_get ("/api/log",      self._api_log)
        r.add_post("/api/restart",  self._api_restart)

        # cogs
        r.add_get ("/api/cogs",     self._api_get_cogs)
        r.add_post("/api/cogs",     self._api_set_cogs)

        # bot-level music / eq
        r.add_get ("/api/settings", self._api_get_settings)
        r.add_post("/api/settings", self._api_set_settings)
        r.add_get ("/api/eq",       self._api_get_eq)
        r.add_post("/api/eq",       self._api_set_eq)
        r.add_post("/api/eq/delete",self._api_delete_eq)

        # per-guild
        r.add_get ("/api/guild/{gid}",              self._api_guild_info)
        r.add_get ("/api/guild/{gid}/roles",        self._api_roles)
        r.add_get ("/api/guild/{gid}/channels",     self._api_channels)

        r.add_get ("/api/guild/{gid}/autorole",     self._api_get_autorole)
        r.add_post("/api/guild/{gid}/autorole",     self._api_set_autorole)

        r.add_get ("/api/guild/{gid}/autoresponder",     self._api_get_autoresponder)
        r.add_post("/api/guild/{gid}/autoresponder",     self._api_set_autoresponder)

        r.add_get ("/api/guild/{gid}/embeds",       self._api_get_embeds)
        r.add_post("/api/guild/{gid}/embeds",       self._api_set_embeds)

    # ── static ────────────────────────────────────────────────────────────────

    async def _serve_ui(self, request: web.Request) -> web.Response:
        ui_path = os.path.join(os.path.dirname(__file__), "..", "dashboard_ui", "index.html")
        if not os.path.exists(ui_path):
            return web.Response(text="Place index.html in dashboard_ui/", status=404)
        with open(ui_path, encoding="utf-8") as f:
            html = f.read()
        return _cors(web.Response(text=html, content_type="text/html"))

    async def _options(self, request: web.Request) -> web.Response:
        return _cors(web.Response(status=204))

    # ── bot-level ─────────────────────────────────────────────────────────────

    async def _api_status(self, request: web.Request) -> web.Response:
        music_cog = self.client.get_cog("Music")
        guilds = []
        for g in self.client.guilds:
            vc = g.voice_client
            now_playing = None
            if music_cog:
                song = music_cog.get_current(g.id)
                if song:
                    now_playing = song.title
            guilds.append({
                "id":           str(g.id),
                "name":         g.name,
                "icon":         str(g.icon.url) if g.icon else None,
                "member_count": g.member_count,
                "in_voice":     vc is not None and vc.is_connected(),
                "playing":      vc is not None and vc.is_playing(),
                "now_playing":  now_playing,
            })
        return json_resp({
            "latency_ms": round(self.client.latency * 1000),
            "guilds":     guilds,
        })

    async def _api_guilds(self, request: web.Request) -> web.Response:
        return json_resp([
            {"id": str(g.id), "name": g.name, "icon": str(g.icon.url) if g.icon else None, "member_count": g.member_count}
            for g in self.client.guilds
        ])

    async def _api_log(self, request: web.Request) -> web.Response:
        return json_resp({"lines": list(_log_buffer)})

    async def _api_restart(self, request: web.Request) -> web.Response:
        print(f"{Timestamp()} [Dashboard] Restart requested via dashboard.")
        async def _do_restart():
            await asyncio.sleep(0.4)
            await self.client.close()
        asyncio.create_task(_do_restart())
        return json_resp({"ok": True})

    # ── cogs ──────────────────────────────────────────────────────────────────

    async def _api_get_cogs(self, request: web.Request) -> web.Response:
        # Discover all cog files on disk dynamically
        result = {}
        cogs_dir = os.path.join(os.path.dirname(__file__), "..", "cogs")
        if os.path.isdir(cogs_dir):
            for fname in sorted(os.listdir(cogs_dir)):
                if fname.endswith(".py"):
                    name = fname[:-3]
                    loaded = f"cogs.{name}" in self.client.extensions
                    result[name] = {"loaded": loaded}
        return json_resp(result)

    async def _api_set_cogs(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        # Build valid cog names from disk
        cogs_dir = os.path.join(os.path.dirname(__file__), "..", "cogs")
        valid = {f[:-3] for f in os.listdir(cogs_dir) if f.endswith(".py")} if os.path.isdir(cogs_dir) else set()
        results = {}
        for name, should_load in body.items():
            if name not in valid or name == "dashboard":
                continue
            ext = f"cogs.{name}"
            currently_loaded = ext in self.client.extensions
            try:
                if should_load and not currently_loaded:
                    await self.client.load_extension(ext)
                    results[name] = "loaded"
                elif not should_load and currently_loaded:
                    await self.client.unload_extension(ext)
                    results[name] = "unloaded"
                else:
                    results[name] = "unchanged"
            except Exception as e:
                results[name] = f"error: {e}"
                print(f"{Timestamp()} [Dashboard] Cog toggle error for {name}: {e}")
        print(f"{Timestamp()} [Dashboard] Cog changes: {results}")
        return json_resp({"ok": True, "results": results})

    # ── bot-level music / eq ──────────────────────────────────────────────────

    async def _api_get_settings(self, request: web.Request) -> web.Response:
        return json_resp(_load_json(SETTINGS_PATH, {}))

    async def _api_set_settings(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        _save_json(SETTINGS_PATH, body)
        return json_resp({"ok": True})

    async def _api_get_eq(self, request: web.Request) -> web.Response:
        return json_resp(_load_json(EQ_PRESETS_PATH, {}))

    async def _api_set_eq(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        _save_json(EQ_PRESETS_PATH, body)
        eq_cog = self.client.get_cog("Equalizer")
        if eq_cog:
            eq_cog.presets = body
        return json_resp({"ok": True})

    async def _api_delete_eq(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        name = body.get("name", "")
        if not name:
            return json_resp({"error": "Missing name"}, 400)
        presets = _load_json(EQ_PRESETS_PATH, {})
        if name not in presets:
            return json_resp({"error": "Preset not found"}, 404)
        del presets[name]
        _save_json(EQ_PRESETS_PATH, presets)
        eq_cog = self.client.get_cog("Equalizer")
        if eq_cog:
            eq_cog.presets = presets
        return json_resp({"ok": True})

    # ── per-guild helpers ─────────────────────────────────────────────────────

    def _guild(self, request: web.Request) -> discord.Guild | None:
        return self.client.get_guild(int(request.match_info["gid"]))

    async def _api_guild_info(self, request: web.Request) -> web.Response:
        g = self._guild(request)
        if not g:
            return json_resp({"error": "Guild not found"}, 404)
        return json_resp({"id": str(g.id), "name": g.name, "icon": str(g.icon.url) if g.icon else None, "member_count": g.member_count})

    async def _api_roles(self, request: web.Request) -> web.Response:
        g = self._guild(request)
        if not g:
            return json_resp({"error": "Guild not found"}, 404)
        roles = [
            {"id": str(r.id), "name": r.name, "color": str(r.color), "position": r.position}
            for r in g.roles if not r.is_default() and not r.managed
        ]
        roles.sort(key=lambda r: -r["position"])
        return json_resp(roles)

    async def _api_channels(self, request: web.Request) -> web.Response:
        g = self._guild(request)
        if not g:
            return json_resp({"error": "Guild not found"}, 404)
        channels = [
            {"id": str(c.id), "name": c.name, "type": "text"}
            for c in g.text_channels
        ]
        channels.sort(key=lambda c: c["name"])
        return json_resp(channels)

    # ── autorole ──────────────────────────────────────────────────────────────

    async def _api_get_autorole(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        return json_resp(_load_guild(gid, "autorole.json", {"enabled": False, "roles": []}))

    async def _api_set_autorole(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        _save_guild(gid, "autorole.json", body)
        print(f"{Timestamp()} [Dashboard] Autorole updated for {gid}")
        return json_resp({"ok": True})

    # ── autoresponder ─────────────────────────────────────────────────────────

    async def _api_get_autoresponder(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        return json_resp(_load_guild(gid, "autoresponder.json", []))

    async def _api_set_autoresponder(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        _save_guild(gid, "autoresponder.json", body)
        print(f"{Timestamp()} [Dashboard] Autoresponder updated for {gid}")
        return json_resp({"ok": True})

    # ── embeds ────────────────────────────────────────────────────────────────

    async def _api_get_embeds(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        return json_resp(_load_guild(gid, "embeds.json", {}))

    async def _api_set_embeds(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        _save_guild(gid, "embeds.json", body)
        print(f"{Timestamp()} [Dashboard] Embeds updated for {gid}")
        return json_resp({"ok": True})

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start_server(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", DASHBOARD_PORT)
        await self._site.start()
        print(f"{Timestamp()} [Dashboard] http://localhost:{DASHBOARD_PORT}")

    async def stop_server(self):
        if self._runner:
            await self._runner.cleanup()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.start_server()

    def cog_unload(self):
        asyncio.create_task(self.stop_server())

    # ── autorole enforcement ──────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        gid  = str(member.guild.id)
        data = _load_guild(gid, "autorole.json", {"enabled": False, "roles": []})
        if not data.get("enabled"):
            return
        roles_to_add = [
            member.guild.get_role(int(rid))
            for rid in data.get("roles", [])
            if member.guild.get_role(int(rid))
        ]
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Autorole")
                print(f"{Timestamp()} [Dashboard] Autorole: gave {len(roles_to_add)} role(s) to {member}")
            except discord.Forbidden:
                print(f"{Timestamp()} [Dashboard] Autorole: missing permissions in {member.guild.name}")


# module-level helpers that mirror _load_guild/_save_guild for use outside the class

def _load_guild(guild_id: str, filename: str, default) -> dict | list:
    return _load_json(_guild_path(guild_id, filename), default)


def _save_guild(guild_id: str, filename: str, data: dict | list):
    _save_json(_guild_path(guild_id, filename), data)


def _guild_path(guild_id: str, filename: str) -> str:
    path = os.path.join("guilds", str(guild_id))
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, filename)


async def setup(client):
    await client.add_cog(Dashboard(client))
