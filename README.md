# <p align="center"><strong>Cucumber Bot 🥒</strong></p>
<hr>
<div align="center">
  <img src="https://img.shields.io/badge/language-Python-blue">
  <img src="https://img.shields.io/github/issues/CoomInPickle/cucumber">
  <img src="https://img.shields.io/badge/license-MIT-green">
  <img src="https://img.shields.io/github/last-commit/CoomInPickle/cucumber">
</div>
<br>

Cucumber is a personal Discord bot which I want to use for all kinds of things like music, since there is no good one that is reliable.  
Also, I'm going to use it for other helpful stuff, but I'll decide on that later.

## Installation using Docker Compose  
The Docker container is tested on Ubuntu. I can't guarantee it works on anything else.

```yaml
version: '3.8'
services:
  cucumber-bot:
    image: coominpickle/cucumber:latest
    container_name: cucumber-discord-bot
    environment:
      - BOT_TOKEN=\${BOT_TOKEN}               # Bot token from dev portal
      - APPLICATION_ID=\${APPLICATION_ID}     # Application ID from dev portal
    restart: unless-stopped
```

## To-Do List

- [x] Add music playback feature  
- [x] ~~Create dynamic /help command~~ (help is already in the Discord /menu)  
- [ ] /queue command to list queue or clear, and maybe more  
- [x] Docker compose deployable  
- [x] !update command which will make the bot pull new files from GitHub (image automatically updates on new push)  
- [x] ~~Adjustable music quality~~ (always trying to get the best quality, anything else is pointless)  
- [ ] ~~Function to make a dedicated "console chat" for the bot, either through DM from only x user or only in the server x channel y.  
      This can maybe include logging but mainly certain commands like !sync and maybe stuff that changes permanently to the .env,
      mainly because IDK how to do permission roles right now.~~
- [x] Make embeds always the same length and maybe height, also change color to cucumber color.  
- [ ] Stop stuttering when bot is searching for a song while playing (partially fixed and only happening when not using direct link)
- [ ] Performance (it's good but could be better)

## Queue system
/play either plays a song or adds it to the queue. /queue shows the current queue. Thats all

## Equalizer
Apply real-time audio filters to currently playing songs using ```/eq```.
Filters are customizable via the eq_presets.json file. The file come pre-loaded with a few presets to apply or use as examples to create custom ones.


### Avalable FFmpeg filters:
| Filter Type  | Filter Code Example                   | Effect                    |
|--------------|---------------------------------------|---------------------------|
| Bass Boost   | `bass=g=15`                           | Boosts bass frequencies   |
| Treble Boost | `treble=g=5`                          | Boosts high frequencies   |
| Speed Up     | `atempo=1.25`                         | Speeds up audio           |
| Slow Down    | `atempo=0.8`                          | Slows down audio          |
| Pitch Up     | `asetrate=48000*1.25,aresample=48000` | Raises pitch              |
| Pitch Down   | `asetrate=48000*0.8,aresample=48000`  | Lowers pitch              |
| 8D           | `apulsator=hz=0.09`                   | Panning effect (3D audio) |
| Echo/Reverb  | `aecho=0.8:0.9:1000:0.3`              | Adds echo                 |
| Lowpass      | `lowpass=f=3000`                      | Muffles highs             |
| Highpass     | `highpass=f=2000`                     | Removes lows              |

## Issues / Suggestions
[Here](https://github.com/CoomInPickle/cucumber/issues "cucumber/issues")

## Contributions

Feel free to contribute to Cucumber, because IDK how much I can do or will do.  
I'm always open to collaboration or help.

## License

This project is licensed under the MIT License.
