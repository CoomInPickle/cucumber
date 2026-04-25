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
    volumes:
      - ./config:/app/config
    restart: unless-stopped
```

On first start, the bot automatically copies the default config files (including `eq_presets.json`) into your mounted `./config` folder if they're not already there. So just run it and you're good.

### Cookies (optional but recommended)

Without cookies, some YouTube videos (age-restricted, region-locked, etc.) will fail. To add them:

1. Install the browser extension **Get cookies.txt LOCALLY** (available for Chrome and Firefox).
2. Go to [youtube.com](https://youtube.com) while logged in.
3. Click the extension and export cookies in **Netscape format**.
4. Save the file as `cookies.txt` and place it in your mounted `./config` folder.

The path inside the container is `config/cookies.txt`, which is what yt-dlp looks for automatically.

If you don't want to use cookies at all, just don't add the file — the bot will still work for most content.

### Disabling Cogs

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

## Music

`/play` plays a song, playlist, or album. You can paste a YouTube/playlist URL or just search by name — album searches work too, e.g. `/play Dark Side of the Moon`. The first track starts immediately and the rest load in the background.

`/skip` — skip current song  
`/back` — go back to previous song  
`/queue` — show the queue. If radio mode is on, preloaded radio songs show in a separate section at the bottom.  
`/nowplaying` — show what's playing  
`/loop` — loop current song  
`/loopqueue` — loop the whole queue  
`/remove <position>` — remove a song from the queue  
`/clearqueue` — clear the queue  
`/leave` — stop and disconnect  

The player embed has four buttons: back, play/pause, skip, and a red stop button that disconnects the bot.

### Radio

`/radio` toggles radio mode on and off. When on, the bot automatically continues playing related songs when the queue runs out — it doesn't spam your queue, it just picks the next song when needed. Two songs are preloaded in the background so transitions are smooth.

You can also seed the radio with a specific song: `/radio <song name>`.

Radio mode is shown in the now-playing embed and in `/queue`. Enabling loop or queue loop disables radio automatically.

### Equalizer

`/eq` — apply a preset filter (bassboost, nightcore, vaporwave, 8d, slowreverb)  
`/eq_custom` — manual controls for bass, treble, speed, pitch, reverb  
`/eq_clear` — reset to flat  

Presets are customizable via the `eq_presets.json` file in your config folder. The file comes with a few examples to copy.

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

`/fade` toggles crossfade between songs. When enabled, the current song fades out in the last few seconds and the next one starts immediately — similar to how Spotify handles it.

## Queue system

`/play` either plays a song or adds it to the queue. `/queue` shows what's in it with pagination. When radio mode is on, the preloaded upcoming radio songs are shown in a separate section.

## Quotes

`/quote` picks a random quote from any channel with "quote" in the name and renders it as an image with the user's avatar. Quotes need to be formatted like `"quote here" @user`, anything else is ignored.

Can be enabled/disabled with `QUOTE_COG=true/false`.

## Instagram

Automatically detects Instagram links, deletes the original message, and re-posts the media as an upload so it embeds properly. Supports reels, photos, and carousels (up to 4 images/videos at once). Files over 24 MB are skipped.

Can be enabled/disabled with `INSTAGRAM_COG=true/false`.

## Fun

Joins a random occupied voice channel every 2 hours with a ~4% chance and plays a sound. Skips if music is already playing.

## Issues / Suggestions

[Here](https://github.com/CoomInPickle/cucumber/issues)

## Contributions

Feel free to contribute. I'm always open to help or collaboration since I don't know how much I'll be able to keep up with this myself.

## License

MIT
