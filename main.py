import asyncio
import json
import os
import secrets
import logging
from flask import Flask
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Render-ന് വേണ്ടി മാത്രമുള്ള ഇൻ-ബിൽറ്റ് വെബ് സെർവർ സെറ്റപ്പ്
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is alive!", 200

@app_flask.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DELETE_DELAY_SECONDS = 10 * 60  # 10 minutes
BOT_USERNAME = "Mallucandidcut_bot"
STORE_FILE = os.path.join(os.path.dirname(__file__), "video_store.json")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

_raw_channel = os.environ.get("CHANNEL_ID", "").strip().strip("\u200b\u200c\u200d\ufeff")
try:
    CHANNEL_ID: int | str = int(_raw_channel)
except ValueError:
    CHANNEL_ID = _raw_channel

pending_poster: dict = {}

def load_store() -> dict:
    if os.path.exists(STORE_FILE):
        try:
            with open(STORE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_store(store: dict) -> None:
    with open(STORE_FILE, "w") as f:
        json.dump(store, f)

video_store: dict = load_store()

async def _delete_after_delay(bot, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(DELETE_DELAY_SECONDS)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info("Deleted message %s in chat %s.", message_id, chat_id)
    except Exception as e:
        logger.error("Failed to delete message %s in chat %s: %s", message_id, chat_id, e)

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"Your Telegram user ID is:\n\n`{user_id}`",
        parse_mode="Markdown",
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Send or forward any video to me and I'll give you a shareable link!"
        )
        return

    code = context.args[0]
    file_id = video_store.get(code)

    if not file_id:
        await update.message.reply_text(
            "Sorry, this link is invalid or the video has been removed."
        )
        return

    try:
        sent_message = await update.message.reply_video(video=file_id)
    except Exception as e:
        logger.error("Failed to send video for code %s (file_id %s): %s", code, file_id, e)
        await update.message.reply_text(
            "Sorry, I could not send that video. It may have expired."
        )
        return

    logger.info(
        "Sent video to chat %s (message %s). Scheduled deletion in %d seconds.",
        sent_message.chat_id,
        sent_message.message_id,
        DELETE_DELAY_SECONDS,
    )

    asyncio.create_task(
        _delete_after_delay(context.bot, sent_message.chat_id, sent_message.message_id)
    )

async def delete_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Only the bot owner can delete links.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/delete <code>`\n\nThe code is the last part of your share link.",
            parse_mode="Markdown",
        )
        return

    code = context.args[0]
    if code not in video_store:
        await update.message.reply_text("❌ No video found with that code.")
        return

    del video_store[code]
    save_store(video_store)
    logger.info("Deleted video link with code=%s", code)
    await update.message.reply_text(
        f"✅ Link `{code}` has been deleted. It will no longer work.",
        parse_mode="Markdown",
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        return

    chat_id = update.effective_chat.id
    if chat_id in pending_poster:
        del pending_poster[chat_id]
        await update.message.reply_text("🗑 Pending poster discarded. You can start fresh.")
    else:
        await update.message.reply_text("Nothing to cancel — no pending poster.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        return

    photo = update.message.photo[-1]
    caption = update.message.caption or ""
    chat_id = update.effective_chat.id

    pending_poster[chat_id] = {
        "photo_file_id": photo.file_id,
        "caption": caption,
    }

    logger.info("Stored pending poster for chat %s", chat_id)
    await update.message.reply_text(
        "🖼 *Poster saved!*\n\nNow send the video file and I'll post everything to the channel.",
        parse_mode="Markdown",
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Sorry, only the bot owner can upload videos.")
        return

    video = update.message.video or (
        update.message.document
        if update.message.document
        and update.message.document.mime_type
        and update.message.document.mime_type.startswith("video/")
        else None
    )

    if not video:
        return

    file_id = video.file_id
    chat_id = update.effective_chat.id

    poster = pending_poster.pop(chat_id, None)
    caption = update.message.caption or (poster["caption"] if poster else "") or ""

    code = secrets.token_urlsafe(8)
    video_store[code] = file_id
    save_store(video_store)

    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    logger.info("Saved video code=%s file_id=%s", code, file_id)

    download_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 DOWNLOAD", url=link)]
    ])

    channel_posted = False
    if CHANNEL_ID:
        try:
            if poster:
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=poster["photo_file_id"],
                    caption=caption if caption else None,
                    reply_markup=download_button,
                    parse_mode="HTML",
                )
            else:
                await context.bot.send_video(
                    chat_id=CHANNEL_ID,
                    video=file_id,
                    caption=caption if caption else None,
                    reply_markup=download_button,
                    parse_mode="HTML",
                )
            channel_posted = True
            logger.info("Posted to channel %s with code=%s (poster=%s)", CHANNEL_ID, code, bool(poster))
        except Exception as e:
            logger.error("Failed to post to channel %s: %s", CHANNEL_ID, e)

    status_line = "✅ Posted to channel!" if channel_posted else "⚠️ Could not post to channel (check bot is admin in channel)."

    await update.message.reply_text(
        f"✅ *Video saved!*\n\n"
        f"{status_line}\n\n"
        f"🔑 Code: `{code}`\n\n"
        f"Users click *📥 DOWNLOAD* → receive the video privately → auto-deleted after 10 minutes.",
        parse_mode="Markdown",
        reply_markup=download_button,
    )

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    if ADMIN_ID:
        logger.info("Admin restriction enabled for user ID %d.", ADMIN_ID)
    else:
        logger.warning("No ADMIN_ID set — anyone can upload videos.")

    if CHANNEL_ID:
        logger.info("Auto-post to channel: %r (type=%s)", CHANNEL_ID, type(CHANNEL_ID).__name__)
    else:
        logger.warning("No CHANNEL_ID set — auto-posting disabled.")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("delete", delete_link))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    app.add_handler(CommandHandler("ping", ping))

    keep_alive()
    logger.info("Bot is running. Loaded %d stored video(s).", len(video_store))
    app.run_polling()

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("പോങ്! ബോട്ട് ലൈവ് ആണ് അശ്വിൻ 🚀")

if __name__ == "__main__":
    main()
