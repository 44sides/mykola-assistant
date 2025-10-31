import subprocess
import time
import datetime
import os
import threading
import requests
import ipaddress
import traceback
import schedule
import psutil
import configparser
import json
import re
import g4f
import asyncio
import random
import hashlib
import sqlite3
from asyncio import run_coroutine_threadsafe
from g4f.client import Client
from pydash import get
from types import SimpleNamespace
from typing import TextIO, Optional
from zoneinfo import ZoneInfo
from telegram import Update, ChatPermissions, ChatMemberAdministrator, ChatMemberRestricted, ReactionTypeEmoji, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ChatMemberHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask, request, redirect
from flasgger import Swagger
from telethon import TelegramClient
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from pytgcalls import idle

bot_token, api_id, api_hash = "MY_TOKEN", 0, 'MY_API_HASH'
bot_username, me = "@MyBotUsername", 0
log_ids, admin_ids = [me], [me]
chat_id_name, thread_id_contracts, thread_id_raffle = 0, 0, 0
chat_id_admins = 0

conn = sqlite3.connect("my_database.db")
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON")
cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, token TEXT, vpn_hostname TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS accounts (nick TEXT PRIMARY KEY, password TEXT, "
               "lavka_sec INTEGER NOT NULL, hours TEXT NOT NULL, chat_id INTEGER NOT NULL, "
               "hours_call TEXT, call_id INTEGER, hours_raksamp TEXT, "
               "user_id INTEGER NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE, "
               "CHECK((hours_call IS NULL AND call_id IS NULL) OR (hours_call IS NOT NULL AND call_id IS NOT NULL)))")

app_flask = Flask(__name__)
swagger = Swagger(app_flask)
config = configparser.ConfigParser()
config.optionxform = str
event_loop = asyncio.get_event_loop()
log_file: Optional[TextIO] = None
call_py = None

app_path, app_name, log_path, transfer_path, group_path, raffle_path, verified_path = "RakSAMP Lite/RakSAMP Lite.exe", 'RakSAMP Lite.exe', "RakSAMP Lite/RakSAMP Lite.log", \
    "RakSAMP Lite/scripts/config/transfer_helper.ini", "config/group_stats.ini", "config/raffle_stats.ini", "config/verified_list.ini"

config.read(transfer_path)

JOB_CONFIGS = {
    "medic": {
        "nicks": ["Nick_Name", "Nick_Name"], # [medic_nick, client_nick]
        "schedule": "02:15",
        "timeout": 5
    },
    "instructor": {
        "nicks": ["Nick_Name", "Nick_Name"], # [instructor_nick, student_nick]
        "schedule": "02:10",
        "timeout": 6
    },
    "robber": {
        "nicks": ["Nick_Name", "Nick_Name", "Nick_Name"], # [one, two, three]
        "schedule": "09:54",
        "timeout": 7
    },
    "croupier": {
        "nicks": ["Nick_Name", "Nick_Name"], # [dragons_nick, caligula_nick]
        "schedule": "10:05",
        "timeout": 20
    },
    "grib": {
        "nicks": ['Nick_Name'] * 30,
        "schedule": "11:00",
        "timeout": 3
    },
    "lspd": {
        "nick": "Nick_Name",
        "schedule": "02:09:00",
        "timeout": 5
    },
    "sfpd": {
        "nick": "Nick_Name",
        "schedule": "02:11:00",
        "timeout": 5
    },
    "lvpd": {
        "nick": "Nick_Name",
        "schedule": "02:13:00",
        "timeout": 5
    },
    "transfer": {
        "nick": "Nick_Name",
        "timeout": 6,
        "limit": int(config.get('main', 'limit', fallback=0))
    },
    "lavka": {
        "timeout": 4
    }
}

JOB_STATE = {
    "medic": {"counter": 0, "reward": 0},
    "robber": {"counter": 0, "reward": 0},
    "grib": {"index": 0, "counter": 0, "pickups": 0, "reward": 0},
    "lspd": {"counter": 0, "tries": 0},
    "sfpd": {"counter": 0, "tries": 0},
    "lvpd": {"counter": 0, "tries": 0},
    "transfer": {"counter": 0, "reason": None, "last_message": None}
}

restart_time = "02:00"
current_date = datetime.date.today()
current_casino = 0
contract_status = {'medic_contract': '', 'instructor_contract': '', 'robber_contract': '', 'croupier_contract': ''}

lavka_jobs = {}

oko_list, oko_decrement = '', 25

restricted_users = {}

@app_flask.route('/')
def root():
    return redirect('/apidocs/')

@app_flask.route('/send_message', methods=['POST'])
def send_message_handler():
    """
    Sends a TG private message via the bot.
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            message:
              type: string
              example: "Hello!"
            recipient:
              type: integer
              example: 123456789
    responses:
      200:
        description: Successfully.
    """
    send_telegram_message(request.json['message'], request.json['recipient'])
    return {"status": "successfully"}, 200

@app_flask.route('/send_stall_message', methods=['POST'])
def send_lavka_message_handler():
    """
    Sends a TG private message to a registered user.
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            message:
              type: string
              example: "Hello!"
            nick:
              type: string
              example: Nick_Name
            token:
              type: string
              example: 29ad5ac62e70c7205136693b03ed25ag
    responses:
      200:
        description: Successfully.
      401:
        description: Invalid token.
      404:
        description: Not found.
    """
    account = run_coroutine_threadsafe(select_account(request.json['nick']), event_loop)
    token = run_coroutine_threadsafe(select_token(request.json['nick']), event_loop)
    if not account.result():
        return {"status": "not found"}, 404
    if token.result()[0] != request.json['token']:
        return {"status": "invalid token"}, 401

    send_telegram_message(request.json['message'], account.result()[4])
    return {"status": "successfully"}, 200

@app_flask.route('/renew_stall', methods=['POST'])
def renew_lavka_handler():
    """
    Retrieves user's profile data from the database and starts a TG reminder cycle with auto-renewal.
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            nick:
              type: string
              example: Nick_Name
            token:
              type: string
              example: 29ad5ac62e70c7205136693b03ed25ag
            renewed_ts:
              type: integer
              example: 1761485503
    responses:
      200:
        description: Successfully.
      401:
        description: Invalid token.
      404:
        description: Not found.
    """
    account = run_coroutine_threadsafe(select_account(request.json['nick']), event_loop)
    token = run_coroutine_threadsafe(select_token(request.json['nick']), event_loop)
    if not account.result():
        return {"status": "not found"}, 404
    if token.result()[0] != request.json['token']:
        return {"status": "invalid token"}, 401
    
    sec, hours, chat_id, hours_call, call_id, hours_raksamp = \
        account.result()[2], json.loads(account.result()[3]) if account.result()[3] else None, account.result()[4], \
        json.loads(account.result()[5]) if account.result()[5] else None, account.result()[6], json.loads(account.result()[7]) if account.result()[7] else None
    renew_lavka(request.json['nick'], request.json['renewed_ts'] + sec, hours, chat_id, hours_call, call_id, hours_raksamp)
    return {"status": "successfully"}, 200

def renew_lavka(nick, renewed_ts, hours, chat_id, hours_call, call_id, hours_raksamp):
    notify_it = iter([(time, h) for h in hours if (time := renewed_ts - h * 3600) > datetime.datetime.now().timestamp()])
    if lavka_jobs.get(nick) is not None:
        schedule.cancel_job(lavka_jobs[nick]['notify'])
        schedule.cancel_job(lavka_jobs[nick]['helper'])
    lavka_jobs[nick] = {'notify': None, 'helper': None}
    ts, left_h = next(notify_it) # StopIteration
    lavka_jobs[nick]['notify'] = schedule.every().day.at(datetime.datetime.utcfromtimestamp(ts).strftime("%H:%M:%S")).do(notify_lavka, nick, left_h, hours, chat_id, hours_call, call_id, hours_raksamp, notify_it)

def notify_lavka(nick, left_h, hours, chat_id, hours_call, call_id, hours_raksamp, notify_it):
    send_telegram_message(f"🔥  The stall will expire in {left_h} hours! ({nick})", chat_id)

    if isinstance(hours_call, list) and left_h in hours_call:
        send_telegram_message(f"call to {call_id} ({nick})")
        run_coroutine_threadsafe(call_py.play(call_id, MediaStream('lavka.mp3', video_flags=MediaStream.Flags.IGNORE)), event_loop)

    if isinstance(hours_raksamp, list) and left_h in hours_raksamp:
        lavka_timeout = JOB_CONFIGS["lavka"]["timeout"]
        if left_h == 0:
            lavka_helper(nick, lavka_timeout, True)
        else:
            time_now = datetime.datetime.now()
            time_now_kyiv = time_now + datetime.timedelta(hours=get_utc_offset("Europe/Kyiv"))
            minute_max = 60 - lavka_timeout - 2
            if time_now_kyiv.hour == 4:
                minute_until_max = minute_max - time_now.minute
                if minute_until_max >= 1:
                    lavka_jobs[nick]['helper'] = schedule.every().day.at((time_now + datetime.timedelta(minutes=random.randint(1, minute_until_max), seconds=random.randint(0, 59))).strftime("%H:%M:%S")).do(lavka_helper, nick, lavka_timeout, True)
                else:
                    lavka_helper(nick, lavka_timeout, True)
            elif time_now_kyiv.hour == 5 and time_now_kyiv.minute < 10:
                lavka_jobs[nick]['helper'] = schedule.every().day.at((time_now + datetime.timedelta(minutes=random.randint(10, minute_max), seconds=random.randint(0, 59))).strftime("%H:%M:%S")).do(lavka_helper, nick, lavka_timeout, True)
            else:
                lavka_jobs[nick]['helper'] = schedule.every().day.at((time_now + datetime.timedelta(minutes=random.randint(1, minute_max), seconds=random.randint(0, 59))).strftime("%H:%M:%S")).do(lavka_helper, nick, lavka_timeout, True)

    try:
        schedule.cancel_job(lavka_jobs[nick]['notify'])
        ts, left_h = next(notify_it)
        lavka_jobs[nick]['notify'] = schedule.every().day.at(datetime.datetime.utcfromtimestamp(ts).strftime("%H:%M:%S")).do(notify_lavka, nick, left_h, hours, chat_id, hours_call, call_id, hours_raksamp, notify_it)
    except StopIteration:
        return

def holy_bible(*args):
    return subprocess.run(["bbl", "rand"] + list(args), capture_output=True, text=True)

