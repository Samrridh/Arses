import logging
import json
import time 
from urllib.parse import urlparse
import asyncio 

import feedparser
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.ext import JobQueue 

from dotenv import load_dotenv
import os



logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)


load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN") 


FEEDS_FILE = "feeds.json"


CHECK_INTERVAL_SECONDS = 300 # 5min

user_feeds = {}


def load_feeds():
    global user_feeds
    try:
        with open(FEEDS_FILE, 'r', encoding='utf-8') as f:
            user_feeds = json.load(f)
        logger.info(f"Loaded {len(user_feeds)} config from {FEEDS_FILE}")
    except FileNotFoundError:
        logger.warning(f"{FEEDS_FILE} not found. Starting empty")
        user_feeds = {}

def save_feeds():
    try:
        with open(FEEDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_feeds, f, indent=4, ensure_ascii=False)
        logger.info(f"Saved feeds to {FEEDS_FILE}")
    except IOError as e:
        logger.error(f"Error saving feeds to {FEEDS_FILE}: {e}")



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
   
    await update.message.reply_html(
        f"Hi {user.mention_html()}!\n"        
        "Use /add &lt;URL&gt; to add a feed.\n"
        "Use /list to see your current subscriptions.\n"
        "Use /remove &lt;number&gt; to remove a subscription."
    )
    logger.info(f"User {user.id} started the bot.")

async def add_feed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    args = context.args

    if not args:
        await update.message.reply_text("Example: /add https://example.com/rss.xml")
        return

    feed_url = args[0]

    parsed_url = urlparse(feed_url)
    if not all([parsed_url.scheme, parsed_url.netloc]):
        await update.message.reply_text("Not a valid URL. provide a full URL including http://")
        return


    if chat_id not in user_feeds:
        user_feeds[chat_id] = {}

    if feed_url in user_feeds[chat_id]:
        await update.message.reply_text("Already subscribed")
        return

    try:
        feed = feedparser.parse(feed_url)
        if feed.bozo:
            logger.warning(f"Parsing error for {feed_url}: {feed.bozo_exception}")
            await update.message.reply_text(f"Could not parse the RSS feed from {feed_url}.")
            return

        feed_title = feed.feed.get('title', 'Untitled Feed')
        if not feed_title: 
            feed_title = f"Feed from {parsed_url.netloc}"

        last_post_link = None
        last_post_title = None
        if feed.entries:
            last_post_link = feed.entries[0].get('link')
            last_post_title = feed.entries[0].get('title', 'Untitled Post')

        user_feeds[chat_id][feed_url] = {
            "title": feed_title,
            "last_post_link": last_post_link,
            "last_post_title": last_post_title
        }
        save_feeds()
        await update.message.reply_text(f"Successfully added '{feed_title}' ({feed_url}). I will notify you of new posts.")
        logger.info(f"User {chat_id} added feed: {feed_url}")

    except Exception as e:
        logger.error(f"Error adding feed {feed_url} for user {chat_id}: {e}")
        await update.message.reply_text(f"An error occurred while trying to add the feed: {e}")

async def list_feeds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)

    if chat_id not in user_feeds or not user_feeds[chat_id]:
        await update.message.reply_text("You are not subscribed to any RSS feeds yet. Use /add <URL> to add one.")
        return

    message = "Your current RSS subscriptions:\n"
    for i, (url, data) in enumerate(user_feeds[chat_id].items()):
        message += f"{i+1}. *{data['title']}*\n   `{url}`\n"
    await update.message.reply_text(message, parse_mode='Markdown')
    logger.info(f"User {chat_id} requested feed list.")

async def remove_feed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    args = context.args

    if not args:
        await update.message.reply_text("Please provide the number of the feed to remove. Use /list to see numbers. Example: /remove 1")
        return

    if chat_id not in user_feeds or not user_feeds[chat_id]:
        await update.message.reply_text("You have no feeds to remove.")
        return

    try:
        index_to_remove = int(args[0]) - 1
        feed_urls = list(user_feeds[chat_id].keys())

        if not (0 <= index_to_remove < len(feed_urls)):
            await update.message.reply_text("Invalid feed number. Please use /list to see valid numbers.")
            return

        url_to_remove = feed_urls[index_to_remove]
        removed_feed_title = user_feeds[chat_id][url_to_remove]['title']

        del user_feeds[chat_id][url_to_remove]
        save_feeds()
        await update.message.reply_text(f"Successfully removed '{removed_feed_title}'.")
        logger.info(f"User {chat_id} removed feed: {url_to_remove}")

    except ValueError:
        await update.message.reply_text("Please provide a valid number for the feed to remove.")
    except Exception as e:
        logger.error(f"Error removing feed for user {chat_id}: {e}")
        await update.message.reply_text(f"An error occurred while trying to remove the feed: {e}")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("I'm an RSS bot! Please use commands like /add, /list, or /remove.")


async def check_for_new_posts_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running RSS feed monitoring job.")
    application = context.application 

    current_user_feeds = user_feeds.copy()

    for chat_id, feeds_data in current_user_feeds.items():
        for feed_url, feed_info in feeds_data.copy().items(): 
            try:
                feed = feedparser.parse(feed_url)

                if feed.bozo:
                    logger.warning(f"Parsing error for {feed_url} (chat_id: {chat_id}): {feed.bozo_exception}")
                    continue

                if not feed.entries:
                    logger.info(f"No entries found for feed: {feed_url}")
                    continue

                new_posts = []
                for entry in feed.entries:
                    entry_link = entry.get('link')
                    entry_title = entry.get('title', 'Untitled Post')

                    if feed_info.get('last_post_link') and entry_link == feed_info['last_post_link']:
                        break 
                    # if not feed_info.get('last_post_link') and feed_info.get('last_post_title') and entry_title == feed_info['last_post_title']:
                    #     break

                    new_posts.append(entry)

                new_posts.reverse()

                if new_posts:
                    logger.info(f"Found {len(new_posts)} new posts for {feed_info['title']} (chat_id: {chat_id})")
                    for post in new_posts:
                        post_title = post.get('title', 'Untitled Post')
                        post_link = post.get('link', '#')
                        notification_message = (
                            f"🔔 New post in *{feed_info['title']}*:\n"
                            f"*{post_title}*\n"
                            f"[Read more]({post_link})"
                        )
                        
                        try:
                            await application.bot.send_message(
                                chat_id=chat_id,
                                text=notification_message,
                                parse_mode='Markdown',
                                disable_web_page_preview=True
                            )
                            logger.info(f"Sent notification for '{post_title}' to {chat_id}")
                        except Exception as send_error:
                            logger.error(f"Error sending message to {chat_id}: {send_error}")

                    user_feeds[chat_id][feed_url]['last_post_link'] = feed.entries[0].get('link')
                    user_feeds[chat_id][feed_url]['last_post_title'] = feed.entries[0].get('title', 'Untitled Post')
                    save_feeds()

            except Exception as e:
                logger.error(f"Error checking feed {feed_url} for user {chat_id}: {e}")


def main() -> None:
    load_feeds()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_feed))
    application.add_handler(CommandHandler("list", list_feeds))
    application.add_handler(CommandHandler("remove", remove_feed))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    job_queue = application.job_queue

    job_queue.run_repeating(check_for_new_posts_job, interval=CHECK_INTERVAL_SECONDS, first=CHECK_INTERVAL_SECONDS)

    logger.info("Bot started. Press Ctrl-C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
