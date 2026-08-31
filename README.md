# Cucumber Bot

<div align="center">
  <img src="https://img.shields.io/badge/language-Python-blue">
  <img src="https://img.shields.io/github/issues/CoomInPickle/cucumber">
  <img src="https://img.shields.io/badge/license-MIT-green">
  <img src="https://img.shields.io/github/last-commit/CoomInPickle/cucumber">
</div>

Cucumber is a personal Discord bot built mainly for music, since there's no reliable free option that actually works. Also has some other stuff I find useful.

## Installation using Docker Compose

Tested on Ubuntu. No guarantees for anything else.

```yaml
version: '3.8'
services:
  cucumber-bot:
    image: coominpickle/cucumber:latest
    container_name: cucumber-discord-bot
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
      - APPLICATION_ID=${APPLICATION_ID}
      - INSTAGRAM_USERNAME=${INSTAGRAM_USERNAME}
      - INSTAGRAM_PASSWORD=${INSTAGRAM_PASSWORD}
      - SPOTIFY_CLIENT_ID=${SPOTIFY_CLIENT_ID}
      - SPOTIFY_CLIENT_SECRET=${SPOTIFY_CLIENT_SECRET}
      # See "Environment Variables" below for everything else you can set —
      # DASHBOARD_TOKEN, YTDLP_WORKERS, per-cog toggles, etc.
    volumes:
      - ./config:/app/config
      - ./data/guilds:/app/data/guilds
    restart: unless-stopped

  bgutil-provider:
    image: brainicism/bgutil-ytdlp-pot-provider:1.3.1
    container_name: bgutil-provider
    restart: unless-stopped
```

On first start, the bot automatically copies the default config files (including `eq_presets.json`) into your mounted `./config` folder if they're not already there. So just run it and you're good.

`bgutil-provider` is required — it's what yt-dlp uses to fetch YouTube PO tokens. Without it, extraction gets unreliable or fails outright for a lot of content.

The `./data/guilds` mount holds all per-server settings: autorole, saved embeds, autoresponder rules, Spotify link toggle, command permissions, and per-server music defaults. **Without this mount, all of that resets every time the container is recreated** (e.g. pulling a new image) — it's not optional if you want settings to survive updates.

### Cookies (optional but recommended)

Without cookies, some YouTube videos (age-restricted, region-locked, etc.) will fail. To add them:

