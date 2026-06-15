import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from threading import Thread

# Flask app for Render's port check (keeps the bot alive)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    # Render uses PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# Bot settings using Render environment variables
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))

bot = Client("candid_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    if len(message.command) > 1:
        # User clicked download from channel post
        file_id = message.command[1]
        await message.reply_text("Here is your requested movie file:")
        await client.send_video(chat_id=message.chat.id, video=file_id)
    else:
        await message.reply_text("Welcome to The Candid Cut Bot! Send me a video in the channel, and I will generate download links.")

@bot.on_message(filters.chat(CHANNEL_ID) & filters.video)
async def channel_video_handler(client, message):
    file_id = message.video.file_id
    bot_username = (await client.get_me()).username
    download_link = f"https://t.me/{bot_username}?start={file_id}"
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 DOWNLOAD", url=download_link)]
    ])
    
    await message.reply_text("Click the button below to download the file privately:", reply_markup=reply_markup)

@bot.on_message(filters.command("cancel"))
async def cancel_handler(client, message):
    await message.reply_text("Action canceled.")

if __name__ == "__main__":
    # Start Flask web server in a separate thread
    t = Thread(target=run)
    t.start()
    
    # Start Telegram Bot
    bot.run()
