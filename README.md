# Cucumber Bot 🥒

![Python](https://img.shields.io/badge/language-Python-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Last Commit](https://img.shields.io/github/last-commit/CoomInPickle/cucumber)
![Issues](https://img.shields.io/github/issues/CoomInPickle/cucumber)
## Overview

Cucumber is a personal Discord bot wich i want to use for all kind of things like music since there is no good one wich is reliable.
Also im gonna use it for other helpful stuff but il decide on that later
## To-Do List

- [x] Add music playback feature
- [ ] ~~Create dynamic /help command~~ (help is already in the discord /menu)
- [ ] /queue command to list quque or clear and maybe more
- [ ] Docker compose deployable
- [ ] !update command wich will make the but pull new files from github
- [ ] Adjustable music quality trought .env
- [ ] function to make a dedicated "console chat" for the bot either trough dm from only x user or only in the server x channel y.
      This can maybe include logging but mainly certain commands like !sync and maybe stuff that changes perrmanently to the .env
      mainly because idk how to do permission roles riight now. if i do its gonna be like /gamerula in minecraft lol
- [x] Make Embeds always same lenght and meybe height, also change color to cucumber color
- [ ] Stop Stuttering when bot is searching song whiles playing
- [ ] Performance (its good but could be better as always)

## Queue system (wip / notes / not working rn)
this is the my idea for the queue management. i just cannt get it working as intended. my assumption is that im not storing the history correctly,
but with the nnew system below i might be able to do that, i just havent tried it yet and will do as soon as possibe
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

Feel free to contribute to cucumber, cause idk how much i can do or will do.
I'm always open to collaboration or help.

## License

This project is licensed under the MIT License.



