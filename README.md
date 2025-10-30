# mykola-helper
Python helper server with various features to make GTA Multiplayer gaming easier

The server serves as a 24/7 helper with a set of features to simplify the SA:MP gaming for the community. It provides services, interfaces, and in-game RakNet SA:MP bots. It was deployed on AWS EC2.

http://18.159.52.87:5000/

## Features
- Monitor - monitors, controls, and logs RakSAMP bots implemented through [lua scripts](https://github.com/44sides/lua-collection-samp/tree/main/RakSAMP).
- Scheduler - schedules RakSAMP bots, notifications, and other jobs.
- Database - stores user profiles with their settings.
- Telegram assistant - [free Telegram bot](https://github.com/44sides/free-group-telegram-bot), Telegram caller and interface with the server.
- REST API - server API to update states of users using [lua scripts](https://github.com/44sides/lua-collection-samp/blob/main/SAMP/moonloader/lavka_notification.lua).
- NordVPN - starts users' RakSAMP bots under a chosen IP in an isolated netns.

## Technologies/libraries 
Schedule, SQLite, Flask, Flasgger, Linux netns, WireGuard, Python-telegram-bot, GPT4Free, Telethon, PyTgCalls, Bbl, RakSAMP Lite

## Dependencies
- Ubuntu 22.04
- RakSAMP Lite 04.02.23
- Wine32
```bash
sudo dpkg --add-architecture i386
sudo apt install wine32
```
- Python
```bash
pip install psutil
pip install schedule
pip install requests
pip install pydash
pip install python-telegram-bot
pip install "python-telegram-bot[ext]"
pip install -U g4f[all]
pip install telethon
pip install py-tgcalls
pip install flask
pip install flask-restful
pip install flasgger
sudo apt install ffmpeg
sudo apt install wireguard
sudo apt install ./bbl_1.4-1_amd64.deb -y && mkdir -p ~/.bbl && echo '{ "translation": "ubio", "randomlyShow": "verse" }' > ~/.bbl/config.json
```

## Useful commands
`nohup python3 mykola_controller.py > mykola_controller.log 2>&1 &` - run the server. <br />
`wine RakSAMP\ Lite/RakSAMP\ Lite.exe -n Nick_Name` - run RakSAMP with nickname. <br />
`nohup wine RakSAMP\ Lite/RakSAMP\ Lite.exe -n Nick_Name &` - run RakSAMP with nickname in background. <br />
