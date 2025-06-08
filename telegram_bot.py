import osMore actions
import re
import urllib.parse
import json
import pickle
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
from datetime import datetime
import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Load token from environment variable
MINI_APP_URL = "https://sortik.app/?add=true"
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
CACHE_FILE = "web_cache.pkl"

# Dictionary to store cache: {user_id: {url: {content: str, timestamp: datetime}}}
cache: Dict[int, Dict[str, Dict[str, Any]]] = {}
DB_FILE = "web_cache.db"

# Initialize SQLite database
def init_db():
    """Initialize SQLite database for cache storage."""
    db_path = Path(DB_FILE)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cache (
            user_id INTEGER,
            url TEXT,
            html_content TEXT,
            resources TEXT,  -- JSON string of resource URLs and their content
            timestamp TEXT,
            PRIMARY KEY (user_id, url)
        )
    ''')
    conn.commit()
    conn.close()

def load_cache():
    """Load cache from file if it exists."""
    global cache
def load_cache(user_id: int) -> Dict[str, Dict[str, Any]]:
    """Load cache for a specific user from SQLite database."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT url, html_content, resources, timestamp FROM cache WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return {
            row[0]: {
                'html_content': row[1],
                'resources': json.loads(row[2]) if row[2] else {},
                'timestamp': datetime.fromisoformat(row[3])
            } for row in rows
        }
    except Exception as e:
        print(f"Error loading cache: {e}")
        return {}

async def save_cache():
    """Save cache to file."""
async def save_cache(user_id: int, url: str, html_content: str, resources: Dict[str, str]):
    """Save cache entry for a user to SQLite database."""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        resources_json = json.dumps(resources)
        cursor.execute('''
            INSERT OR REPLACE INTO cache (user_id, url, html_content, resources, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, url, html_content, resources_json, timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving cache: {e}")

async def fetch_website_content(url: str) -> str:
    """Fetch website content asynchronously."""
async def fetch_website_content(url: str) -> tuple[str, Dict[str, str]]:
    """Fetch website HTML and attempt to cache linked resources."""
    try:
        async with aiohttp.ClientSession() as session:
            # Fetch HTML content
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    return f"Error: Failed to fetch content (status {response.status})"
                if response.status != 200:
                    return f"Error: Failed to fetch content (status {response.status})", {}
                html_content = await response.text()
            
            # Parse HTML to find resource URLs (CSS, JS, images)
            soup = BeautifulSoup(html_content, 'html.parser')
            resources = {}
            resource_tags = [
                ('link', 'href', r'\.css$'),  # CSS files
                ('script', 'src', r'\.js$'),  # JS files
                ('img', 'src', r'\.(png|jpg|jpeg|gif)$')  # Images
            ]
            
            for tag, attr, pattern in resource_tags:
                for element in soup.find_all(tag, attrs={attr: re.compile(pattern)}):
                    resource_url = element.get(attr)
                    if resource_url:
                        # Convert relative URLs to absolute
                        if not resource_url.startswith(('http://', 'https://')):
                            resource_url = urllib.parse.urljoin(url, resource_url)
                        try:
                            async with session.get(resource_url, timeout=5) as res:
                                if res.status == 200:
                                    resources[resource_url] = await res.text()
                                else:
                                    resources[resource_url] = f"Error: Status {res.status}"
                        except Exception as e:
                            resources[resource_url] = f"Error: {str(e)}"
            
            return html_content, resources
    except Exception as e:
        return f"Error: {str(e)}"
        return f"Error: {str(e)}", {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Отправьте ссылку на видео или сайт, и я открою мини-приложение с этой ссылкой. "
        "Используйте /view_cache, чтобы посмотреть сохраненный кеш."
        "Отправьте ссылку на сайт, и я сохраню ее кэш (HTML и ресурсы), связанный с вашим аккаунтом. "
        "Мини-приложение получит доступ к кэшу. Используйте /view_cache, чтобы посмотреть кэш."
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
        # Load user-specific cache from database
        user_cache = load_cache(user_id)

        # Check if URL is already in cache
        if shared_url in cache[user_id]:
            content = cache[user_id][shared_url]['content']
            timestamp = cache[user_id][shared_url]['timestamp']
            await update.message.reply_text(f"Кеш найден (от {timestamp}): {content[:200]}...")
        if shared_url in user_cache:
            html_content = user_cache[shared_url]['html_content']
            timestamp = user_cache[shared_url]['timestamp']
            await update.message.reply_text(f"Кеш найден (от {timestamp}): {html_content[:200]}...")

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
            # Fetch and cache website content and resources
            html_content, resources = await fetch_website_content(shared_url)
            await save_cache(user_id, shared_url, html_content, resources)
            await update.message.reply_text(f"Сайт загружен и сохранен в кеш: {html_content[:200]}...")

        # Create button for mini app, passing user_id for cache sync
        encoded_url = urllib.parse.quote(shared_url, safe='')
        mini_app_link = f"{MINI_APP_URL}&url={encoded_url}&user_id={user_id}"
        keyboard = [
            [InlineKeyboardButton("Открыть мини-приложение", web_app={"url": mini_app_link})]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Ссылка найдена: {shared_url}\nНажмите кнопку ниже:",
            f"Ссылка найдена: {shared_url}\nНажмите кнопку ниже для открытия в мини-приложении:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")

async def view_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display cached website content for the user."""
    user_id = update.effective_user.id
    if user_id not in cache or not cache[user_id]:
    user_cache = load_cache(user_id)
    
    if not user_cache:
        await update.message.reply_text("Кеш пуст.")
        return

    response = "Сохраненный кеш:\n"
    for url, data in cache[user_id].items():
    for url, data in user_cache.items():
        timestamp = data['timestamp']
        content_preview = data['content'][:100] + "..." if len(data['content']) > 100 else data['content']
        response += f"URL: {url}\nВремя: {timestamp}\nКонтент: {content_preview}\n\n"
        html_preview = data['html_content'][:100] + "..." if len(data['html_content']) > 100 else data['html_content']
        resources = data['resources']
        resources_count = len(resources) if resources else 0
        response += f"URL: {url}\nВремя: {timestamp}\nHTML: {html_preview}\nРесурсы: {resources_count} файлов\n\n"

    await update.message.reply_text(response)

def main():
    """Main function to run the bot."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")

    # Load cache at startup (synchronously)
    load_cache()
    # Initialize database at startup
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
