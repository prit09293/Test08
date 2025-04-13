import os
import io
import re
import time
import random
import contextlib
import requests
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageDraw, ImageFont
from rembg import remove
from telegraph import Telegraph
from pymongo import MongoClient

# === Environment Variables ===
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MONGO_URI = os.environ.get("MONGO_URI")
OWNER_ID = 6672752177

# === MongoDB Setup ===
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["suho_bot"]
admins_col = db["admins"]
afk_col = db["afk"]
search_modes_col = db["search_modes"]

# === Bot Init ===
app = Client("suho_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# === Utils ===
def is_admin_user(uid):
    return admins_col.find_one({"_id": uid}) is not None

def is_admin():
    return filters.create(lambda _, __, m: is_admin_user(m.from_user.id))

async def add_admin(uid: int):
    if not is_admin_user(uid):
        admins_col.insert_one({"_id": uid})

async def remove_admin(uid: int):
    if is_admin_user(uid) and uid != OWNER_ID:
        admins_col.delete_one({"_id": uid})

def set_afk(uid, reason=""):
    afk_col.replace_one({"_id": uid}, {"_id": uid, "time": time.time(), "reason": reason}, upsert=True)

def clear_afk(uid):
    afk_col.delete_one({"_id": uid})

def get_afk(uid):
    return afk_col.find_one({"_id": uid})

def get_search_mode(uid):
    doc = search_modes_col.find_one({"_id": uid})
    return doc["mode"] if doc else "telegram"

def set_search_mode(uid, mode):
    search_modes_col.replace_one({"_id": uid}, {"_id": uid, "mode": mode}, upsert=True)

# === Commands ===
@app.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    await message.reply("Suho Bot is online!")

@app.on_message(filters.command("help"))
async def help_cmd(client, message: Message):
    await message.reply(
        "**Suho Bot – Commands Guide**\n\n"
        "**Admin Commands:**\n"
        "/addadmin <user_id>, /removeadmin <user_id>, /admins\n\n"
        "**General:**\n"
        "/start, /help, /afk [reason], /searchmode <telegram|instant>, /search <query>\n\n"
        "**AI/Tools:**\n"
        "/suho <prompt>, /summarize <text>, /animequote\n"
        "/upscale 2x-10x, /rembg (reply photo), /voice (reply voice), /meme top ; bottom\n"
        "/eval <code> – admin only"
    )

@app.on_message(filters.command("addadmin") & filters.user(OWNER_ID))
async def cmd_add_admin(client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: /addadmin <user_id>")
    uid = int(message.command[1])
    await add_admin(uid)
    await message.reply(f"Added admin: {uid}")

@app.on_message(filters.command("removeadmin") & filters.user(OWNER_ID))
async def cmd_remove_admin(client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: /removeadmin <user_id>")
    uid = int(message.command[1])
    await remove_admin(uid)
    await message.reply(f"Removed admin: {uid}")

@app.on_message(filters.command("admins") & is_admin())
async def list_admins(client, message: Message):
    admins = admins_col.find()
    ids = [str(admin["_id"]) for admin in admins]
    await message.reply("Admins:\n" + "\n".join(ids))

@app.on_message(filters.command("afk"))
async def afk_cmd(client, message: Message):
    reason = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    set_afk(message.from_user.id, reason)
    await message.reply(f"AFK set{' - ' + reason if reason else ''}")

@app.on_message(filters.group & ~filters.service)
async def afk_return_check(client, message: Message):
    uid = message.from_user.id
    afk = get_afk(uid)
    if afk:
        mins = int((time.time() - afk["time"]) // 60)
        clear_afk(uid)
        await message.reply(f"Welcome back! You were AFK for {mins} minute(s).")

@app.on_message(filters.command("searchmode"))
async def set_mode(client, message: Message):
    if len(message.command) < 2 or message.command[1] not in ["telegram", "instant"]:
        return await message.reply("Use: /searchmode telegram OR instant")
    set_search_mode(message.from_user.id, message.command[1])
    await message.reply(f"Search mode set to: {message.command[1]}")

@app.on_message(filters.command("search"))
async def search_cmd(client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Use: /search <query>")
    query = message.text.split(None, 1)[1]
    mode = get_search_mode(message.from_user.id)
    try:
        url = f"https://nyaa.si/?f=0&c=0_0&q={query}&s=seeders&o=desc"
        r = requests.get(url)
        entries = re.findall(r'<tr.*?class="(?:default|danger|success)".*?</tr>', r.text, re.S)
        results = []
        for entry in entries[:10]:
            try:
                title = re.search(r'title="([^"]+)"', entry).group(1)
                link = "https://nyaa.si" + re.search(r'href="(/view/\d+)"', entry).group(1)
                magnet = re.search(r'href="(magnet:\?xt=urn:btih:[^"]+)"', entry).group(1)
                size = re.search(r'<td class="text-center">([^<]+)</td>', entry).group(1)
                seeders = re.findall(r'<td class="text-center">(\d+)</td>', entry)[-2]
                results.append((title, link, magnet, size, seeders))
            except: continue

        if mode == "telegram":
            for title, link, magnet, size, seeders in results:
                await message.reply(f"**{title}**\nSize: {size} | Seeders: {seeders}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Magnet", url=magnet)], [InlineKeyboardButton("Nyaa", url=link)]]))
        else:
            telegraph = Telegraph()
            telegraph.create_account(short_name="suho")
            html_lines = [f"<b>{title}</b><br>Size: {size} | Seeders: {seeders}<br><a href='{magnet}'>Magnet</a><br><a href='{link}'>Nyaa</a><br><br>" for title, link, magnet, size, seeders in results]
            page = telegraph.create_page(f"Nyaa Results: {query}", html_content="".join(html_lines))
            await message.reply(f"Instant View: https://telegra.ph/{page['path']}")
    except Exception as e:
        await message.reply(f"Error: {e}")

@app.on_message(filters.command("suho"))
async def suho_cmd(client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Use: /suho <prompt>")
    prompt = message.text.split(None, 1)[1]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
        result = r.json()["choices"][0]["message"]["content"]
        await message.reply(result)
    except Exception as e:
        await message.reply(f"Error: {e}")

@app.on_message(filters.command("summarize"))
async def summarize_cmd(client, message: Message):
    text = message.reply_to_message.text if message.reply_to_message else message.text.split(None, 1)[1]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": f"Summarize this: {text}"}]
    }
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
        result = r.json()["choices"][0]["message"]["content"]
        await message.reply(result)
    except Exception as e:
        await message.reply(f"Error: {e}")

@app.on_message(filters.command("animequote"))
async def quote_cmd(client, message: Message):
    quotes = [
        "'A lesson without pain is meaningless.' - Edward Elric",
        "'Power comes in response to a need, not a desire.' - Goku",
        "'Fear is not evil. It tells you what your weakness is.' - Gildarts"
    ]
    await message.reply(random.choice(quotes))

@app.on_message(filters.command("eval") & is_admin())
async def eval_cmd(client, message: Message):
    code = message.text.split(None, 1)
    if len(code) < 2:
        return await message.reply("Give me some code.")
    code = code[1]
    local_vars = {}
    stdout = io.StringIO()
    try:
        exec("async def __eval_fn(client, message):\n" +
             "\n".join(f"    {line}" for line in code.split("\n")),
             globals(), local_vars)
        with contextlib.redirect_stdout(stdout):
            result = await local_vars["__eval_fn"](client, message)
        output = stdout.getvalue()
        if result is not None:
            output += str(result)
        await message.reply(f"**Output:**\n```\n{output.strip()}\n```")
    except Exception as e:
        await message.reply(f"**Error:** `{e}`")

# === Flask + Run ===
from flask import Flask
import threading

web = Flask(__name__)

@web.route("/")
def home():
    return "Bot is alive!"

def run_web():
    web.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

def run_bot():
    app.run()

# Start both web server and bot
threading.Thread(target=run_web).start()
run_bot()