1. Install the browser extension **Get cookies.txt LOCALLY** (available for Chrome and Firefox).
2. Go to [youtube.com](https://youtube.com) while logged in.
3. Click the extension and export cookies in **Netscape format**.
4. Save the file as `cookies.txt` and place it in your mounted `./config` folder.

The path inside the container is `config/cookies.txt`, which is what yt-dlp looks for automatically.

If you don't want to use cookies at all, just don't add the file — the bot will still work for most content.

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Your bot's token from the [Discord Developer Portal](https://discord.com/developers/applications). |
| `APPLICATION_ID` | Your application's ID from the same portal page. |

### Optional — features

| Variable | Default | Description |
|---|---|---|
| `INSTAGRAM_USERNAME` / `INSTAGRAM_PASSWORD` | — | Instagram login used by the `instaloader` fallback in the Instagram cog. Without these, yt-dlp is still tried first, but anything it can't grab (most photos, some carousels) will be skipped. See the [Instagram](#instagram) section. |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | — | Client-credentials app keys from the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). No user login needed. Without these, Spotify links are just treated as a normal text search instead of being resolved properly. Spotify link support also needs to be toggled on per-server from the dashboard even once these are set. |

### Optional — dashboard

| Variable | Default | Description |
|---|---|---|
| `DASHBOARD_PORT` | `8080` | Port the web dashboard listens on inside the container. |
| `DASHBOARD_TOKEN` | — | If set, every dashboard API request must include this value in an `X-Dashboard-Token` header. Leave unset for local/trusted networks; set it if you're exposing the dashboard port beyond your own machine. |

### Optional — performance

| Variable | Default | Description |
|---|---|---|
| `YTDLP_WORKERS` | `3` | Number of worker processes in the yt-dlp extraction pool (see `data/ytdlp_pool.py`). Each worker builds its own `YoutubeDL` instance and runs extraction in a separate process so it doesn't fight the voice-audio thread for the GIL. Raise this if you're running several servers with heavy concurrent `/play` usage and have the CPU to spare; lower it on constrained hosts. |

### Optional — disabling cogs

See [Disabling Cogs](#disabling-cogs) below — one `<NAME>_COG=false` variable per cog.

## Disabling Cogs

Cogs can be disabled by adding `<NAME>_COG=false` to your environment variables. Useful if you don't want the Instagram or Quotes features.

| Name         | Note |
|--------------|------|
| fun          | -    |
| instagram    | -    |
| music        | -    |
| music_eq     | -    |
| music_queue  | -    |
| music_radio  | -    |
| quote        | -    |
| system       | -    |
| embeds       | saved-embed manager (`/embed`, `/embeds`) |
| dashboard    | disables the entire web dashboard |

## Dashboard

The bot ships with a web dashboard (aiohttp, served from inside the bot process) at `http://<host>:8080` by default. It gives you a UI for everything that would otherwise need editing config files or restarting the bot:

- **Status** — servers, latency, what's currently playing.
- **Auto Role** — roles automatically assigned to new members.
- **Auto Responder** — trigger/response rules per server.
- **Embeds** — build and send custom embeds with a live preview, or trigger them via `/embed`.
- **Permissions** — restrict who can use certain command groups to specific roles (currently covers music commands — see [Permissions](#permissions) below).
- **Music Settings** — per-server defaults for crossfade, radio, loop, loop queue, crossfade duration, and the Spotify-links toggle.
- **EQ Presets** — add/remove `/eq` presets, hot-reloaded into the running bot.
- **Cog Manager** — load/unload cogs at runtime without a restart.
- **Log** — live tail of the bot's console output.

Set `DASHBOARD_TOKEN` if you're exposing the port outside a trusted network — every dashboard route except loading the page itself will require it.

## Permissions

Certain command groups can be restricted to specific roles, per server, from the **Permissions** tab of the dashboard. Right now this covers music commands (`/play`, `/skip`, `/loop`, EQ commands, `/radio`, etc.) — turning it on lets you pick which roles are allowed to use them.

A few notes on how it behaves:

- Off by default — with the toggle disabled, anyone can use the commands, same as before.
- Server admins (Administrator / Manage Server permission) and the server owner can always use gated commands, even with the restriction on, so you can't accidentally lock yourself out.
- If you enable the restriction but haven't picked any roles yet, only admins/owner can use the commands until you add some.
- This is a general framework under the hood, so more command groups may get their own permission toggle here in the future.

## Music

`/play` plays a song, playlist, or album. You can paste a YouTube/playlist URL or just search by name — album searches work too, e.g. `/play Dark Side of the Moon`. Add `priority:true` to insert a single track at the front of the queue instead of the end. The first track starts immediately and the rest load in the background.

`/skip` — skip current song  
`/back` — go back to previous song  
`/queue` — show the queue. If radio mode is on, preloaded radio songs show in a separate section at the bottom.  
`/shuffle` — randomly shuffle the current queue  
`/nowplaying` — show what's playing  
`/loop` — loop current song  
`/loopqueue` — loop the whole queue  
`/remove <position>` — remove a song from the queue  
`/clearqueue` — clear the queue  
`/leave` — stop and disconnect  

The player embed has four buttons: back, play/pause, skip, and a red stop button that disconnects the bot.

Default behavior for crossfade/radio/loop/loop queue, and the crossfade duration, can be set per-server from the dashboard's **Music Settings** tab.

### Radio

`/radio` toggles radio mode on and off. When on, the bot automatically continues playing related songs when the queue runs out — it doesn't spam your queue, it just picks the next song when needed. Two songs are preloaded in the background so transitions are smooth.

You can also seed the radio with a specific song: `/radio <song name>`.

Radio mode is shown in the now-playing embed and in `/queue`. Enabling loop or queue loop disables radio automatically.

### Equalizer

`/eq` — apply a preset filter (bassboost, nightcore, vaporwave, 8d, slowreverb)  
`/eq_custom` — manual controls for bass, treble, speed, pitch, reverb  
`/eq_clear` — reset to flat  

Presets are customizable via the `eq_presets.json` file in your config folder, or from the dashboard's **EQ Presets** tab. The file comes with a few examples to copy.

| Filter       | Example                               | Effect                  |
|--------------|---------------------------------------|-------------------------|
| Bass Boost   | `bass=g=15`                           | Boosts bass             |
| Treble Boost | `treble=g=5`                          | Boosts highs            |
| Speed Up     | `atempo=1.25`                         | Speeds up audio         |
| Slow Down    | `atempo=0.8`                          | Slows down audio        |
| Pitch Up     | `asetrate=48000*1.25,aresample=48000` | Raises pitch            |
| Pitch Down   | `asetrate=48000*0.8,aresample=48000`  | Lowers pitch            |
| 8D           | `apulsator=hz=0.09`                   | Panning effect          |
| Echo/Reverb  | `aecho=0.8:0.9:1000:0.3`             | Adds echo               |
| Lowpass      | `lowpass=f=3000`                      | Muffles highs           |
| Highpass     | `highpass=f=2000`                     | Removes lows            |

### Crossfade

`/fade` toggles crossfade between songs. When enabled, the current song fades out in the last few seconds and the next one starts immediately — similar to how Spotify handles it. The default on/off state and the fade duration are configurable per-server from the dashboard.

## Queue system

`/play` either plays a song or adds it to the queue. `/queue` shows what's in it with pagination. When radio mode is on, the preloaded upcoming radio songs are shown in a separate section.

## Quotes

`/quote` picks a random quote from any channel with "quote" in the name and renders it as an image with the user's avatar. Quotes need to be formatted like `"quote here" @user`, anything else is ignored.

Can be enabled/disabled with `QUOTE_COG=true/false`.

## Instagram

Automatically detects Instagram links, deletes the original message, and re-posts the media as an upload so it embeds properly. Supports reels, photos, and carousels (up to 10 items). Files over 24 MB are skipped.

Photos with a music track attached are merged into a video with audio using ffmpeg before being sent.

If media can't be downloaded, the bot falls back to reposting a clean version of the link with tracking params stripped.

### Setup

The bot tries two methods in order:

1. **yt-dlp** — works for reels and some public content. Uses `config/cookies.txt` if present.
2. **Instaloader** — fallback for photos and anything yt-dlp can't grab. Requires `INSTAGRAM_USERNAME`/`INSTAGRAM_PASSWORD` (see [Environment Variables](#environment-variables)).

On startup the bot logs in and saves a session file to `config/ig_session_<username>`. On subsequent restarts it reuses that session instead of logging in again. Don't delete it.

Can be enabled/disabled with `INSTAGRAM_COG=true/false`.

## Fun

Joins a random occupied voice channel every 2 hours with a ~4% chance and plays a sound. Skips if music is already playing.

## Issues / Suggestions

[Here](https://github.com/CoomInPickle/cucumber/issues)

## Contributions

Feel free to contribute. I'm always open to help or collaboration since I don't know how much I'll be able to keep up with this myself.

## License

MIT