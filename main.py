import os
import json
import logging
import feedparser
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    JobQueue,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# File to store user feeds
FEED_FILE = 'feeds.json'

# Load or initialize feed data
user_feeds = {}
if os.path.exists(FEED_FILE):
    try:
        with open(FEED_FILE, 'r') as f:
            content = f.read().strip()
            if content:
                user_feeds = json.loads(content)
    except Exception as e:
        print(f"⚠️ Failed to load JSON: {e}")
        user_feeds = {}


# Save feeds to disk
def save_feeds():
    with open(FEED_FILE, 'w') as f:
        json.dump(user_feeds, f)

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me an RSS feed URL and I'll notify you when there's a new post!"
        "Use /myfeeds to see your current subscriptions."
        "Use /removefeeds 'url' &lt;number&gt; to remove a subscription."
    )

# Handle messages (RSS URLs)
async def handle_rss_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()

    # Validate RSS
    feed = feedparser.parse(text)
    if not feed.entries:
        await update.message.reply_text("❌ Invalid RSS feed.")
        return

    # Add user and their feeds
    if user_id not in user_feeds:
        user_feeds[user_id] = {}

    if text in user_feeds[user_id]:
        await update.message.reply_text("✅ Feed already added.")
    else:
        latest_time = feed.entries[0].published if 'published' in feed.entries[0] else None
        user_feeds[user_id][text] = latest_time
        save_feeds()
        await update.message.reply_text("✅ RSS feed added!")

# Check feeds for updates
async def check_feeds(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🔁 Checking feeds...")
    for user_id, feeds in user_feeds.items():
        for feed_url in list(feeds.keys()):
            try:
                parsed = feedparser.parse(feed_url)
                if not parsed.entries:
                    continue

                latest = parsed.entries[0]
                latest_time = latest.published if 'published' in latest else None

                if feeds[feed_url] != latest_time:
                    # Send update
                    message = f"🆕 New post:\n*{latest.title}*\n{latest.link}"
                    await context.bot.send_message(chat_id=int(user_id), text=message, parse_mode='Markdown')
                    user_feeds[user_id][feed_url] = latest_time
                    save_feeds()
            except Exception as e:
                logger.warning(f"⚠️ Error parsing feed {feed_url}: {e}")


async def myfeeds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if user_id not in user_feeds or not user_feeds[user_id]:
        await update.message.reply_text("📭 You haven't subscribed to any feeds yet.")
        return

    message = "📌 Your subscribed feeds:\n"
    for i, url in enumerate(user_feeds[user_id].keys(), 1):
        message += f"{i}. {url}\n"
    await update.message.reply_text(message)

async def removefeed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    args = context.args

    if not args:
        await update.message.reply_text("❗ Please provide the feed URL to remove.\nUsage: /removefeed <url>")
        return

    feed_url = " ".join(args).strip()

    if user_id not in user_feeds or feed_url not in user_feeds[user_id]:
        await update.message.reply_text("⚠️ You're not subscribed to this feed.")
        return

    del user_feeds[user_id][feed_url]
    save_feeds()
    await update.message.reply_text("🗑️ Feed removed successfully.")

# Run the bot
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myfeeds", myfeeds))
    app.add_handler(CommandHandler("removefeed", removefeed))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rss_link))

    job_queue: JobQueue = app.job_queue
    job_queue.run_repeating(check_feeds, interval=300, first=10)

    logger.info("🤖 Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
