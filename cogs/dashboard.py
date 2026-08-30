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
GUILDS_DIR      = "data/guilds"
DASHBOARD_PORT  = int(os.getenv("DASHBOARD_PORT", 8080))
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN")
LOG_MAX_LINES   = 500


@web.middleware
async def _auth_middleware(request, handler):
    if not DASHBOARD_TOKEN:
        return await handler(request)
    if request.method == "OPTIONS" or request.path == "/":
        return await handler(request)
    if request.headers.get("X-Dashboard-Token") != DASHBOARD_TOKEN:
        return json_resp({"error": "Unauthorized"}, 401)
    return await handler(request)

_log_buffer: deque = deque(maxlen=LOG_MAX_LINES)


class _LogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        _log_buffer.append(self.format(record))


class _StdoutCapture:
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
    if not isinstance(sys.stdout, _StdoutCapture):
        sys.stdout = _StdoutCapture(sys.stdout)


def _load_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _save_json(path: str, data):
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _guild_dir(guild_id: str) -> str:
    path = os.path.join(GUILDS_DIR, str(guild_id))
    os.makedirs(path, exist_ok=True)
    return path


def _guild_path(guild_id: str, filename: str) -> str:
    return os.path.join(_guild_dir(guild_id), filename)


def _load_guild(guild_id: str, filename: str, default):
    return _load_json(_guild_path(guild_id, filename), default)


def _save_guild(guild_id: str, filename: str, data):
    _save_json(_guild_path(guild_id, filename), data)


def safe_url(url):
    if not url:
        return None

    url = str(url).strip()

    if url.startswith(("http://", "https://")):
        return url

    return None

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


