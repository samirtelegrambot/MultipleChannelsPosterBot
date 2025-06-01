import json
import os
import logging
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
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
ADMINS_FILE = "admins.json"
DATA_FILE = "user_channels.json"
MAX_CHANNELS = 5

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= Load Data =================
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        user_channels = json.load(f)
else:
    user_channels = {}

if os.path.exists(ADMINS_FILE):
    with open(ADMINS_FILE, "r") as f:
        try:
            admins = json.load(f)
        except json.JSONDecodeError:
            admins = []
else:
    admins = []

if OWNER_ID not in admins:
    admins.append(OWNER_ID)
    with open(ADMINS_FILE, "w") as f:
        json.dump(admins, f, indent=2)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(user_channels, f, indent=2)

def save_admins():
    with open(ADMINS_FILE, "w") as f:
        json.dump(admins, f, indent=2)

# ================= Handlers =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"/start used by user: {user_id}")

    if user_id in admins:
        keyboard = [
            [KeyboardButton("➕ Add Channel"), KeyboardButton("📤 Post to Channel")],
            [KeyboardButton("📋 My Channels"), KeyboardButton("🗑️ Remove Channel")],
            [KeyboardButton("👥 Manage Admins")],  # Added Manage Admins option
        ]
        await update.message.reply_text(
            "👋 Welcome! Choose an option:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        )
    else:
        await update.message.reply_text("❌ You are not authorized to use this bot.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in admins:
        await update.message.reply_text("❌ You are not authorized.")
        return

    text = update.message.text
    state = context.user_data.get("state")

    if text == "➕ Add Channel":
        context.user_data["state"] = "adding"
        await update.message.reply_text("🔗 Send @username or ID of the channel(s) to add (max 5).", reply_markup=ReplyKeyboardRemove())

    elif text == "📋 My Channels":
        channels = user_channels.get(str(user_id), [])
        if not channels:
            await update.message.reply_text("❌ You haven't added any channels.")
        else:
            msg = ""
            for i, ch_id in enumerate(channels):
                try:
                    chat = await context.bot.get_chat(ch_id)
                    name = chat.title or chat.username or str(chat.id)
                    msg += f"{i+1}. {name} (`{ch_id}`)\n"
                except Exception:
                    msg += f"{i+1}. ⚠️ Failed to fetch `{ch_id}`\n"
            await update.message.reply_text(f"📋 Your Channels:\n{msg}", parse_mode="Markdown")

    elif text == "🗑️ Remove Channel":
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
        await update.message.reply_text("📝 Send the message(s) you want to post.")

    # Added Manage Admins menu
    elif text == "👥 Manage Admins" and user_id == OWNER_ID:
        keyboard = [
            [KeyboardButton("➕ Add Admin"), KeyboardButton("🗑️ Remove Admins")],
            [KeyboardButton("📋 List Admins"), KeyboardButton("⬅️ Back")]
        ]
        await update.message.reply_text(
            "👥 Manage Admins Menu - Choose an option:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        )

    elif text == "➕ Add Admin" and user_id == OWNER_ID:
        context.user_data["state"] = "adding_admin"
        await update.message.reply_text("👤 Send the Telegram ID of the new admin:")

    # Added Remove Admins functionality
    elif text == "🗑️ Remove Admins" and user_id == OWNER_ID:
        if len(admins) <= 1:
            await update.message.reply_text("❌ No admins to remove (only the owner remains).")
            return
        context.user_data["state"] = "removing_admin"
        buttons = [[InlineKeyboardButton(f"❌ {admin_id}", callback_data=f"confirm_remove_admin|{admin_id}")] for admin_id in admins if admin_id != OWNER_ID]
        await update.message.reply_text("🗑️ Select an admin to remove:", reply_markup=InlineKeyboardMarkup(buttons))

    # Added List Admins functionality
    elif text == "📋 List Admins" and user_id == OWNER_ID:
        if not admins:
            await update.message.reply_text("❌ No admins found.")
        else:
            msg = "👥 Admins:\n"
            for i, admin_id in enumerate(admins):
                msg += f"{i+1}. `{admin_id}` {'(Owner)' if admin_id == OWNER_ID else ''}\n"
            await update.message.reply_text(msg, parse_mode="Markdown")

    # Added Back button functionality
    elif text == "⬅️ Back" and user_id in admins:
        keyboard = [
            [KeyboardButton("➕ Add Channel"), KeyboardButton("📤 Post to Channel")],
            [KeyboardButton("📋 My Channels"), KeyboardButton("🗑️ Remove Channel")],
            [KeyboardButton("👥 Manage Admins")],
        ]
        await update.message.reply_text(
            "👋 Welcome! Choose an option:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        )

    elif text == "✅ Post to All" and context.user_data.get("pending_post"):
        messages = context.user_data.get("pending_post", [])
        channels = user_channels.get(str(user_id), [])
        for msg in messages:
            for ch in channels:
                try:
                    await forward_cleaned(msg, context, ch)
                except Exception as e:
                    logger.warning(f"Failed to post to {ch}: {e}")
        await update.message.reply_text("✅ Posted to all channels.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()

    elif text == "❌ Cancel":
        context.user_data.clear()
        await update.message.reply_text("❌ Post cancelled.", reply_markup=ReplyKeyboardRemove())

    elif text == "📂 Select Channels" and context.user_data.get("pending_post"):
        channels = user_channels.get(str(user_id), [])
        if not channels:
            await update.message.reply_text("❌ No channels available.")
            context.user_data.clear()
            return
        context.user_data["state"] = "selecting_channels"
        context.user_data["selected_channels"] = []
        keyboard = [[KeyboardButton(ch)] for ch in channels]
        keyboard.append([KeyboardButton("✅ Done")])
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
                            await forward_cleaned(msg, context, ch)
                        except Exception as e:
                            logger.warning(f"Failed to post to {ch}: {e}")
                await update.message.reply_text("✅ Posted to selected channels.", reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()
        else:
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
                    continue
                valid_channels.append(str(chat.id))
            except Exception as e:
                logger.warning(f"Failed to add channel {ch}: {e}")

        existing = user_channels.get(str(user_id), [])
        if len(existing) + len(valid_channels) > MAX_CHANNELS:
            await update.message.reply_text(f"⚠️ Max {MAX_CHANNELS} channels allowed.")
        else:
            user_channels[str(user_id)] = list(set(existing + valid_channels))
            save_data()
            await update.message.reply_text(f"✅ Added {len(valid_channels)} channel(s).")
        context.user_data.pop("state", None)

    elif state == "adding_admin" and user_id == OWNER_ID:
        try:
            new_admin_id = int(text.strip())
            if new_admin_id not in admins:
                admins.append(new_admin_id)
                save_admins()
                await update.message.reply_text(f"✅ Added new admin: `{new_admin_id}`", parse_mode="Markdown")
            else:
                await update.message.reply_text("⚠️ Admin already exists.")
        except Exception:
            await update.message.reply_text("❌ Invalid user ID.")
        context.user_data.pop("state", None)

    else:
        await update.message.reply_text("❓ Unknown command.")

async def handle_forwards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in admins:
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

    if query.data.startswith("confirm_remove"):
        _, ch = query.data.split("|")
        channels = user_channels.get(str(user_id), [])
        if ch in channels:
            channels.remove(ch)
            user_channels[str(user_id)] = channels
            save_data()
            await query.edit_message_text(f"✅ Removed `{ch}`", parse_mode="Markdown")

    # Added handler for removing admins
    elif query.data.startswith("confirm_remove_admin"):
        _, admin_id = query.data.split("|")
        admin_id = int(admin_id)
        if admin_id in admins and admin_id != OWNER_ID:
            admins.remove(admin_id)
            save_admins()
            await query.edit_message_text(f"✅ Removed admin: `{admin_id}`", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Cannot remove the owner or invalid admin.")

async def forward_cleaned(message, context, target_chat_id):
    try:
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

# ================= Main =================
def main():
    print(f"✅ Bot is starting... OWNER_ID: {OWNER_ID}")
    print(f"Current admins: {admins}")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forwards))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_message))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
