import json
import os
import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv
from collections import defaultdict
import asyncio
import time

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MAX_CHANNELS = 5
RATE_LIMIT_SECONDS = 60
RATE_LIMIT_MAX = 10

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(user_id)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# SQLite Database Setup
def init_db():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS user_channels (
        user_id TEXT,
        channel_id TEXT,
        PRIMARY KEY (user_id, channel_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS scheduled_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        channel_id TEXT,
        message TEXT,
        schedule_time TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# Rate Limiting
user_command_timestamps = defaultdict(list)

def check_rate_limit(user_id):
    now = time.time()
    timestamps = user_command_timestamps[user_id]
    timestamps[:] = [t for t in timestamps if now - t < RATE_LIMIT_SECONDS]
    if len(timestamps) >= RATE_LIMIT_MAX:
        return False
    timestamps.append(now)
    return True

# Database Functions
def load_admins():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    admins = [row[0] for row in c.fetchall()]
    conn.close()
    if OWNER_ID not in admins:
        admins.append(OWNER_ID)
        save_admins(admins)
    return admins

def save_admins(admins):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("DELETE FROM admins")
    for admin_id in admins:
        c.execute("INSERT OR REPLACE INTO admins (user_id) VALUES (?)", (admin_id,))
    conn.commit()
    conn.close()

def load_user_channels():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT user_id, channel_id FROM user_channels")
    user_channels = defaultdict(list)
    for user_id, channel_id in c.fetchall():
        user_channels[user_id].append(channel_id)
    conn.close()
    return user_channels

def save_user_channels(user_id, channels):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("DELETE FROM user_channels WHERE user_id = ?", (user_id,))
    for channel_id in channels:
        c.execute("INSERT INTO user_channels (user_id, channel_id) VALUES (?, ?)", (user_id, channel_id))
    conn.commit()
    conn.close()

def schedule_post(user_id, channel_id, message, schedule_time):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("INSERT INTO scheduled_posts (user_id, channel_id, message, schedule_time) VALUES (?, ?, ?, ?)",
              (user_id, channel_id, json.dumps(message), schedule_time.isoformat()))
    conn.commit()
    conn.close()

def get_scheduled_posts():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT id, user_id, channel_id, message, schedule_time FROM scheduled_posts")
    posts = [(row[0], row[1], row[2], json.loads(row[3]), datetime.fromisoformat(row[4])) for row in c.fetchall()]
    conn.close()
    return posts

def delete_scheduled_post(post_id):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()

# ================= Handlers =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logging.getLogger(__name__).setLevel(logging.INFO)
    logging.getLogger(__name__).handlers[0].setFormatter(
        logging.Formatter(f"%(asctime)s - %(levelname)s - {user_id} - %(message)s")
    )
    logger.info("/start command executed")

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    admins = load_admins()
    if user_id in admins:
        if user_id == OWNER_ID:
            keyboard = [
                [KeyboardButton("➕ Add Channel"), KeyboardButton("📤 Post to Channel")],
                [KeyboardButton("📋 My Channels"), KeyboardButton("🗑️ Remove Channel")],
                [KeyboardButton("👥 Manage Admins"), KeyboardButton("📢 Broadcast")],
                [KeyboardButton("⏰ Schedule Post")],
            ]
        else:
            keyboard = [
                [KeyboardButton("➕ Add Channel"), KeyboardButton("📤 Post to Channel")],
                [KeyboardButton("📋 My Channels"), KeyboardButton("🗑️ Remove Channel")],
                [KeyboardButton("⏰ Schedule Post")],
            ]
        await update.message.reply_text(
            "👋 Welcome! Choose an option:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        )
    else:
        await update.message.reply_text("❌ You are not authorized to use this bot.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logging.getLogger(__name__).setLevel(logging.INFO)
    logging.getLogger(__name__).handlers[0].setFormatter(
        logging.Formatter(f"%(asctime)s - %(levelname)s - {user_id} - %(message)s")
    )
    if user_id not in load_admins():
        await update.message.reply_text("❌ You are not authorized.")
        return

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    text = update.message.text
    state = context.user_data.get("state")

    if text == "❌ Cancel":
        context.user_data.clear()
        await update.message.reply_text("❌ Operation cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    if text == "➕ Add Channel":
        context.user_data["state"] = "adding"
        keyboard = [[KeyboardButton("❌ Cancel")]]
        await update.message.reply_text(
            "🔗 Send @username or ID of the channel(s) to add (max 5).",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

    elif text == "📋 My Channels":
        user_channels = load_user_channels()
        channels = user_channels.get(str(user_id), [])
        if not channels:
            await update.message.reply_text("❌ You haven't added any channels.")
            return
        page = context.user_data.get("channel_page", 0)
        per_page = 5
        total_pages = (len(channels) + per_page - 1) // per_page
        start = page * per_page
        end = start + per_page
        msg = f"📋 Your Channels (Page {page + 1}/{total_pages}):\n"
        for i, ch_id in enumerate(channels[start:end], start=start):
            try:
                chat = await context.bot.get_chat(ch_id)
                bot_member = await context.bot.get_chat_member(ch_id, context.bot.id)
                status = "✅" if bot_member.status == "administrator" else "⚠️ (Not Admin)"
                name = chat.title or chat.username or str(chat.id)
                msg += f"{i+1}. {name} (`{ch_id}`) {status}\n"
            except Exception:
                msg += f"{i+1}. ⚠️ Failed to fetch `{ch_id}`\n"
        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"channel_page|{page-1}"))
        if end < len(channels):
            buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"channel_page|{page+1}"))
        if buttons:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([buttons]))
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "🗑️ Remove Channel":
        user_channels = load_user_channels()
        channels = user_channels.get(str(user_id), [])
        if not channels:
            await update.message.reply_text("❌ No channels to remove.")
            return
        context.user_data["state"] = "removing"
        buttons = [[InlineKeyboardButton(f"❌ {ch}", callback_data=f"confirm_remove|{ch}")] for ch in channels]
        await update.message.reply_text("🗑️ Select a channel to remove:", reply_markup=InlineKeyboardMarkup(buttons))

    elif text == "📤 Post to Channel":
        context.user_data["state"] = "awaiting_post"
        context.user_data["forwarded_batch"] = []
        context.user_data["pending_post"] = []
        keyboard = [[KeyboardButton("❌ Cancel")]]
        await update.message.reply_text(
            "📝 Send the message(s) you want to post.",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

    elif text == "⏰ Schedule Post":
        context.user_data["state"] = "scheduling_post"
        context.user_data["pending_post"] = []
        keyboard = [[KeyboardButton("❌ Cancel")]]
        await update.message.reply_text(
            "📝 Send the message(s) you want to schedule.",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

    elif text == "👥 Manage Admins" and user_id == OWNER_ID:
        keyboard = [
            [KeyboardButton("➕ Add Admin"), KeyboardButton("🗑️ Remove Admins")],
            [KeyboardButton("📋 List Admins"), KeyboardButton("⬅️ Back")],
            [KeyboardButton("❌ Cancel")]
        ]
        await update.message.reply_text(
            "👥 Manage Admins Menu - Choose an option:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        )

    elif text == "➕ Add Admin" and user_id == OWNER_ID:
        context.user_data["state"] = "adding_admin"
        keyboard = [[KeyboardButton("❌ Cancel")]]
        await update.message.reply_text(
            "👤 Send the Telegram ID of the new admin:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

    elif text == "🗑️ Remove Admins" and user_id == OWNER_ID:
        admins = load_admins()
        if len(admins) <= 1:
            await update.message.reply_text("❌ No admins to remove (only the owner remains).")
            return
        context.user_data["state"] = "removing_admin"
        buttons = [[InlineKeyboardButton(f"❌ {admin_id}", callback_data=f"confirm_remove_admin|{admin_id}")] for admin_id in admins if admin_id != OWNER_ID]
        await update.message.reply_text("🗑️ Select an admin to remove:", reply_markup=InlineKeyboardMarkup(buttons))

    elif text == "📋 List Admins" and user_id == OWNER_ID:
        admins = load_admins()
        if not admins:
            await update.message.reply_text("❌ No admins found.")
        else:
            msg = "👥 Admins:\n"
            for i, admin_id in enumerate(admins):
                msg += f"{i+1}. `{admin_id}` {'(Owner)' if admin_id == OWNER_ID else ''}\n"
            await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "📢 Broadcast" and user_id == OWNER_ID:
        context.user_data["state"] = "broadcasting"
        keyboard = [[KeyboardButton("❌ Cancel")]]
        await update.message.reply_text(
            "📢 Send the message to broadcast to all admins:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

    elif text == "⬅️ Back" and user_id in load_admins():
        if user_id == OWNER_ID:
            keyboard = [
                [KeyboardButton("➕ Add Channel"), KeyboardButton("📤 Post to Channel")],
                [KeyboardButton("📋 My Channels"), KeyboardButton("🗑️ Remove Channel")],
                [KeyboardButton("👥 Manage Admins"), KeyboardButton("📢 Broadcast")],
                [KeyboardButton("⏰ Schedule Post")],
            ]
        else:
            keyboard = [
                [KeyboardButton("➕ Add Channel"), KeyboardButton("📤 Post to Channel")],
                [KeyboardButton("📋 My Channels"), KeyboardButton("🗑️ Remove Channel")],
                [KeyboardButton("⏰ Schedule Post")],
            ]
        await update.message.reply_text(
            "👋 Welcome! Choose an option:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        )

    elif text == "✅ Post to All" and context.user_data.get("pending_post"):
        messages = context.user_data.get("pending_post", [])
        user_channels = load_user_channels()
        channels = user_channels.get(str(user_id), [])
        for msg in messages:
            for ch in channels:
                try:
                    bot_member = await context.bot.get_chat_member(ch, context.bot.id)
                    if bot_member.status != "administrator":
                        logger.warning(f"Bot is not admin in {ch}")
                        continue
                    await forward_cleaned(msg, context, ch)
                except Exception as e:
                    logger.error(f"Failed to post to {ch}: {e}")
                    await update.message.reply_text(f"⚠️ Failed to post to `{ch}`: {str(e)}", parse_mode="Markdown")
        await update.message.reply_text("✅ Posted to all valid channels.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()

    elif text == "📂 Select Channels" and context.user_data.get("pending_post"):
        user_channels = load_user_channels()
        channels = user_channels.get(str(user_id), [])
        if not channels:
            await update.message.reply_text("❌ No channels available.")
            context.user_data.clear()
            return
        context.user_data["state"] = "selecting_channels"
        context.user_data["selected_channels"] = []
        keyboard = [[KeyboardButton(ch)] for ch in channels]
        keyboard.append([KeyboardButton("✅ Done"), KeyboardButton("❌ Cancel")])
        await update.message.reply_text(
            "✅ Select channels to post to:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )

    elif state == "selecting_channels":
        if text == "✅ Done":
            messages = context.user_data.get("pending_post", [])
            selected_channels = context.user_data.get("selected_channels", [])
            if not selected_channels:
                await update.message.reply_text("❌ No channels selected.")
            else:
                for msg in messages:
                    for ch in selected_channels:
                        try:
                            bot_member = await context.bot.get_chat_member(ch, context.bot.id)
                            if bot_member.status != "administrator":
                                logger.warning(f"Bot is not admin in {ch}")
                                continue
                            await forward_cleaned(msg, context, ch)
                        except Exception as e:
                            logger.error(f"Failed to post to {ch}: {e}")
                            await update.message.reply_text(f"⚠️ Failed to post to `{ch}`: {str(e)}", parse_mode="Markdown")
                await update.message.reply_text("✅ Posted to selected channels.", reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()
        else:
            user_channels = load_user_channels()
            channels = user_channels.get(str(user_id), [])
            if text in channels:
                selected = context.user_data.setdefault("selected_channels", [])
                if text not in selected:
                    selected.append(text)
                    await update.message.reply_text(f"✅ Selected: {text}")
                else:
                    await update.message.reply_text(f"⚠️ {text} already selected.")
            else:
                await update.message.reply_text("❌ Invalid channel.")

    elif state == "adding":
        new_channels = text.strip().split()
        valid_channels = []
        for ch in new_channels:
            try:
                chat = await context.bot.get_chat(ch)
                bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
                if bot_member.status != "administrator":
                    await update.message.reply_text(f"⚠️ Bot must be an admin in {ch}")
                    continue
                valid_channels.append(str(chat.id))
            except Exception as e:
                logger.error(f"Failed to add channel {ch}: {e}")
                await update.message.reply_text(f"⚠️ Failed to add {ch}: {str(e)}")

        user_channels = load_user_channels()
        existing = user_channels.get(str(user_id), [])
        if len(existing) + len(valid_channels) > MAX_CHANNELS:
            await update.message.reply_text(f"⚠️ Max {MAX_CHANNELS} channels allowed.")
        else:
            user_channels[str(user_id)] = list(set(existing + valid_channels))
            save_user_channels(str(user_id), user_channels[str(user_id)])
            await update.message.reply_text(f"✅ Added {len(valid_channels)} channel(s).")
        context.user_data.pop("state", None)
        await update.message.reply_text("⬅️ Back to main menu.", reply_markup=ReplyKeyboardRemove())

    elif state == "adding_admin" and user_id == OWNER_ID:
        try:
            new_admin_id = int(text.strip())
            if new_admin_id == user_id:
                await update.message.reply_text("❌ Cannot add yourself as admin.")
                return
            admins = load_admins()
            if new_admin_id not in admins:
                admins.append(new_admin_id)
                save_admins(admins)
                await update.message.reply_text(f"✅ Added new admin: `{new_admin_id}`", parse_mode="Markdown")
            else:
                await update.message.reply_text("⚠️ Admin already exists.")
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Please send a numeric Telegram ID.")
        context.user_data.pop("state", None)
        await update.message.reply_text("⬅️ Back to main menu.", reply_markup=ReplyKeyboardRemove())

    elif state == "broadcasting" and user_id == OWNER_ID:
        admins = load_admins()
        for admin_id in admins:
            if admin_id != user_id:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=f"📢 Broadcast: {text}")
                except Exception as e:
                    logger.error(f"Failed to broadcast to {admin_id}: {e}")
        await update.message.reply_text("✅ Broadcast sent to all admins.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()

    elif state == "scheduling_post":
        context.user_data["pending_post"].append(update.message)
        context.user_data["state"] = "scheduling_time"
        keyboard = [[KeyboardButton("❌ Cancel")]]
        await update.message.reply_text(
            "⏰ Send the schedule time (e.g., '2025-06-03 14:30' or 'in 1 hour'):",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

    elif state == "scheduling_time":
        try:
            if text.lower().startswith("in "):
                time_str = text[3:].strip()
                if "hour" in time_str:
                    hours = float(time_str.split()[0])
                    schedule_time = datetime.now() + timedelta(hours=hours)
                elif "minute" in time_str:
                    minutes = float(time_str.split()[0])
                    schedule_time = datetime.now() + timedelta(minutes=minutes)
                else:
                    raise ValueError("Invalid time format")
            else:
                schedule_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
            context.user_data["schedule_time"] = schedule_time
            user_channels = load_user_channels()
            channels = user_channels.get(str(user_id), [])
            if not channels:
                await update.message.reply_text("❌ No channels available.")
                context.user_data.clear()
                return
            context.user_data["state"] = "scheduling_channels"
            keyboard = [[KeyboardButton(ch)] for ch in channels]
            keyboard.append([KeyboardButton("✅ Done"), KeyboardButton("❌ Cancel")])
            await update.message.reply_text(
                "✅ Select channels to schedule the post:",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid time format. Use '2025-06-03 14:30' or 'in 1 hour'.")

    elif state == "scheduling_channels":
        if text == "✅ Done":
            messages = context.user_data.get("pending_post", [])
            selected_channels = context.user_data.get("selected_channels", [])
            schedule_time = context.user_data.get("schedule_time")
            if not selected_channels:
                await update.message.reply_text("❌ No channels selected.")
            else:
                for msg in messages:
                    for ch in selected_channels:
                        schedule_post(str(user_id), ch, msg.to_dict(), schedule_time)
                await update.message.reply_text(
                    f"✅ Post scheduled for {schedule_time.strftime('%Y-%m-%d %H:%M')}.",
                    reply_markup=ReplyKeyboardRemove()
                )
            context.user_data.clear()
        else:
            user_channels = load_user_channels()
            channels = user_channels.get(str(user_id), [])
            if text in channels:
                selected = context.user_data.setdefault("selected_channels", [])
                if text not in selected:
                    selected.append(text)
                    await update.message.reply_text(f"✅ Selected: {text}")
                else:
                    await update.message.reply_text(f"⚠️ {text} already selected.")
            else:
                await update.message.reply_text("❌ Invalid channel.")

    else:
        await update.message.reply_text("❓ Unknown command.")

async def handle_forwards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in load_admins():
        return

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    context.user_data.setdefault("pending_post", []).append(update.message)
    if len(context.user_data["pending_post"]) == 1:
        keyboard = [
            [KeyboardButton("✅ Post to All"), KeyboardButton("📂 Select Channels")],
            [KeyboardButton("❌ Cancel")]
        ]
        await update.message.reply_text(
            "📤 Choose where to post:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not check_rate_limit(user_id):
        await query.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    if query.data.startswith("confirm_remove"):
        _, ch = query.data.split("|")
        user_channels = load_user_channels()
        channels = user_channels.get(str(user_id), [])
        if ch in channels:
            channels.remove(ch)
            user_channels[str(user_id)] = channels
            save_user_channels(str(user_id), channels)
            await query.edit_message_text(f"✅ Removed `{ch}`", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Channel not found.")

    elif query.data.startswith("confirm_remove_admin"):
        _, admin_id = query.data.split("|")
        admin_id = int(admin_id)
        admins = load_admins()
        if admin_id in admins and admin_id != OWNER_ID:
            admins.remove(admin_id)
            save_admins(admins)
            await query.edit_message_text(f"✅ Removed admin: `{admin_id}`", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Cannot remove the owner or invalid admin.")

    elif query.data.startswith("channel_page"):
        _, page = query.data.split("|")
        context.user_data["channel_page"] = int(page)
        user_channels = load_user_channels()
        channels = user_channels.get(str(user_id), [])
        per_page = 5
        total_pages = (len(channels) + per_page - 1) // per_page
        start = int(page) * per_page
        end = start + per_page
        msg = f"📋 Your Channels (Page {int(page) + 1}/{total_pages}):\n"
        for i, ch_id in enumerate(channels[start:end], start=start):
            try:
                chat = await context.bot.get_chat(ch_id)
                bot_member = await context.bot.get_chat_member(ch_id, context.bot.id)
                status = "✅" if bot_member.status == "administrator" else "⚠️ (Not Admin)"
                name = chat.title or chat.username or str(chat.id)
                msg += f"{i+1}. {name} (`{ch_id}`) {status}\n"
            except Exception:
                msg += f"{i+1}. ⚠️ Failed to fetch `{ch_id}`\n"
        buttons = []
        if int(page) > 0:
            buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"channel_page|{int(page)-1}"))
        if end < len(channels):
            buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"channel_page|{int(page)+1}"))
        if buttons:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([buttons]))
        else:
            await query.edit_message_text(msg, parse_mode="Markdown")

async def forward_cleaned(message_dict, context, target_chat_id):
    try:
        message = Update(0, message=message_dict).message
        if message.text:
            await context.bot.send_message(chat_id=target_chat_id, text=message.text)
        elif message.photo:
            await context.bot.send_photo(chat_id=target_chat_id, photo=message.photo[-1].file_id, caption=message.caption)
        elif message.video:
            await context.bot.send_video(chat_id=target_chat_id, video=message.video.file_id, caption=message.caption)
        elif message.document:
            await context.bot.send_document(chat_id=target_chat_id, document=message.document.file_id, caption=message.caption)
    except Exception as e:
        logger.error(f"Error forwarding to {target_chat_id}: {e}")
        raise

async def check_scheduled_posts(context: ContextTypes.DEFAULT_TYPE):
    while True:
        now = datetime.now()
        posts = get_scheduled_posts()
        for post_id, user_id, channel_id, message, schedule_time in posts:
            if now >= schedule_time:
                try:
                    bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
                    if bot_member.status == "administrator":
                        await forward_cleaned(message, context, channel_id)
                    delete_scheduled_post(post_id)
                except Exception as e:
                    logger.error(f"Failed to post scheduled message to {channel_id}: {e}")
        await asyncio.sleep(60)  # Check every minute

# ================= Main =================
def main():
    print(f"✅ Bot is starting... OWNER_ID: {OWNER_ID}")
    admins = load_admins()
    print(f"Current admins: {admins}")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forwards))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_message))

    app.job_queue.run_repeating(check_scheduled_posts, interval=60, first=0)

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