class Dashboard(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client  = client
        self._app    = web.Application(middlewares=[_auth_middleware])
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
        r.add_get ("/api/guild/{gid}/roles",    self._api_roles)
        r.add_get ("/api/guild/{gid}/channels", self._api_channels)

        # per-guild: autorole
        r.add_get ("/api/guild/{gid}/autorole", self._api_get_autorole)
        r.add_post("/api/guild/{gid}/autorole", self._api_set_autorole)

        # per-guild: autoresponder
        r.add_get ("/api/guild/{gid}/autoresponder", self._api_get_autoresponder)
        r.add_post("/api/guild/{gid}/autoresponder", self._api_set_autoresponder)

        # per-guild: spotify
        r.add_get ("/api/guild/{gid}/spotify", self._api_get_spotify)
        r.add_post("/api/guild/{gid}/spotify", self._api_set_spotify)

        # per-guild: embeds  (name-keyed: {name: embedData})
        r.add_get ("/api/guild/{gid}/embeds",         self._api_get_embeds)
        r.add_post("/api/guild/{gid}/embeds",         self._api_set_embeds)
        r.add_post("/api/guild/{gid}/embeds/send",    self._api_send_embed)

    async def _serve_ui(self, request: web.Request) -> web.Response:
        ui_path = os.path.join(os.path.dirname(__file__), "..", "dashboard_ui", "index.html")
        if not os.path.exists(ui_path):
            return web.Response(text="Place index.html in dashboard_ui/", status=404)
        with open(ui_path, encoding="utf-8") as f:
            html = f.read()
        return _cors(web.Response(text=html, content_type="text/html"))

    async def _options(self, request: web.Request) -> web.Response:
        return _cors(web.Response(status=204))

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

    async def _api_get_cogs(self, request: web.Request) -> web.Response:
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
        return json_resp({"ok": True, "results": results})

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

    def _guild(self, request: web.Request) -> discord.Guild | None:
        return self.client.get_guild(int(request.match_info["gid"]))

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
        channels = [{"id": str(c.id), "name": c.name} for c in g.text_channels]
        channels.sort(key=lambda c: c["name"])
        return json_resp(channels)

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

    async def _api_get_spotify(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        return json_resp(_load_guild(gid, "spotify.json", {"enabled": False}))

    async def _api_set_spotify(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        _save_guild(gid, "spotify.json", body)
        print(f"{Timestamp()} [Dashboard] Spotify links {'enabled' if body.get('enabled') else 'disabled'} for {gid}")
        return json_resp({"ok": True})


    async def _api_get_embeds(self, request: web.Request) -> web.Response:
        gid = request.match_info["gid"]
        return json_resp(_load_guild(gid, "embeds.json", {}))

    async def _api_set_embeds(self, request: web.Request) -> web.Response:
        """Replace the entire embeds dict for a guild (name → data)."""
        gid = request.match_info["gid"]
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)
        if not isinstance(body, dict):
            return json_resp({"error": "Expected object"}, 400)
        _save_guild(gid, "embeds.json", body)
        print(f"{Timestamp()} [Dashboard] Embeds updated for {gid} ({len(body)} entries)")
        return json_resp({"ok": True})

    async def _api_send_embed(self, request: web.Request) -> web.Response:
        """Send a saved embed to a channel via the bot. Looks up by name."""
        gid = request.match_info["gid"]
        try:
            body = await request.json()
        except Exception:
            return json_resp({"error": "Invalid JSON"}, 400)

        name = body.get("name")
        channel_id = body.get("channel_id")
        if not name or not channel_id:
            return json_resp({"error": "Missing name or channel_id"}, 400)

        embeds = _load_guild(gid, "embeds.json", {})
        if name not in embeds:
            return json_resp({"error": "Embed not found"}, 404)

        embed_data = embeds[name]
        channel = self.client.get_channel(int(channel_id))
        if not channel:
            return json_resp({"error": "Channel not found"}, 404)

        # Build discord embed
        color_hex = embed_data.get("color", "#5865F2").lstrip("#")
        try:
            color = discord.Color(int(color_hex, 16))
        except Exception:
            color = discord.Color.blurple()

        em = discord.Embed(
            title=embed_data.get("title") or None,
            description=embed_data.get("description") or None,
            color=color,
        )

        em.url = safe_url(embed_data.get("url"))

        author = embed_data.get("author", {})
        if author.get("name"):
            em.set_author(
                name=author["name"],
                url=safe_url(author.get("url")),
                icon_url=safe_url(author.get("icon_url")),
            )

        thumb = safe_url(embed_data.get("thumbnail"))
        if thumb:
            em.set_thumbnail(url=thumb)

        image = safe_url(embed_data.get("image"))
        if image:
            em.set_image(url=image)

        for field in embed_data.get("fields", []):
            em.add_field(
                name=field.get("name", "\u200b"),
                value=field.get("value", "\u200b"),
                inline=field.get("inline", False),
            )

        footer = embed_data.get("footer", {})
        if footer.get("text"):
            em.set_footer(
                text=footer["text"],
                icon_url=safe_url(footer.get("icon_url")),
            )

        try:
            content = embed_data.get("content") or None
            await channel.send(content=content, embed=em)
            print(f"{Timestamp()} [Dashboard] Sent embed '{name}' to #{channel.name}")
            return json_resp({"ok": True})
        except discord.Forbidden:
            return json_resp({"error": "Missing permissions to send in that channel"}, 403)
        except Exception as e:
            return json_resp({"error": str(e)}, 500)

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        gid   = str(message.guild.id)
        rules = _load_guild(gid, "autoresponder.json", [])
        if not rules:
            return
        content_lower = message.content.lower()
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            trigger  = rule.get("trigger", "").lower()
            response = rule.get("response", "")
            match    = rule.get("match", "contains")  # contains | exact | startswith
            if not trigger or not response:
                continue
            hit = False
            if match == "exact":
                hit = content_lower == trigger
            elif match == "startswith":
                hit = content_lower.startswith(trigger)
            else:
                hit = trigger in content_lower
            if hit:
                try:
                    await message.channel.send(response)
                except Exception:
                    pass
                break  # only first matching rule fires


async def setup(client):
    await client.add_cog(Dashboard(client))