def send_telegram_message(message, recipients=log_ids, thread_id=None, parse_mode=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    if not isinstance(recipients, list):
        recipients = [recipients]
    for recipient in recipients:
        payload = {
            "chat_id": recipient,
            "text": message,
        }
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            response = requests.post(url, data=payload)
            response.raise_for_status()
        except Exception as e:
            print(f"Failed to send message to {recipient} ({thread_id}): {e}")

def edit_telegram_message(new_text, chat_id, message_id, parse_mode=None):
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except Exception as e:
        send_telegram_message(f"Failed to edit message {message_id} in chat {chat_id}")

def delete_telegram_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{bot_token}/deleteMessage"
    params = {
        "chat_id": chat_id,
        "message_id": message_id
    }
    try:
        response = requests.post(url, params=params)
        response.raise_for_status()
    except Exception as e:
        send_telegram_message(f"Failed to delete message {message_id} in chat {chat_id}: {e}")

def top_update_telegram_message():
    config.clear()
    config.read(group_path)

    message = ''
    sorted_items = sorted(config['earned'].items(), key=lambda x: int(x[1]), reverse=True)

    for nick, value in sorted_items:
        formatted_value = f"{int(value):,}".replace(',', '.')
        message += f"<code>{nick:<24}</code>:   <b>{formatted_value}$</b>\n"

    edit_telegram_message(message, chat_id_name, 474, parse_mode='HTML')

async def add_verified_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text('/add_verified <id>')
        return

    config.clear()
    config.read(verified_path)

    verified_list = json.loads(config['main']['list'])
    new_id = int(context.args[0])

    if new_id not in verified_list:
        verified_list.append(new_id)
        config['main']['list'] = json.dumps(verified_list)
        with open(verified_path, 'w') as configfile: config.write(configfile, space_around_delimiters=False)
        await update.message.reply_text(f"User verified: {new_id}")
    else:
        await update.message.reply_text('User is already verified')

async def remove_verified_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text('/remove_verified <id>')
        return

    config.clear()
    config.read(verified_path)

    verified_list = json.loads(config['main']['list'])
    old_id = int(context.args[0])

    if old_id in verified_list:
        verified_list.remove(old_id)
        config['main']['list'] = json.dumps(verified_list)
        with open(verified_path, 'w') as configfile: config.write(configfile, space_around_delimiters=False)
        await update.message.reply_text(f"User verification removed: {old_id}")
    else:
        await update.message.reply_text('User is not verified')

async def raffle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) < 3 or not context.args[0].replace('.','',1).isdigit():
            await update.message.reply_text("/lot <points> <nick> <comment>")
            return

        elif update.message.chat.id != chat_id_name:
            return

        chat_id = update.message.chat.id
        message_id = update.message.message_id

        config.clear()
        config.read(raffle_path)

        value = float(config['tickets'].get(context.args[1], 0))
        config['tickets'][context.args[1]] = f"{value + float(context.args[0]):.3f}"

        with open(raffle_path, 'w') as configfile: config.write(configfile, space_around_delimiters=False)

        # await update.message.reply_text(f"⚡ {context.args[1]} credited: {context.args[0]} — {' '.join(context.args[2:])}")

        message = ''
        sorted_items = sorted(config['tickets'].items(), key=lambda x: float(x[1]), reverse=True)

        for nick, value in sorted_items:
            num = float(value)
            formatted_value = int(num) if num.is_integer() else num
            message += f"<code>{nick[:24]:<24}</code>:   <b>{formatted_value}</b>\n"

        edit_telegram_message(message, chat_id_name, 4442, parse_mode='HTML')

        await context.bot.set_message_reaction(chat_id=chat_id, message_id=message_id, reaction=[ReactionTypeEmoji(emoji="🏆")])

    except Exception as e:
        await update.message.reply_text(f"An error occurred while crediting: {e}")

async def welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Welcome to the group! 👋"
    )
    await update.message.reply_text(welcome_text)

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        return

    jobs = schedule.get_jobs()
    schedule_text = "Current schedule:\n"
    for job in jobs:
        job_arg = f"({job.job_func.args[0]})" if job.job_func.args else ''
        schedule_text += f"- {job.job_func.__name__}{job_arg}, {job.next_run}UTC\n"
    await update.message.reply_text(schedule_text)

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report_text = f"Contract status for {current_date}:\n"
    for contract, status in contract_status.items():
        report_text += f"- {contract}: {status}\n"
    await update.message.reply_text(report_text)

async def clear_log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        return

    if clear_log():
        await update.message.reply_text("Log file cleared")

async def remove_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        return

    if len(context.args) == 1:
        job_name, job_arg = context.args + [None]
    elif len(context.args) == 2:
        job_name, job_arg = context.args
        #time_parts = job_time_str.split(":")
        #job_time_str = f"{time_parts[0]}:{time_parts[1]}" if len(time_parts) == 3 else job_time_str
    else:
        await update.message.reply_text("Usage: /remove_schedule <job_name> [job_arg]")
        return

    try:
        remove_schedule(job_name, job_arg)
        await update.message.reply_text(f"Schedule for {job_name} removed")
    except Exception as e:
        error_message = f"Failed to remove schedule: {e}"
        send_telegram_message(error_message)

async def set_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        return

    try:
        args = context.args
        job_time_str = None
        if len(args) == 2:
            job_name, new_time = args
        elif len(args) == 3:
            job_name, job_time_str, new_time = args
            time_parts = job_time_str.split(":")
            job_time_str = f"{time_parts[0]}:{time_parts[1]}" if len(time_parts) == 3 else job_time_str
        else:
            await update.message.reply_text("Usage: /set_schedule <job_name> <new_timeUTC>")
            return

        time_parts = new_time.split(":")
        new_time = f"{time_parts[0]}:{time_parts[1]}" if len(time_parts) == 3 else new_time

        if job_name == 'robber_contract':
            hour, minute = int(new_time.split(':')[0]), int(new_time.split(':')[1])
            if (25 <= minute <= 29) or (55 <= minute <= 59) or (hour % 2 == 0 and 0 <= minute <= 29):
                await update.message.reply_text(f"This launch minute {minute} is restricted!")
                return

        #found = False
        #for job in schedule.get_jobs():
        #    if job.job_func.__name__ == job_name:
        #        found = True
        #if found:
        #    remove_schedule(job_name, job_time_str)

        set_schedule(job_name, new_time, False)

        await update.message.reply_text(f"Schedule for {job_name} set to {new_time} UTC")
    except Exception as e:
        error_message = f"Failed to set schedule: {e}"
        send_telegram_message(error_message)

async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config.clear()
    config.read(verified_path)
    verified_list = json.loads(config['main']['list'])

    if update.effective_user.id not in verified_list:
        await update.message.reply_text('Transfer is available to verified users')
        return
    
    transfer_limit = JOB_CONFIGS["transfer"]["limit"]

    if len(context.args) == 2 and context.args[0] == 'limit' and context.args[1].isdigit():
        config.clear()
        config.read(transfer_path)
        config['main']['limit'] = context.args[1]
        with open(transfer_path, 'w') as configfile: config.write(configfile, space_around_delimiters=False)
        JOB_CONFIGS["transfer"]["limit"] = int(config['main']['limit'])
        await update.message.reply_text(f"Limit: Daily limit has been changed to {config['main']['limit']}$")

    elif len(context.args) == 1 and context.args[0] == 'status':
        config.clear()
        config.read(transfer_path)
        transfer_cntr = JOB_STATE["transfer"]["counter"]
        await update.message.reply_text(f"Balance: {config['main']['balance']}$\nLimit: {transfer_cntr}/{config['main']['limit']}$")

    elif not os_controller_pschecker(JOB_CONFIGS["transfer"]["nick"]):
        if len(context.args) == 1 and context.args[0] == 'deposit':
            config.clear()
            config.read(transfer_path)
            config['main']['mode'] = '1'
            with open(transfer_path, 'w') as configfile: config.write(configfile, space_around_delimiters=False)
            
            transfer_nick = JOB_CONFIGS["transfer"]["nick"]
            transfer_timeout = JOB_CONFIGS["transfer"]["timeout"]
            transfer_helper(transfer_nick, transfer_timeout, True)
            
            JOB_STATE["transfer"]["last_message"] = await update.message.reply_text(f"Deposit: transfer the amount {transfer_nick} /transfer_exit")

        elif len(context.args) >= 3 and context.args[0].isdigit():
            transfer_cntr = JOB_STATE["transfer"]["counter"]
            transfer_limit = JOB_CONFIGS["transfer"]["limit"]
            
            if transfer_cntr + int(context.args[0]) <= transfer_limit:
                config.clear()
                config.read(transfer_path)
                config['main']['mode'] = '0'
                config['main']['sum'] = context.args[0]
                config['main']['nick'] = context.args[1]
                with open(transfer_path, 'w') as configfile: config.write(configfile, space_around_delimiters=False)
                
                JOB_STATE["transfer"]["reason"] = ' '.join(context.args[2:])
                
                transfer_nick = JOB_CONFIGS["transfer"]["nick"]
                transfer_timeout = JOB_CONFIGS["transfer"]["timeout"]
                transfer_helper(transfer_nick, transfer_timeout, True)
                
                transfer_reason = JOB_STATE["transfer"]["reason"]
                JOB_STATE["transfer"]["last_message"] = await update.message.reply_text(f"Transfer: {config['main']['sum']}$ will be transferred to {config['main']['nick']}. Reason: {transfer_reason} /transfer_exit")

            else:
                await update.message.reply_text(f"Limit of {transfer_limit}$ reached!")

        else:
            await update.message.reply_text("/transfer <amount> <nick> <reason>")
            # await update.message.reply_text("Usage: /transfer <sum> <nick> <reason> | /transfer deposit | /transfer status | /transfer exit")

    else:
        await update.message.reply_text("Cashier is already online!")

async def transfer_exit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transfer_nick = JOB_CONFIGS["transfer"]["nick"]
    transfer_last_message = JOB_STATE["transfer"]["last_message"]
    
    if os_controller_pschecker(transfer_nick):
        os_controller_psterminator(transfer_nick)
        await update.message.reply_text("Cashier has been stopped")
        delete_telegram_message(transfer_last_message.chat.id, transfer_last_message.message_id)

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2 or not context.args[0].isdigit():
        return

    chat_id = chat_id_name
    thread_id = context.args[0]

    try:
        sent_message = await context.bot.send_message(chat_id, ' '.join(context.args[1:]), message_thread_id=thread_id or None)
        await update.message.reply_text(f"Message ID: {sent_message.message_id}")
    except Exception as e:
        await update.message.reply_text(f"Error sending message: {e}")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 0:
        return

    if update.message.reply_to_message and not update.message.reply_to_message.forum_topic_created:
        response_text = f"User ID: {update.message.reply_to_message.from_user.id}\n"
    else:
        response_text = f"Chat ID: {update.effective_chat.id}\n"
        if update.message.message_thread_id: response_text += f"Thread ID: {update.message.message_thread_id}"

    await update.message.reply_text(response_text)

