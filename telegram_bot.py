import os
import reAdd commentMore actions
import urllib.parse
import json
import pickle
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Load token from environment variable
MINI_APP_URL = "https://sortik.app/?add=true"

URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
CACHE_FILE = "web_cache.pkl"

# Dictionary to store cache: {user_id: {url: {content: str, timestamp: datetime}}}
cache: Dict[int, Dict[str, Dict[str, Any]]] = {}

async def fetch_website_content(url: str) -> str:
    """Fetch website content asynchronously."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    return f"Error: Failed to fetch content (status {response.status})"
    except Exception as e:
        return f"Error: {str(e)}"

async def load_cache():
    """Load cache from file if it exists."""
    global cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
    except Exception as e:
        print(f"Error loading cache: {e}")

async def save_cache():
    """Save cache to file."""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception as e:
        print(f"Error saving cache: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Отправьте ссылку на видео, и я открою мини-приложение с этой ссылкой."
        "Отправьте ссылку на видео или сайт, и я открою мини-приложение с этой ссылкой. "
        "Используйте /view_cache, чтобы посмотреть сохраненный кеш."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages with URLs."""
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if urls:
        shared_url = urls[0]
        encoded_url = urllib.parse.quote(shared_url, safe='')

        # Initialize user cache if not exists
        if user_id not in cache:
            cache[user_id] = {}

        # Check if URL is already in cache
        if shared_url in cache[user_id]:
            content = cache[user_id][shared_url]['content']
            timestamp = cache[user_id][shared_url]['timestamp']
            await update.message.reply_text(f"Кеш найден (от {timestamp}): {content[:200]}...")

        else:
            # Fetch and cache website content
            content = await fetch_website_content(shared_url)
            cache[user_id][shared_url] = {
                'content': content,
                'timestamp': datetime.now()
            }
            await save_cache()
            await update.message.reply_text(f"Сайт загружен и сохранен в кеш: {content[:200]}...")

        # Create button for mini app
        mini_app_link = f"{MINI_APP_URL}&url={encoded_url}"
        
        keyboard = [
            [InlineKeyboardButton("Открыть мини-приложение", web_app={"url": mini_app_link})]
        ]
@@ -35,11 +98,33 @@ async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    else:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")

async def view_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display cached website content for the user."""
    user_id = update.effective_user.id
    if user_id not in cache or not cache[user_id]:
        await update.message.reply_text("Кеш пуст.")
        return

    response = "Сохраненный кеш:\n"
    for url, data in cache[user_id].items():
        timestamp = data['timestamp']
        content_preview = data['content'][:100] + "..." if len(data['content']) > 100 else data['content']
        response += f"URL: {url}\nВремя: {timestamp}\nКонтент: {content_preview}\n\n"
    
    await update.message.reply_text(response)

def main():
    """Main function to run the bot."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")
    
    # Load cache at startup
    import asyncio
    asyncio.run(load_cache())
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    application.run_polling()
