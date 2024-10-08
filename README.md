# Cucumber Bot 🥒

![Python](https://img.shields.io/badge/language-Python-blue)  
![License](https://img.shields.io/badge/license-MIT-green)  
![Last Commit](https://img.shields.io/github/last-commit/CoomInPickle/cucumber)  
![Issues](https://img.shields.io/github/issues/CoomInPickle/cucumber)  

## Overview  

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
- [ ] Function to make a dedicated "console chat" for the bot, either through DM from only x user or only in the server x channel y.  
      This can maybe include logging but mainly certain commands like !sync and maybe stuff that changes permanently to the .env,
      mainly because IDK how to do permission roles right now.  
- [x] Make embeds always the same length and maybe height, also change color to cucumber color.  
- [x] Stop stuttering when bot is searching for a song while playing (partially fixed and only happening when not using direct link)
- [ ] Performance (it's good but could be better)

## Queue system (/back doesn't work)
This is my idea for the queue management. I just can't get it working as intended. My assumption is that I'm not storing the history correctly,
but with the new system below I might be able to do that. I just haven't tried it yet and will do as soon as possible.

### Approach Using Explicit Queue Management
Instead of relying solely on played_songs, we can maintain a dedicated queue for both playing and played songs. This approach ensures clear management of song playback and history.

### Queue Management:
- Use two lists: queue for upcoming songs and played_songs for history.
- When a song finishes playing, move it from queue to played_songs.

### Back Command Logic:
- When /back is invoked, move the current playing song back to queue.
- Retrieve the last played song from played_songs and move it to queue for playback.

Here’s how you could modify your bot to implement this approach:

### Explanation:
#### Queue Management:
- queue: Holds upcoming songs to be played.
- played_songs: Stores songs that have been played.

#### Back Command:
- When /back is called, it stops the current playback if any.
- Moves the current playing song back to queue.
- Retrieves the last played song from played_songs and plays it.

## Issues / Suggestions
[Here](https://github.com/CoomInPickle/cucumber/issues "cucumber/issues")

## Contributions

Feel free to contribute to Cucumber, because IDK how much I can do or will do.  
I'm always open to collaboration or help.

## License

This project is licensed under the MIT License.