async def bbl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 0 and (len(context.args) != 1 or context.args[0] not in ['ot', 'nt', 'g']):
        return

    result = holy_bible(*context.args)
    
    if result.returncode == 0:
        await update.message.reply_text(result.stdout)
    else:
        await update.message.reply_text(f"An error occurred: {result.stderr}")

async def photo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 0:
        return

    unsplash_token = "SPLASH_TOKEN"
    url = f"https://api.unsplash.com/photos/random?client_id={unsplash_token}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        image_url = data.get('urls').get('regular')
        description = data.get('description') and data.get('description') + '\n' or ''
        caption = f"{description}{data.get('location').get('name')}. {data.get('created_at').split('T')[0]}"
        await update.message.reply_photo(photo=image_url, caption=caption)
    except Exception as e:
        await update.message.reply_text(f"An image error occurred: {e}")

async def members_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 0:
        return

    elif update.message.chat.type != 'private':
        return

    config.clear()
    config.read(verified_path)

    verified_list = json.loads(config['main']['list'])
    chat_id = chat_id_name
    admins = await context.bot.get_chat_administrators(chat_id)

    result = ""

    for admin in admins:
        user = admin.user
        verified = "✅ " if user.id in verified_list else ""
        username = f"@{user.username} " if user.username else ""
        title = f"({admin.custom_title})" if admin.custom_title else ""
        result += f"{verified}ID: {user.id} — {user.full_name} {username}{title}\n"

    await update.message.reply_text(result)

async def unnick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (len(context.args) != 0 or not update.message.reply_to_message) and len(context.args) != 1:
        return

    elif get(update.message, 'reply_to_message.forum_topic_created') and len(context.args) == 0:
        return

    if len(context.args) == 0:
        chat_id = update.effective_chat.id
        user = update.message.reply_to_message and update.message.reply_to_message.from_user
        status, title = False, None
        for admin in (await context.bot.get_chat_administrators(chat_id)):
            if admin.user.id == user.id:
                status = True
                title = admin.custom_title
        if not status:
            await update.message.reply_text(f'User <a href="tg://user?id={user.id}">{user.first_name}</a> not found!', parse_mode='HTML')
            return

    elif len(context.args) == 1:
        nickname = context.args[0]
        chat_id = update.message.chat.type == 'private' and chat_id_name or update.effective_chat.id
        user, title = None, None
        for admin in (await context.bot.get_chat_administrators(chat_id)):
            if admin.custom_title == nickname:
                user = admin.user
                title = admin.custom_title
        if not user:
            await update.message.reply_text(f"User {nickname} not found!")
            return

    try:
        await context.bot.promote_chat_member(chat_id=chat_id, user_id=user.id)
        await update.message.reply_text(f'Nickname removed for user <a href="tg://user?id={user.id}">{user.first_name}</a>: {title}', parse_mode='HTML')
        send_telegram_message(f'Nickname removed for user {user.first_name}: {title} ({update.effective_user.first_name})')
    except Exception as e:
        await update.message.reply_text(f"An error occurred while removing the nickname: {e}")

async def nick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1 or not update.message.reply_to_message and not update.message.external_reply:
        return

    elif get(update.message, 'reply_to_message.forum_topic_created') and len(context.args) == 0:
        return

    elif get(update.message, 'external_reply.origin.type') == 'hidden_user':
        await update.message.reply_text(f"User profile is hidden")
        return

    chat_id = update.message.external_reply and update.message.external_reply.chat.id or update.effective_chat.id
    user = get(update.message, 'reply_to_message.api_kwargs.new_chat_member') or get(update.message, 'reply_to_message.from_user') or get(update.message, 'external_reply.origin.sender_user')
    user = SimpleNamespace(**user) if isinstance(user, dict) else user
    chat_member = await context.bot.get_chat_member(chat_id, user.id)

    try:
        if not isinstance(chat_member, ChatMemberAdministrator):
            await context.bot.promote_chat_member(chat_id=chat_id, user_id=user.id, can_post_stories=True)
        await context.bot.set_chat_administrator_custom_title(chat_id=chat_id, user_id=user.id, custom_title=context.args[0])
        await context.bot.send_message(update.effective_chat.id, f'User <a href="tg://user?id={user.id}">{user.first_name}</a> has been assigned the nickname: {context.args[0]}',
                                       message_thread_id=update.message.is_topic_message and update.message.message_thread_id, parse_mode='HTML')
        if update.message.chat.type in ['supergroup', 'group']:
            await context.bot.delete_message(update.effective_chat.id, update.message.message_id)
        send_telegram_message(f'User {user.first_name} has been assigned the nickname: {context.args[0]} ({update.effective_user.first_name})')
    except Exception as e:
        await update.message.reply_text(f"An error occurred while assigning the nickname: {e}")

def update_unmuted(user):
    del restricted_users[user.id]
    send_telegram_message(f'User <a href="tg://user?id={user.id}">{user.first_name}</a> has been unmuted', parse_mode='HTML')
    return schedule.CancelJob

def restore_admin_rights(user, chat_id, admin_rights, admin_title):
    del restricted_users[user.id]

    promote_url = f"https://api.telegram.org/bot{bot_token}/promoteChatMember"
    title_url = f"https://api.telegram.org/bot{bot_token}/setChatAdministratorCustomTitle"

    promote_payload = {"chat_id": chat_id, "user_id": user.id, **admin_rights}
    title_payload = {"chat_id": chat_id, "user_id": user.id, "custom_title": admin_title}

    try:
        promote_response = requests.post(promote_url, data=promote_payload)
        promote_response.raise_for_status()
        title_response = requests.post(title_url, data=title_payload)
        title_response.raise_for_status()
    except Exception as e:
        send_telegram_message(f"An error occurred while restoring the user: {e}")

    send_telegram_message(f'User <a href="tg://user?id={user.id}">{user.first_name}</a> has been unmuted', parse_mode='HTML')
    return schedule.CancelJob

async def un_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.message.text.replace('/un_', '').replace(f"{bot_username}", ''))

    if not restricted_users.get(user_id):
        return

    restore_job = restricted_users[user_id]['restore_job']
    restore_job.run()
    schedule.cancel_job(restore_job)

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        if not restricted_users:
            await update.message.reply_text("The list of restricted users is empty")
            return

        message = ''
        for user_id, data in restricted_users.items():
            user_link = f'<a href="tg://user?id={data["user"].id}">{data["user"].first_name}</a>'
            until_date = data['until_date'].strftime("%m-%d %H:%M:%S")
            unmute_command = f"/un_{data['user'].id}"
            message += f"User: {user_link}, Restoration: {until_date} {unmute_command}\n"

        await update.message.reply_text(message, parse_mode='HTML')
        return

    elif not len(context.args) == 1 or not context.args[0].isdigit() or not update.message.reply_to_message:
        return

    # elif update.effective_user.id not in admin_ids:
    #     return
    
    duration_minutes = int(1) # context.args[0]

    chat_id = update.effective_chat.id
    user = update.message.reply_to_message.from_user

    if restricted_users.get(user.id):
        await update.message.reply_text(f"User {user.first_name} is already muted! /mute")
        return

    chat_member = await context.bot.get_chat_member(chat_id, user.id)

    until_date = datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)

    if isinstance(chat_member, ChatMemberAdministrator):
        admin_rights = {
            attr: getattr(chat_member, attr, None)
            for attr in ['can_change_info', 'can_delete_messages', 'can_delete_stories', 'can_edit_stories', 'can_invite_users',
                         'can_manage_chat', 'can_manage_topics', 'can_manage_video_chats', 'can_pin_messages','can_post_stories',
                         'can_promote_members', 'can_restrict_members', 'is_anonymous']
        }
        admit_title = chat_member.custom_title
        restore_job = schedule.every(duration_minutes).minutes.do(restore_admin_rights, user, chat_id, admin_rights, admit_title)
    else:
        restore_job = schedule.every(duration_minutes).minutes.do(update_unmuted, user)

    restricted_users[user.id] = {'until_date': until_date, 'user': user, 'confirmed': False, 'restore_job': restore_job}

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            until_date=until_date,
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text(f"User {user.first_name} has been muted for {duration_minutes} minutes")
        send_telegram_message(f'User {user.first_name} has been muted for {duration_minutes} minutes ({update.effective_user.first_name})')
    except Exception as e:
        await update.message.reply_text(f"An error occurred while muting: {e}")

async def status_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != chat_id_name:
        return

    chat_id = update.effective_chat.id
    user = update.chat_member.new_chat_member.user
    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status

    if restricted_users.get(user.id):
        if not restricted_users[user.id]['confirmed']:
            restricted_users[user.id]['confirmed'] = True
        else:
            schedule.cancel_job(restricted_users[user.id]['restore_job'])
            del restricted_users[user.id]

    elif old_status in ['left', 'kicked'] and new_status == 'member':
        try:
            await context.bot.promote_chat_member(chat_id=chat_id, user_id=user.id, can_post_stories=True)
            await context.bot.set_chat_administrator_custom_title(chat_id=chat_id, user_id=user.id, custom_title="Unknown")
        except Exception as e:
            send_telegram_message(f"An error occurred while promoting the user: {e}")

    elif old_status not in ['left', 'kicked'] and new_status in ['left', 'kicked']:
        result = holy_bible()
        if result.returncode == 0:
            await context.bot.send_message(chat_id, result.stdout)
        # await context.bot.send_message(chat_id, f'User <a href="tg://user?id={user.id}">{user.first_name}</a> left the group', parse_mode='HTML')

async def select_account(nick):
    cursor.execute("SELECT * FROM accounts WHERE nick = ?", (nick,))
    account = cursor.fetchone()
    return account

async def select_token(nick):
    cursor.execute("SELECT token FROM users WHERE id = (SELECT user_id FROM accounts WHERE nick = ?)", (nick,))
    user_token = cursor.fetchone()
    return user_token

async def table_out_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1 or update.effective_user.id not in admin_ids:
        return

    cursor.execute(f"SELECT * FROM {context.args[0]}")
    rows = cursor.fetchall()

    table = ""
    for row in rows:
        if context.args[0] == 'accounts':
            password_formatted = row[1][:2] + '*' * (len(row[1]) - 2)
            table += str(row[:1] + (password_formatted,) + row[2:]) + "\n"
        else:
            table += str(row) + "\n"

    await update.message.reply_text(f"{context.args[0]}:\n{table}")

