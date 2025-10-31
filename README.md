# mykola-assistant
Python bot manager with various services to automate GTA Multiplayer gameplay

The server, acting as a 24/7 assistant, manages bots and offers various services to automate SA:MP gameplay for a community. It provides interfaces, assistant services, and in-game SA:MP bots powered by the RakNet network engine. It was deployed on AWS EC2.

http://18.159.52.87:5000/

## Components
- Monitor - monitors, controls, and logs RakSAMP bots implemented through [lua scripts](https://github.com/44sides/lua-collection-samp/tree/main/RakSAMP).
- Scheduler - schedules RakSAMP bots, notifications, and other jobs.
- Database - stores user profiles with their bot settings.
- REST API - server API to update users' bots states through client [lua scripts](https://github.com/44sides/lua-collection-samp/blob/main/SAMP/moonloader/lavka_notification.lua).
- NordVPN integration - starts users' RakSAMP bots under a chosen IP in an isolated netns.
- Telegram assistant - [free Telegram bot](https://github.com/44sides/free-group-telegram-bot), Telegram reminder-caller, and interface with the server.

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