async def table_del_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2 or update.effective_user.id not in admin_ids:
        return

    first_col = cursor.execute(f"PRAGMA table_info({context.args[0]})").fetchone()[1]

    cursor.execute(f"DELETE FROM {context.args[0]} WHERE {first_col} = ?", (context.args[1],))
    conn.commit()

    if cursor.rowcount > 0:
        await update.message.reply_text(f"Deleted {context.args[1]} from {context.args[0]}")

async def md5_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return

    arg_hash = hashlib.md5((context.args[0]).encode('ascii')).hexdigest()
    await update.message.reply_text(f"MD5 hash: {arg_hash}")

async def signup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for i in range(len(context.args)):
        if context.args[i] == 'None':
            context.args[i] = None

    id = update.message.from_user.id

    user_signup_hash = hashlib.md5(f"{id}".encode('ascii')).hexdigest()

    if len(context.args) != 2 or context.args[0] != user_signup_hash:
        await update.message.reply_text('/signup <md5key> <vpn_hostname (<url> | None)>')
        return

    cursor.execute("SELECT 1 FROM users WHERE id = ?", (id,))
    user = cursor.fetchone()

    if user:
        await update.message.reply_text(f"Already registered: {id} ID")
        return

    vpn_hostname = context.args[1]
    token = hashlib.md5(f"{id}_token".encode('ascii')).hexdigest()

    if vpn_hostname not in ('localhost', None):
        try:
            # create netns
            subprocess.run(f"sudo WG_NAME=nord-{id} WG_COUNTRY_CODE={vpn_hostname[:2].upper()} WG_HOSTNAME={vpn_hostname} bash nord-netns/my-nordvpn-netns up".split(), check=True)
            # copy resolv.conf for netns
            subprocess.run(f"sudo mkdir -p /etc/netns/nord-{id}".split(), check=True)
            subprocess.run(f"sudo cp nord-netns/resolv.conf /etc/netns/nord-{id}/resolv.conf".split(), check=True)
            # init env for wine
            subprocess.run(f"sudo -u ubuntu env WINEPREFIX=/home/ubuntu/.wine-nord-{id} wineboot --init".split(), check=True)
        except Exception as e:
            send_telegram_message('here')
            subprocess.run(f"sudo WG_NAME=nord-{id} bash nord-netns/my-nordvpn-netns down".split(), check=True)

    cursor.execute('INSERT INTO users (id, token, vpn_hostname) VALUES (?, ?, ?)', (id, token, vpn_hostname))
    conn.commit()

    await update.message.reply_text(f"Registered under {vpn_hostname}. Token: {token}")

async def delete_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 0:
        return

    id = update.message.from_user.id

    cursor.execute("SELECT nick FROM accounts WHERE user_id = ?", (id,))
    accounts = cursor.fetchall()

    for account in accounts:
        if lavka_jobs.get(account[0]) is not None:
            schedule.cancel_job(lavka_jobs[account[0]]['notify'])
            schedule.cancel_job(lavka_jobs[account[0]]['helper'])
            del lavka_jobs[account[0]]

    subprocess.run(f"sudo -u ubuntu env WINEPREFIX=/home/ubuntu/.wine-nord-{id} wineserver -k".split())
    subprocess.run(f"sudo rm -rf .wine-nord-{id}".split(), check=True)
    subprocess.run(f"sudo rm -rf /etc/netns/nord-{id}".split(), check=True)
    subprocess.run(f"sudo WG_NAME=nord-{id} bash nord-netns/my-nordvpn-netns down".split(), check=True)

    cursor.execute('DELETE FROM users WHERE id = ?', (id,))
    conn.commit()

    await update.message.reply_text(f"Deleted: {id} ID")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 0:
        return

    # profile
    cursor.execute("SELECT id, vpn_hostname FROM users WHERE id = ?", (update.message.from_user.id,))
    user = cursor.fetchone()

    if not user:
        await update.message.reply_text(f"User not found")
        return

    table_profile = f"({user[0]}; {user[1]})"

    # accounts
    cursor.execute("SELECT nick, password, lavka_sec, hours, chat_id, hours_call, call_id, hours_raksamp FROM accounts WHERE user_id = ? ORDER BY rowid", (update.message.from_user.id,))
    accounts = cursor.fetchall()
    table_accounts = ""
    for i, account in enumerate(accounts, start=1):
        password_formatted = account[1][:2] + '*' * (len(account[1]) - 2)
        table_accounts += f"{i}. ({account[0]}; {password_formatted}; {account[2]}; {account[3]}; {account[4]}; {account[5]}; {account[6]}; {account[7]})\n"

    # schedule
    table_schedule = ""
    for account in accounts:
        jobs = [lavka_jobs.get(account[0], {}).get('notify'), lavka_jobs.get(account[0], {}).get('helper')]
        for job in jobs:
            if job in schedule.jobs:
                job_arg = f"({job.job_func.args[0]})" if job.job_func.args else ''
                table_schedule += f"- {job.job_func.__name__}{job_arg}, {job.next_run}UTC\n"

    await update.message.reply_text(f"My profile: {table_profile}\nMy accounts:\n{table_accounts}My schedule:\n{table_schedule}")

async def add_account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for i in range(len(context.args)):
        if context.args[i] == 'None':
            context.args[i] = None

    if len(context.args) != 8 or len(context.args[1]) < 6:
        await update.message.reply_text("/add_account <nick> <password> <lavka_sec> <hours:list> <chat_id> [hours_call:list] [call_id] [hours_raksamp:list]")
        return

    id = update.message.from_user.id

    cursor.execute("SELECT vpn_hostname FROM users WHERE id = ?", (id,))
    user = cursor.fetchone()

    if not user or user[0] is None and context.args[7]:
        await update.message.reply_text('RakSAMP is not available')
        return

    cursor.execute("SELECT 1 FROM accounts WHERE nick = ?", (context.args[0],))
    account = cursor.fetchone()

    if account:
        await update.message.reply_text(f"Already added: {context.args[0]}")
        return

    cursor.execute('INSERT INTO accounts (nick, password, lavka_sec, hours, chat_id, hours_call, call_id, hours_raksamp, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (context.args[0], context.args[1], context.args[2], context.args[3], context.args[4], context.args[5], context.args[6], context.args[7], id))
    conn.commit()

    password_formatted = context.args[1][:2] + '*' * (len(context.args[1]) - 2)

    await update.message.reply_text(f"Nick: {context.args[0]}\nPassword: {password_formatted}\n"
                                    f"Lavka_sec: {context.args[2]}\nHours: {context.args[3]} (Chat_id: {context.args[4]})\n"
                                    f"Hours_call: {context.args[5]} (Call_id: {context.args[6]})\nHours_raksamp: {context.args[7]}")

async def dliv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) not in [1, 2] or (not context.args[0].isdigit() or context.args[0] == '0') or \
            (len(context.args) == 2 and (not bool(re.compile(r'^[+-]?\d+$').fullmatch(context.args[1])) or int(context.args[1]) < -1 or int(context.args[1]) >= 60)):
        await update.message.reply_text("/dliv <num> [opt (<min> | -1)]")
        return

    cursor.execute("SELECT nick, password, lavka_sec, hours, chat_id, hours_call, call_id, hours_raksamp FROM accounts WHERE user_id = ? ORDER BY rowid LIMIT 1 OFFSET ?", (update.message.from_user.id, int(context.args[0]) - 1))
    account = cursor.fetchone()

    if not account:
        await update.message.reply_text(f"Account not found")
        return

    time_now = datetime.datetime.now()

    if len(context.args) == 1 or len(context.args) == 2 and context.args[1] == '-1':
        job = lavka_jobs.get(account[0], {}).get('notify')

        if job not in schedule.jobs:
            await update.message.reply_text(f"Schedule not found")
            return

        min, sec = job.next_run.minute, job.next_run.second

        overdue_time = job.next_run + datetime.timedelta(hours=job.job_func.args[1])
        time_left = overdue_time - time_now
        renewed_hours = 12 - ((time_left.days * 24 + time_left.seconds // 3600) + 1)
        renewed_price = 650 * renewed_hours
    else:
        min, sec = int(context.args[1]), account[2]
        renewed_hours = 12
        renewed_price = 0

    is_hour_counted = (time_now.minute * 60 + time_now.second) >= min * 60 + sec
    renewed_time = (time_now + datetime.timedelta(hours=is_hour_counted and 12 or 11)).replace(minute=min, second=sec)

    if len(context.args) == 2 and context.args[1] == '-1':
        renewed_hours = renewed_hours - 1
        renewed_price = renewed_price - 650
        renewed_time = renewed_time - datetime.timedelta(hours=1)

    renew_lavka(account[0], int(renewed_time.timestamp()), json.loads(account[3]) if account[3] else None, account[4],
                json.loads(account[5]) if account[5] else None, account[6], json.loads(account[7]) if account[7] else None)

    formatted_time = (renewed_time + datetime.timedelta(hours=get_utc_offset("Europe/Kyiv"))).strftime('%Y-%m-%d %H:%M:%S')
    await update.message.reply_text(f"🏷️  You have renewed the stall lease for {renewed_hours} h. for {renewed_price}$ until {formatted_time} ({account[0]})")

async def launch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1 or not context.args[0].isdigit() or context.args[0] == '0':
        return

    id = update.message.from_user.id

    cursor.execute("SELECT vpn_hostname FROM users WHERE id = ?", (id,))
    user = cursor.fetchone()

    if not user or user[0] is None:
        await update.message.reply_text('RakSAMP is not available')
        return

    cursor.execute("SELECT nick FROM accounts WHERE user_id = ? ORDER BY rowid LIMIT 1 OFFSET ?", (update.message.from_user.id, int(context.args[0]) - 1))
    account = cursor.fetchone()

    if not account:
        await update.message.reply_text(f"Account not found")
        return
    
    lavka_helper(account[0], JOB_CONFIGS["lavka"]["timeout"], True)

    await update.message.reply_text(f"{account[0]} is launching...")

client = Client()
messages = [{"role": "system", "content": "Answer questions in English."}]

def gpt_query(prompt, user):
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model='gpt-4o-mini', # g4f.models.default
        provider=g4f.Provider.PollinationsAI,
        messages=messages
    )

    string = ''
    for key, value in response.__dict__.items():
        if key in ['model', 'provider']:
            string += f"{key}: {value}\n"
    string += f"user: {user.first_name}{f', @{user.username}' if user.username else ''}"
    send_telegram_message(string)

    gpt_response = response.choices[0].message.content
    messages.append({"role": "assistant", "content": gpt_response})

    return gpt_response

async def handle_message_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message:
        return

    user = update.message.from_user

    message_type = update.message.chat.type
    text = update.message.text
    if message_type == 'supergroup' or message_type == 'group':
        if any(word in text for word in [bot_username, 'Mykolaj']) or bot_username[1:] == get(update.message, 'reply_to_message.from_user.username'):
            pure_text = text.replace(bot_username, '').strip()
            response = gpt_query(pure_text, user)
        else:
            return
    else:
        response = gpt_query(text, user)

    await update.message.reply_text(response)

async def error_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update:
        send_telegram_message(f"{update}\ncaused error: {context.error}")
        if update.message:
            await update.message.reply_text('An unknown error occurred')

def start_flask_server():
    app_flask.run(host='0.0.0.0')

async def start_pytgcalls():
    global call_py

    app = TelegramClient('py-tgcalls', api_id=api_id, api_hash=api_hash)
    call_py = PyTgCalls(app)
    await call_py.start()
    await idle()

def start_telegram_bot():
    app = Application.builder().token(bot_token).build()

    # Raksamp
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("clear_log", clear_log_command))
    app.add_handler(CommandHandler("remove_schedule", remove_schedule_command))
    app.add_handler(CommandHandler("set_schedule", set_schedule_command))

    # transfer_helper
    app.add_handler(CommandHandler("transfer", transfer_command))
    app.add_handler(MessageHandler(filters.Regex(fr"^/transfer_exit(?:{bot_username})?$"), transfer_exit_command))
    
    # Chat
    app.add_handler(CommandHandler("welcome", welcome_command))
    app.add_handler(CommandHandler("send", send_command))
    app.add_handler(CommandHandler("lot", raffle_command))
    app.add_handler(CommandHandler("bbl", bbl_command))
    app.add_handler(CommandHandler("photo", photo_command))

    # Profile for lavka
    app.add_handler(CommandHandler("md5", md5_command))
    app.add_handler(CommandHandler("signup", signup_command))
    app.add_handler(CommandHandler("delete_profile", delete_profile_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("add_account", add_account_command))
    app.add_handler(CommandHandler("dliv", dliv_command))
    app.add_handler(CommandHandler("launch", launch_command))

    # Management
    app.add_handler(CommandHandler("add_verified", add_verified_command))
    app.add_handler(CommandHandler("remove_verified", remove_verified_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("members", members_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unnick", unnick_command))
    app.add_handler(CommandHandler("nick", nick_command))
    app.add_handler(MessageHandler(filters.Regex(fr"^/un_(\d+)(?:{bot_username})?$"), un_command))
    app.add_handler(ChatMemberHandler(status_event, ChatMemberHandler.CHAT_MEMBER))
    # database
    app.add_handler(CommandHandler("table_out", table_out_command))
    app.add_handler(CommandHandler("table_del", table_del_command))

    # ChatGPT
    app.add_handler(MessageHandler(filters.TEXT, handle_message_bot))

    app.add_error_handler(error_bot)

    app.run_polling(poll_interval=5.0, timeout=10.0, allowed_updates=Update.ALL_TYPES)

def update_date():
    global current_date, current_casino, oko_list, oko_decrement
    
    JOB_STATE["transfer"]["counter"] = 0
    current_date = datetime.date.today()
    current_casino = (current_casino + 1) % 2
    oko_list, oko_decrement = '', 25
    send_telegram_message('Day has been updated')

def remove_schedule(job_name, job_arg=None):
    if job_name == 'grib_contract':
        JOB_STATE["grib"]["index"] = 0
        JOB_STATE["grib"]["counter"] = 0

    found = False
    for job in schedule.get_jobs():
        found_flag, break_flag = False, False
        if job_name == job.job_func.__name__:
            if job_arg is None:
                found_flag = True
            elif job.job_func.args and job_arg == job.job_func.args[0]:
                found_flag, break_flag = True, True

            if found_flag:
                found = True
                schedule.cancel_job(job)
                if break_flag:
                    break

    if not found:
        raise ValueError(f"Job {job_name} not found")

def set_schedule(job_name, job_time_str, once):
    if job_name == "medic_contract":
        schedule.every().day.at(job_time_str).do(medic_contract, JOB_CONFIGS["medic"]["nicks"][0], JOB_CONFIGS["medic"]["timeout"], once)
    elif job_name == "instructor_contract":
        schedule.every().day.at(job_time_str).do(instructor_contract, JOB_CONFIGS["instructor"]["nicks"][0], JOB_CONFIGS["instructor"]["timeout"], once)
    elif job_name == "robber_contract":
        hour, minute = int(job_time_str.split(':')[0]), int(job_time_str.split(':')[1])
        if (25 <= minute <= 29) or (55 <= minute <= 59) or (hour % 2 == 0 and 0 <= minute <= 29):
            raise ValueError(f"This launch minute {minute} is restricted!")
        schedule.every().day.at(job_time_str).do(robber_contract, JOB_CONFIGS["robber"]["nicks"][2], JOB_CONFIGS["robber"]["timeout"], once)
    elif job_name == "croupier_contract":
        if current_casino == 0:
            schedule.every().day.at(job_time_str).do(croupier_contract, JOB_CONFIGS["croupier"]["nicks"][0], JOB_CONFIGS["croupier"]["timeout"], once)
        else:
            schedule.every().day.at(job_time_str).do(croupier_contract, JOB_CONFIGS["croupier"]["nicks"][1], JOB_CONFIGS["croupier"]["timeout"], once)
    elif job_name == "grib_contract":
        schedule.every().day.at(job_time_str).do(grib_contract, JOB_CONFIGS["grib"]["nicks"][JOB_STATE["grib"]["index"]], JOB_CONFIGS["grib"]["timeout"], once)
    elif job_name == "lspd_helper":
        schedule.every().day.at(job_time_str).do(lspd_helper, JOB_CONFIGS["lspd"]["nick"], JOB_CONFIGS["lspd"]["timeout"], once)
    elif job_name == "sfpd_helper":
        schedule.every().day.at(job_time_str).do(sfpd_helper, JOB_CONFIGS["sfpd"]["nick"], JOB_CONFIGS["sfpd"]["timeout"], once)
    elif job_name == "lvpd_helper":
        schedule.every().day.at(job_time_str).do(lvpd_helper, JOB_CONFIGS["lvpd"]["nick"], JOB_CONFIGS["lvpd"]["timeout"], once)
    elif job_name == "biker_helper":
        schedule.every().day.at(job_time_str).do(biker_helper, biker_nick, biker_timeout, once)
    elif job_name == "afker_helper":
        schedule.every().day.at(job_time_str).do(afker_helper, afker_nick, afker_timeout, once)
    elif job_name == "update_date":
        schedule.every().day.at(job_time_str).do(update_date)
    else:
        raise ValueError(f"Unknown job_name: {job_name}")

def extra_job(job_name, delta_minutes):
    try:
        new_time = (datetime.datetime.now() + datetime.timedelta(minutes=delta_minutes)).strftime("%H:%M")
        set_schedule(job_name, new_time, True)
        return new_time
    except Exception as e:
        error_message = f"Failed to set extra-job: {e}"
        send_telegram_message(error_message)
    
def check_extra_job_robber(minutes):
    postpone_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    new_minutes = minutes
    if postpone_time.hour % 2 == 0:
        if 0 <= postpone_time.minute <= 29:
            new_minutes = minutes + 31 - postpone_time.minute
        elif 55 <= postpone_time.minute <= 59:
            new_minutes = minutes + 61 - postpone_time.minute
    else:
        if 25 <= postpone_time.minute <= 29:
            new_minutes = minutes + 31 - postpone_time.minute
        elif 55 <= postpone_time.minute <= 59:
            new_minutes = minutes + 61 - postpone_time.minute + 30
    return new_minutes
    
async def run_scheduler():
    try:
        while True:
            schedule.run_pending()
            await asyncio.sleep(1)
    except Exception as e:
        error_message = f"Scheduler failed: {e}"
        send_telegram_message(error_message)

async def run_monitor():
    global log_file, current_casino, oko_decrement, oko_list
    
    try:
        if not os.path.exists(log_path):
            send_telegram_message("Log file not found")
            return

        log_file = open(log_path, 'r+', encoding='cp1251')
        log_file.seek(0, os.SEEK_END)

        while True:
            line = log_file.readline()
            if not line:
                await asyncio.sleep(1)
                continue

            while True:
                position_before = log_file.tell()
                afterline = log_file.readline()
                if afterline and not re.search(r'^\[(\d{2}:\d{2}:\d{2})\]', afterline):
                    line += afterline
                else:
                    log_file.seek(position_before)
                    break
            
            # medic_contract
            if "[medic_contract]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))

                # logger
                if msg.get('type') == 0:
                    if msg.get('event') == 'treatment':
                        send_telegram_message(line)
                    elif msg.get('event') == 'completed_already':
                        send_telegram_message(line)
                        medic_cntr = JOB_STATE["medic"]["counter"]
                        medic_reward = JOB_STATE["medic"]["reward"]
                        if medic_cntr not in [0, 10]:
                            send_telegram_message(f"We will heal completed: <b>{int(medic_reward / 10 * medic_cntr)}$</b>", chat_id_name, thread_id_contracts, 'HTML')
                    elif msg.get('event') == 'completed':
                        if msg.get('attributes').get('completed') == True:
                            send_telegram_message(line)
                            medic_cntr = JOB_STATE["medic"]["counter"]
                            medic_reward = JOB_STATE["medic"]["reward"]
                            if medic_cntr not in [0, 10]:
                                send_telegram_message(f"We will heal completed: <b>{int(medic_reward / 10 * medic_cntr)}$</b>", chat_id_name, thread_id_contracts, 'HTML')

                elif msg.get('type') == 1:
                    send_telegram_message(line)

                # operator
                if msg.get('event') == 'stopping_route':
                    if msg.get('attributes').get('name') == 'medic_food_':
                        threading.Timer(5.0, medic_contract, args=(JOB_CONFIGS["medic"]["nicks"][1], JOB_CONFIGS["medic"]["timeout"], False)).start()
                elif msg.get('event') == 'reward':
                    JOB_STATE["medic"]["reward"] = msg.get('attributes').get('reward')
                elif msg.get('event') == 'treated':
                    JOB_STATE["medic"]["counter"] += 1
                elif msg.get('event') == 'completed_already':
                    JOB_STATE["medic"]["counter"] = 0
                elif msg.get('event') == 'completed':
                    if msg.get('attributes').get('completed') == True:
                        JOB_STATE["medic"]["counter"] = 0


            # instructor_contract
            if "stopping route instructor_health_closed" in line or "stopping route instructor_health_open" in line:
                threading.Timer(5.0, instructor_contract, args=(JOB_CONFIGS["instructor"]["nicks"][1], JOB_CONFIGS["instructor"]["timeout"], False)).start()
            if "[instructor_contract] Door moved!" in line:
                send_telegram_message(line)
                new_time = extra_job("instructor_contract", 30)
                send_telegram_message(f"Extra-job for instructor_contract set to {new_time} UTC")
                contract_status['instructor_contract'] = f'extra job {new_time} UTC'
            if "[instructor_contract] Contract number limit!" in line:
                send_telegram_message(line)
                contract_status['instructor_contract'] = 'contract limit'
            if "[instructor_contract] Student has no money!" in line:
                send_telegram_message(line)
                contract_status['instructor_contract'] = 'student has no money'
            if "[instructor_contract] Unexpected behavior!" in line:
                send_telegram_message(line)
                contract_status['instructor_contract'] = 'unexpected behavior'
            if "[instructor_contract] Connection was closed by the server" in line:
                send_telegram_message(line)
                contract_status['instructor_contract'] = 'connection closed'
            if "[instructor_contract] The connection was lost" in line:
                send_telegram_message(line)
                contract_status['instructor_contract'] = 'connection lost'
            if "[instructor_contract] Contract already completed" in line:
                send_telegram_message(line)
                contract_status['instructor_contract'] = 'TRUE'
            if "[instructor_contract] Contract completed" in line:
                reward = line[line.rfind('/') + 1:]
                send_telegram_message(line)
                send_telegram_message(f"Instructor completed: <b>{reward}</b>", chat_id_name, thread_id_contracts, 'HTML')
                contract_status['instructor_contract'] = reward


            # robber_contract
            if "[robber_contract]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))
                
                robber_one_nick = JOB_CONFIGS["robber"]["nicks"][0]
                robber_cntr = JOB_STATE["robber"]["counter"]
                robber_reward = JOB_STATE["robber"]["reward"]

                # logger
                if msg.get('type') == 0:
                    if msg.get('event') == 'treatment' or \
                       msg.get('event') == 'players_around' or \
                       msg.get('event') == 'robbed_already':
                        send_telegram_message(line)
                    elif msg.get('event') == 'robbed':
                        if msg.get('attributes').get('cooldown') == True:
                            send_telegram_message(line)
                    elif msg.get('event') == 'completed_already':
                        send_telegram_message(line)
                        if robber_cntr not in [0, 2]:
                            send_telegram_message(f"Robbery of the century completed: <b>{int(robber_reward / 2 * robber_cntr)}$</b>", chat_id_name, thread_id_contracts, 'HTML')
                    elif msg.get('event') == 'completed':
                        if msg.get('attributes').get('completed') == True:
                            if msg.get('nick') == robber_one_nick:
                                send_telegram_message(line)
                                if robber_cntr not in [0, 2]:
                                    send_telegram_message(f"Robbery of the century completed: <b>{int(robber_reward / 2 * robber_cntr)}$</b>", chat_id_name, thread_id_contracts, 'HTML')
                        elif msg.get('attributes').get('completed') == False:
                            if msg.get('nick') == robber_one_nick:
                                send_telegram_message(line)

                elif msg.get('type') == 1:
                    send_telegram_message(line)

                # operator
                robber_timeout = JOB_CONFIGS["robber"]["timeout"]
                if msg.get('event') == 'stopping_route':
                    if msg.get('attributes').get('name') == 'robberThree_spot':
                        robber_contract(JOB_CONFIGS["robber"]["nicks"][1], robber_timeout, False)
                    elif msg.get('attributes').get('name') == 'robberTwo_spot':
                        robber_contract(JOB_CONFIGS["robber"]["nicks"][0], robber_timeout, False)

                elif msg.get('event') == 'players_around':
                    minutes = check_extra_job_robber(15)
                    new_time = extra_job("robber_contract", minutes)
                    send_telegram_message(f"Extra-job for robber_contract set to {new_time} UTC")

                elif msg.get('nick') == robber_one_nick:
                    if msg.get('event') == 'reward':
                        JOB_STATE["robber"]["reward"] = msg.get('attributes').get('reward')
                    elif msg.get('event') == 'completed_already':
                        JOB_STATE["robber"]["counter"] = 0
                    elif msg.get('event') == 'robbed_already':
                        minutes = check_extra_job_robber(int(msg.get('attributes').get('timer').split(':')[0]) + 1)
                        new_time = extra_job("robber_contract", minutes)
                        send_telegram_message(f"Extra-job for robber_contract set to {new_time} UTC")
                    elif msg.get('event') == 'robbed':
                        JOB_STATE["robber"]["counter"] += 1
                    elif msg.get('event') == 'completed':
                        if msg.get('attributes').get('completed') == False:
                            minutes = check_extra_job_robber(30)
                            new_time = extra_job("robber_contract", minutes)
                            send_telegram_message(f"Next-job for robber_contract set to {new_time} UTC")
                        elif msg.get('attributes').get('completed') == True:
                            JOB_STATE["robber"]["counter"] = 0


            # croupier_contract
            if "[croupier_contract] Players around!" in line:
                send_telegram_message(line)
                new_time = extra_job("croupier_contract", 20)
                send_telegram_message(f"Extra-job for croupier_contract set to {new_time} UTC")
                contract_status['croupier_contract'] = f'extra job {new_time} UTC'
            if "[croupier_contract] Someone is already dealing!" in line:
                send_telegram_message(line)
                new_time = extra_job("croupier_contract", 20)
                send_telegram_message(f"Extra-job for croupier_contract set to {new_time} UTC")
                contract_status['croupier_contract'] = f'extra job {new_time} UTC'
            if "[croupier_contract] Dragons is closed!" in line:
                send_telegram_message(line)
                current_casino = (current_casino + 1) % 2
                new_time = extra_job("croupier_contract", 1)
                send_telegram_message(f"Extra-job for croupier_contract set to {new_time} UTC")
                contract_status['croupier_contract'] = f'extra job {new_time} UTC'
            if "[croupier_contract] Caligula is closed!" in line:
                send_telegram_message(line)
                current_casino = (current_casino + 1) % 2
                new_time = extra_job("croupier_contract", 1)
                send_telegram_message(f"Extra-job for croupier_contract set to {new_time} UTC")
                contract_status['croupier_contract'] = f'extra job {new_time} UTC'
            if "[croupier_contract] Spawn to family to treat" in line:
                send_telegram_message(line)
            if "[croupier_contract] Contract number limit!" in line:
                send_telegram_message(line)
                contract_status['croupier_contract'] = 'contract limit'
            if "[croupier_contract] Unexpected behavior!" in line:
                send_telegram_message(line)
                contract_status['croupier_contract'] = 'unexpected behavior'
            if "[croupier_contract] Connection was closed by the server" in line:
                send_telegram_message(line)
                contract_status['croupier_contract'] = 'connection closed'
            if "[croupier_contract] The connection was lost" in line:
                send_telegram_message(line)
                contract_status['croupier_contract'] = 'connection lost'
            if "[croupier_contract] Contract already completed" in line:
                send_telegram_message(line)
                contract_status['croupier_contract'] = 'TRUE'
            if "[croupier_contract] Contract completed" in line:
                reward = line[line.rfind('/') + 1:]
                send_telegram_message(line)
                send_telegram_message(f"Croupier completed: <b>{reward}</b>", chat_id_name, thread_id_contracts, 'HTML')
                contract_status['croupier_contract'] = reward


            # grib_contract
            if "[grib_contract]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))
                
                grib_cntr = JOB_STATE["grib"]["counter"]
                grib_reward = JOB_STATE["grib"]["reward"]

                # logger
                if msg.get('type') == 0:
                    if msg.get('event') == 'treatment' or \
                       msg.get('event') == 'grib_counter':
                        send_telegram_message(line)
                    elif msg.get('event') == 'completed_already':
                        send_telegram_message(line)
                        if grib_cntr not in [0, 50]:
                            send_telegram_message(f"Mushroom spot completed: <b>{int(grib_reward / 50 * grib_cntr)}$</b>", chat_id_name, thread_id_contracts, 'HTML')
                    elif msg.get('event') == 'players_memory':
                        if msg.get('attributes').get('players_memory'):
                            send_telegram_message(line)
                    elif msg.get('event') == 'completed':
                        if msg.get('attributes').get('completed') == True:
                            send_telegram_message(line)
                            if grib_cntr not in [0, 50]:
                                send_telegram_message(f"Mushroom spot completed: <b>{int(grib_reward / 50 * grib_cntr)}$</b>", chat_id_name, thread_id_contracts, 'HTML')

                elif msg.get('type') == 1:
                    send_telegram_message(line)

                # operator
                if msg.get('event') == 'reward':
                    JOB_STATE["grib"]["reward"] = msg.get('attributes').get('reward')

                elif msg.get('event') == 'completed_already':
                    JOB_STATE["grib"]["counter"] = 0

                elif msg.get('event') == 'grib_picked':
                    JOB_STATE["grib"]["counter"] += 1

                elif msg.get('event') == 'grib_counter':
                    JOB_STATE["grib"]["pickups"] = msg.get('attributes').get('counter')

                elif msg.get('event') == 'completed':
                    grib_pickups = JOB_STATE["grib"]["pickups"]
                    grib_index = JOB_STATE["grib"]["index"]
                    grib_nicks = JOB_CONFIGS["grib"]["nicks"]
                    
                    if msg.get('attributes').get('completed') == False:
                        if grib_pickups < 2:
                            JOB_STATE["grib"]["index"] += 1
                        
                        grib_index = JOB_STATE["grib"]["index"]
                        if grib_index < len(grib_nicks):
                            new_time = extra_job("grib_contract", 2)
                            send_telegram_message(f"Next-job for grib_contract set to {new_time} UTC")
                        else:
                            JOB_STATE["grib"]["index"] = 0
                            new_time = extra_job("grib_contract", 150)
                            send_telegram_message(f"Next-job for grib_contract set to {new_time} UTC")
                    elif msg.get('attributes').get('completed') == True:
                        JOB_STATE["grib"]["index"] = 0
                        JOB_STATE["grib"]["counter"] = 0

            # Other

            # transfer_helper
            if "[transfer_helper]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))
                
                transfer_reason = JOB_STATE["transfer"]["reason"]
                transfer_last_message = JOB_STATE["transfer"]["last_message"]

                # logger
                if msg.get('type') == 0:
                    if msg.get('event') == 'treatment':
                        send_telegram_message(line)
                    elif msg.get('event') == 'transferred':
                        send_telegram_message(line)

                        config.clear()
                        config.read(group_path)
                        value = int(config['earned'].get(msg.get('attributes').get('nick'), 0))
                        config['earned'][msg.get('attributes').get('nick')] = str(value + msg.get('attributes').get('sum'))
                        with open(group_path, 'w') as configfile: config.write(configfile, space_around_delimiters=False)

                        send_telegram_message(f"✅  Transferred to account <b>{msg.get('attributes').get('nick')}</b>: <b>{msg.get('attributes').get('sum')}$</b>. Reason: {transfer_reason}", chat_id_name, thread_id_contracts, 'HTML')
                        delete_telegram_message(transfer_last_message.chat.id, transfer_last_message.message_id)
                        top_update_telegram_message()
                    elif msg.get('event') == 'deposited':
                        send_telegram_message(line)
                        send_telegram_message(f"💰  Deposited <b>{msg.get('attributes').get('sum')}$</b> from <b>{msg.get('attributes').get('nick')}</b>. [{msg.get('attributes').get('timestamp')}]", chat_id_name, thread_id_contracts, 'HTML')
                        delete_telegram_message(transfer_last_message.chat.id, transfer_last_message.message_id)

                elif msg.get('type') == 1:
                    if msg.get('event') == 'timeout':
                        send_telegram_message(f"Cashier was stopped due to timeout!", transfer_last_message.chat.id, transfer_last_message.is_topic_message and transfer_last_message.message_thread_id)
                    elif msg.get('event') == 'bad_recipient':
                        send_telegram_message(f"Player is offline or level is less than 4!", transfer_last_message.chat.id, transfer_last_message.is_topic_message and transfer_last_message.message_thread_id)
                    elif msg.get('event') == 'bad_input':
                        send_telegram_message(f"Incorrect input data!", transfer_last_message.chat.id, transfer_last_message.is_topic_message and transfer_last_message.message_thread_id)
                    elif msg.get('event') == 'not_enough_money':
                        send_telegram_message(f"Not enough funds!", transfer_last_message.chat.id, transfer_last_message.is_topic_message and transfer_last_message.message_thread_id)
                    else:
                        send_telegram_message(line, transfer_last_message.chat.id, transfer_last_message.is_topic_message and transfer_last_message.message_thread_id)
                    delete_telegram_message(transfer_last_message.chat.id, transfer_last_message.message_id)

                # operator
                if msg.get('event') == 'balance':
                    config.clear()
                    config.read(transfer_path)
                    config['main']['balance'] = str(msg.get('attributes').get('balance'))
                    with open(transfer_path, 'w') as configfile: config.write(configfile, space_around_delimiters=False)

                elif msg.get('event') == 'transferred':
                    JOB_STATE["transfer"]["counter"] += msg.get('attributes').get('sum')


            # lspd_helper
            if "[lspd_helper]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))

                # logger
                if msg.get('type') == 0:
                    if msg.get('event') == 'treatment' or \
                       msg.get('event') == 'players_atwork' or \
                       msg.get('event') == 'door_moved' or \
                       msg.get('event') == 'players_around' or \
                       msg.get('event') == 'key_obtained':
                        send_telegram_message(line)
                    elif msg.get('event') == 'players_memory':
                        if msg.get('attributes').get('players_memory'):
                            send_telegram_message(line)

                elif msg.get('type') == 1:
                    send_telegram_message(line)

                # operator
                if msg.get('event') == 'players_atwork':
                    lspd_tries = JOB_STATE["lspd"]["tries"]
                    lspd_cntr = JOB_STATE["lspd"]["counter"]
                    if lspd_tries < 3:
                        JOB_STATE["lspd"]["tries"] += 1
                        new_time = extra_job("lspd_helper", 30)
                        send_telegram_message(f"Extra-job for lspd_helper set to {new_time} UTC")
                    else:
                        if lspd_cntr > 20:
                            send_telegram_message(f"LSPD contraband completed: <b>{lspd_cntr} keys</b>", chat_id_name, thread_id_contracts, 'HTML')
                        # send_telegram_message(f"LSPD contraband completed: <b>{lspd_cntr} keys</b>", recipients=chat_id_admins, parse_mode='HTML')
                        send_telegram_message(f"LSPD contraband completed: <b>{lspd_cntr} keys</b>", parse_mode='HTML')
                        JOB_STATE["lspd"]["tries"] = 0
                        JOB_STATE["lspd"]["counter"] = 0

                elif msg.get('event') in ['players_around', 'door_moved']:
                    new_time = extra_job("lspd_helper", 10)
                    send_telegram_message(f"Extra-job for lspd_helper set to {new_time} UTC")

                elif msg.get('event') == 'key_obtained':
                    JOB_STATE["lspd"]["counter"] += 1
                    new_time = extra_job("lspd_helper", 11)
                    send_telegram_message(f"Next-job for lspd_helper set to {new_time} UTC")


            # sfpd_helper
            if "[sfpd_helper]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))

                # logger
                if msg.get('type') == 0:
                    if msg.get('event') == 'treatment' or \
                            msg.get('event') == 'players_atwork' or \
                            msg.get('event') == 'door_moved' or \
                            msg.get('event') == 'players_around' or \
                            msg.get('event') == 'key_obtained':
                        send_telegram_message(line)
                    elif msg.get('event') == 'players_memory':
                        if msg.get('attributes').get('players_memory'):
                            send_telegram_message(line)

                elif msg.get('type') == 1:
                    send_telegram_message(line)

                # operator
                if msg.get('event') == 'players_atwork':
                    sfpd_tries = JOB_STATE["sfpd"]["tries"]
                    sfpd_cntr = JOB_STATE["sfpd"]["counter"]
                    if sfpd_tries < 3:
                        JOB_STATE["sfpd"]["tries"] += 1
                        new_time = extra_job("sfpd_helper", 30)
                        send_telegram_message(f"Extra-job for sfpd_helper set to {new_time} UTC")
                    else:
                        if sfpd_cntr > 20:
                            send_telegram_message(f"SFPD contraband completed: <b>{sfpd_cntr} keys</b>", chat_id_name, thread_id_contracts, 'HTML')
                        # send_telegram_message(f"SFPD contraband completed: <b>{sfpd_cntr} keys</b>", recipients=chat_id_admins, parse_mode='HTML')
                        send_telegram_message(f"SFPD contraband completed: <b>{sfpd_cntr} keys</b>", parse_mode='HTML')
                        JOB_STATE["sfpd"]["tries"] = 0
                        JOB_STATE["sfpd"]["counter"] = 0

                elif msg.get('event') in ['players_around', 'door_moved']:
                    new_time = extra_job("sfpd_helper", 10)
                    send_telegram_message(f"Extra-job for sfpd_helper set to {new_time} UTC")

                elif msg.get('event') == 'key_obtained':
                    JOB_STATE["sfpd"]["counter"] += 1
                    new_time = extra_job("sfpd_helper", 11)
                    send_telegram_message(f"Next-job for sfpd_helper set to {new_time} UTC")


            # lvpd_helper
            if "[lvpd_helper]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))

                # logger
                if msg.get('type') == 0:
                    if msg.get('event') == 'treatment' or \
                            msg.get('event') == 'players_atwork' or \
                            msg.get('event') == 'door_moved' or \
                            msg.get('event') == 'players_around' or \
                            msg.get('event') == 'key_obtained':
                        send_telegram_message(line)
                    elif msg.get('event') == 'players_memory':
                        if msg.get('attributes').get('players_memory'):
                            send_telegram_message(line)

                elif msg.get('type') == 1:
                    send_telegram_message(line)

                # operator
                if msg.get('event') == 'players_atwork':
                    lvpd_tries = JOB_STATE["lvpd"]["tries"]
                    lvpd_cntr = JOB_STATE["lvpd"]["counter"]
                    if lvpd_tries < 3:
                        JOB_STATE["lvpd"]["tries"] += 1
                        new_time = extra_job("lvpd_helper", 30)
                        send_telegram_message(f"Extra-job for lvpd_helper set to {new_time} UTC")
                    else:
                        if lvpd_cntr > 20:
                            send_telegram_message(f"LVPD contraband completed: <b>{lvpd_cntr} keys</b>", chat_id_name, thread_id_contracts, 'HTML')
                        # send_telegram_message(f"LVPD contraband completed: <b>{lvpd_cntr} keys</b>", recipients=chat_id_admins, parse_mode='HTML')
                        send_telegram_message(f"LVPD contraband completed: <b>{lvpd_cntr} keys</b>", parse_mode='HTML')
                        JOB_STATE["lvpd"]["tries"] = 0
                        JOB_STATE["lvpd"]["counter"] = 0

                elif msg.get('event') in ['players_around', 'door_moved']:
                    new_time = extra_job("lvpd_helper", 10)
                    send_telegram_message(f"Extra-job for lvpd_helper set to {new_time} UTC")

                elif msg.get('event') == 'key_obtained':
                    JOB_STATE["lvpd"]["counter"] += 1
                    new_time = extra_job("lvpd_helper", 11)
                    send_telegram_message(f"Next-job for lvpd_helper set to {new_time} UTC")


            # lavka_helper
            if "[lavka_helper]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))
                account = await select_account(msg.get('nick'))

                if msg.get('type') == 0:
                    if msg.get('event') == 'renewed':
                        renew_lavka(msg.get('nick'), msg.get('attributes').get('renewed_ts') + account[2], json.loads(account[3]) if account[3] else None, account[4],
                                    json.loads(account[5]) if account[5] else None, account[6], json.loads(account[7]) if account[7] else None)
                        formatted_time = (datetime.datetime.utcfromtimestamp(msg.get('attributes').get('renewed_ts') + account[2]) + datetime.timedelta(hours=get_utc_offset("Europe/Kyiv"))).strftime('%Y-%m-%d %H:%M:%S')
                        send_telegram_message(f"🏷️  The stall lease was renewed for {msg.get('attributes').get('renewed_hours')} h. for {650 * msg.get('attributes').get('renewed_hours')}$ until {formatted_time} ({msg.get('nick')})", account[4])
                    
                    elif msg.get('event') == 'items':
                        message = ''
                        for k, v in msg.get('attributes').items():
                            message += f"🏷️  Your item {k} in the amount of {v[0]} units was bought for {v[1]}$ by a buyer\n"
                        send_telegram_message(message, account[4])

                    elif msg.get('event') == 'players_memory':
                        if msg.get('attributes').get('players_memory'):
                            send_telegram_message(line, account[4])

                    elif msg.get('event') == 'connected':
                        send_telegram_message(f"Connected via {signed_to_ipv4_reversed(msg.get('attributes').get('ip'))}", account[4])

                elif msg.get('type') == 1:
                    send_telegram_message(line, account[4])

            if "[oko_boga]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))

                # logger
                if msg.get('type') == 0:
                    if msg.get('event') == 'set_text':
                        if oko_decrement > 0:
                            oko_decrement -= 1
                            oko_list += msg.get('attributes').get('text') + '\n'
                            if oko_decrement == 0:
                                send_telegram_message(oko_list, recipients=chat_id_admins)
                        else:
                            send_telegram_message(msg.get('attributes').get('text'), recipients=chat_id_admins)

                elif msg.get('type') == 1:
                    if msg.get('event') == 'stop':
                        send_telegram_message('👁 The Eye has closed', recipients=chat_id_admins)
                    else:
                        send_telegram_message(line)

            # catcher_helper
            if "[catcher_helper]" in line:
                msg = json.loads(re.search(r'\{.*\}', line).group(0))

                if msg.get('type') == 0:
                    send_telegram_message(line)
                elif msg.get('type') == 1:
                    send_telegram_message(line)

            if "[NET] Invalid password" in line:
                pass
                # send_telegram_message(line)
            if "[NET] Bad nickname" in line:
                send_telegram_message(line)

    except Exception as e:
        error_message = f"Monitor failed: {e}"
        send_telegram_message(error_message)
        
        for nick in JOB_CONFIGS["medic"]["nicks"]: os_controller_psterminator(nick)
        for nick in JOB_CONFIGS["instructor"]["nicks"]: os_controller_psterminator(nick)
        for nick in JOB_CONFIGS["robber"]["nicks"]: os_controller_psterminator(nick)
        for nick in JOB_CONFIGS["croupier"]["nicks"]: os_controller_psterminator(nick)
        for nick in JOB_CONFIGS["grib"]["nicks"]: os_controller_psterminator(nick)
        os_controller_psterminator(JOB_CONFIGS["lspd"]["nick"])
        os_controller_psterminator(JOB_CONFIGS["sfpd"]["nick"])
        os_controller_psterminator(JOB_CONFIGS["lvpd"]["nick"])

def os_controller_timer(ps, timer):
    try:
        time.sleep(timer * 60)
        if ps.is_running():
            cmdline = " ".join([arg for arg in ps.cmdline() if arg])
            ps.terminate()
            send_telegram_message(f"PID {ps.pid} with command '{cmdline}' timed out after {timer} minutes."
                                  f" {ps.pid} terminated.")
    except Exception as e:
        error_message = f"OS Controller (Timer) failed: {e}"
        send_telegram_message(error_message)
        raise

def os_controller_pscounter(process_name):
    try:
        count = 0
        for proc in psutil.process_iter(['name', 'cmdline', 'pid']):
            try:
                if proc.info['name'] == process_name:
                    count += 1
                    # process_pid = proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return count
    except Exception as e:
        error_message = f"OS Controller (Pscounter) failed: {e}"
        send_telegram_message(error_message)
        raise

def os_controller_psterminator(nick):
    try:
        for proc in psutil.process_iter(['name', 'cmdline', 'pid']):
            try:
                if proc.info['cmdline']:
                    process_cmdline = " ".join([arg for arg in proc.info['cmdline'] if arg])
                    bot_nick = process_cmdline[process_cmdline.rfind(' ') + 1:]
                    if bot_nick == nick:
                        proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except Exception as e:
        error_message = f"OS Controller (Psterminator) failed: {e}"
        send_telegram_message(error_message)
        raise

def os_controller_pschecker(nick):
    try:
        for proc in psutil.process_iter(['name', 'cmdline', 'pid']):
            try:
                if proc.info['cmdline']:
                    process_cmdline = " ".join([arg for arg in proc.info['cmdline'] if arg])
                    bot_nick = process_cmdline[process_cmdline.rfind(' ') + 1:]
                    if bot_nick == nick:
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except Exception as e:
        error_message = f"OS Controller (Pschecker) failed: {e}"
        send_telegram_message(error_message)
        raise

def launcher_raksamp_ps(nick, netns_id=None):
    try:
        if not netns_id:
            ps = subprocess.Popen(f'wine "{app_path}" -n {nick}', shell=True)
        else:
            ps = subprocess.Popen(f'sudo ip netns exec nord-{netns_id} sudo -u ubuntu env WINEPREFIX=/home/ubuntu/.wine-nord-{netns_id} wine "{app_path}" -n {nick}', shell=True)
        time.sleep(2)
        cps = psutil.Process(ps.pid).children(recursive=True)
        return cps[-1]
    except Exception as e:
        error_message = f"Launcher failed: {e}"
        send_telegram_message(error_message)
        raise

def clear_log():
    global log_file
    try:
        # os.path.getsize(log_path)
        log_file.seek(0)
        log_file.truncate()
        return True
    except Exception as e:
        error_message = f"Failed to clear log file: {e}"
        send_telegram_message(error_message)

def get_utc_offset(timezone_name):
    now = datetime.datetime.now(ZoneInfo(timezone_name))
    return int(now.utcoffset().total_seconds() // 3600)

def signed_to_ipv4_reversed(signed):
    unsigned = signed + 2 ** 32 if signed < 0 else signed
    ip = str(ipaddress.ip_address(unsigned))
    reversed_ip = '.'.join(reversed(ip.split('.')))
    return reversed_ip

def medic_contract(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[medic_contract] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"medic_contract start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def instructor_contract(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[instructor_contract] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"instructor_contract start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def robber_contract(nick, timeout, schedule_once):
    try:
        current_minute = datetime.datetime.now().minute
        if 25 <= current_minute <= 29 or 55 <= current_minute <= 59:
            raise ValueError(f"Current launch minute {current_minute} is restricted!")
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError("Can't launch more than 3 processes!")
        send_telegram_message(f"[robber_contract] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"robber_contract start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def croupier_contract(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[croupier_contract] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"croupier_contract start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def grib_contract(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[grib_contract] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"grib_contract start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def transfer_helper(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[transfer_helper] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"transfer_helper start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def lspd_helper(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[lspd_helper] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"lspd_helper start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def sfpd_helper(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[sfpd_helper] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"sfpd_helper start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def lvpd_helper(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[lvpd_helper] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"lvpd_helper start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def lavka_helper(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[lavka_helper] {nick} joining...")

        cursor.execute("SELECT id, vpn_hostname FROM users WHERE id = (SELECT user_id FROM accounts WHERE nick = ?)", (nick,))
        user = cursor.fetchone()

        ps = launcher_raksamp_ps(nick, user[1] != 'localhost' and user[0] or None)

        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"lavka_helper start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)
        raise

def biker_helper(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[biker_helper] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"biker_helper start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

def afker_helper(nick, timeout, schedule_once):
    try:
        if os_controller_pscounter(app_name) >= 3:
            raise ValueError(f"Can't launch more than 3 processes!")
        send_telegram_message(f"[afker_helper] {nick} joining...")
        ps = launcher_raksamp_ps(nick)
        os_controller_timer_thread = threading.Thread(target=os_controller_timer, args=(ps, timeout))
        os_controller_timer_thread.start()
        if schedule_once:
            return schedule.CancelJob
    except Exception as e:
        error_message = f"afker_helper start failed: {e}"
        send_telegram_message(error_message)
        os_controller_psterminator(nick)

# Medic
try:
    cfg = JOB_CONFIGS["medic"]
    schedule.every().day.at(cfg["schedule"]).do(medic_contract, cfg["nicks"][0], cfg["timeout"], False)
    send_telegram_message(f"medic_contract scheduled for {cfg['schedule']} UTC")
except Exception as e:
    send_telegram_message(f"Failed to schedule medic_contract: {e}")

# Instructor
try:
    cfg = JOB_CONFIGS["instructor"]
    schedule.every().day.at(cfg["schedule"]).do(instructor_contract, cfg["nicks"][0], cfg["timeout"], False)
    send_telegram_message(f"instructor_contract scheduled for {cfg['schedule']} UTC")
except Exception as e:
    send_telegram_message(f"Failed to schedule instructor_contract: {e}")

# Robber
try:
    cfg = JOB_CONFIGS["robber"]
    schedule.every().day.at(cfg["schedule"]).do(robber_contract, cfg["nicks"][2], cfg["timeout"], False)
    send_telegram_message(f"robber_contract scheduled for {cfg['schedule']} UTC")
except Exception as e:
    send_telegram_message(f"Failed to schedule robber_contract: {e}")

# Croupier
try:
    cfg = JOB_CONFIGS["croupier"]
    nick = cfg["nicks"][current_casino]
    schedule.every().day.at(cfg["schedule"]).do(croupier_contract, nick, cfg["timeout"], False)
    send_telegram_message(f"croupier_contract scheduled for {cfg['schedule']} UTC")
except Exception as e:
    send_telegram_message(f"Failed to schedule croupier_contract: {e}")

# Grib
try:
    cfg = JOB_CONFIGS["grib"]
    nick = cfg["nicks"][JOB_STATE["grib"]["index"]]
    schedule.every().day.at(cfg["schedule"]).do(grib_contract, nick, cfg["timeout"], False)
    send_telegram_message(f"grib_contract scheduled for {cfg['schedule']} UTC")
except Exception as e:
    send_telegram_message(f"Failed to schedule grib_contract: {e}")

# PD Helpers (LSPD, SFPD, LVPD)
for job_name, job_func in [("lspd", lspd_helper), ("sfpd", sfpd_helper), ("lvpd", lvpd_helper)]:
    try:
        cfg = JOB_CONFIGS[job_name]
        schedule.every().day.at(cfg["schedule"]).do(job_func, cfg["nick"], cfg["timeout"], False)
        send_telegram_message(f"{job_name}_helper scheduled for {cfg['schedule']} UTC")
    except Exception as e:
        send_telegram_message(f"Failed to schedule {job_name}_helper: {e}")

schedule.every().day.at(restart_time).do(update_date)
send_telegram_message(f"Restart scheduled for {restart_time} UTC")


# Start flask server
flask_thread = threading.Thread(target=start_flask_server)
flask_thread.start()

# Start monitor
event_loop.create_task(run_monitor())

# Start scheduler
event_loop.create_task(run_scheduler())

# Start pytgcalls
event_loop.create_task(start_pytgcalls())

# Start telegram bot
start_telegram_bot()
