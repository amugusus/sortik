import os
import re
import urllib.parse
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import aiohttp
from datetime import datetime
import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup
import json

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Load token from environment variable
MINI_APP_URL = "https://sortik.app/?add=true"
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
DB_FILE = "web_cache.db"

# Predefined categories and their default colors
CATEGORIES = [
    {"name": "News", "color": "gray"},
    {"name": "Tech", "color": "blue"},
    {"name": "Fun", "color": "yellow"},
    {"name": "Sport", "color": "green"},
    {"name": "Music", "color": "purple"}
]
CUSTOM_CATEGORIES = []  # List to store user-defined categories
COLORS = ['red', 'blue', 'green', 'yellow', 'purple', 'pink', 'indigo', 'gray']

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

def load_cache(user_id: int) -> Dict[str, Dict[str, Any]]:
    """Load cache for a specific user from SQLite database."""
    try:
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

async def save_cache(user_id: int, url: str, html_content: str, resources: Dict[str, str]):
    """Save cache entry for a user to SQLite database."""
    try:
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

async def fetch_website_content(url: str) -> tuple[str, Dict[str, str]]:
    """Fetch website HTML and attempt to cache linked resources."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return f"Error: Failed to fetch content (status {response.status})", {}
                html_content = await response.text()
            
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
        return f"Error: {str(e)}", {}

async def extract_metadata(url: str, html_content: str) -> tuple[str, str]:
    """Extract title and description from website content."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        title = soup.title.string if soup.title else url
        description = ""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            description = meta_desc['content']
        elif 'instagram.com' in url:
            description = "Instagram post or profile"
        elif 'youtube.com' in url or 'youtu.be' in url:
            description = "YouTube video or shorts"
        else:
            og_desc = soup.find('meta', attrs={'property': 'og:description'})
            if og_desc and og_desc.get('content'):
                description = og_desc['content']
        return title.strip(), description.strip()
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return url, "No description available"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Отправьте ссылку на сайт, и над строкой ввода появится кнопка 'Открыть в мини-приложении'. "
        "Я также сохраню кэш (HTML и ресурсы), связанный с вашим аккаунтом. "
        "Используйте /view_cache, чтобы посмотреть кэш."
    )

async def build_category_keyboard(shared_url: str, user_id: int) -> InlineKeyboardMarkup:
    """Build inline keyboard with category buttons, starting with custom ones."""
    keyboard = [[InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}|{user_id}")]]
    for cat in CUSTOM_CATEGORIES:
        keyboard.append([InlineKeyboardButton(cat['name'], callback_data=f"category|{cat['name']}|{cat['color']}|{shared_url}|{user_id}")])
    for cat in CATEGORIES:
        keyboard.append([InlineKeyboardButton(cat['name'], callback_data=f"category|{cat['name']}|{cat['color']}|{shared_url}|{user_id}")])
    return InlineKeyboardMarkup(keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages with URLs, echo the URL, and show category buttons."""
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
        return

    shared_url = urls[0]
    user_cache = load_cache(user_id)

    if shared_url in user_cache:
        html_content = user_cache[shared_url]['html_content']
        timestamp = user_cache[shared_url]['timestamp']
        await update.message.reply_text(f"Кеш найден (от {timestamp}): {html_content[:200]}...")
    else:
        html_content, resources = await fetch_website_content(shared_url)
        await save_cache(user_id, shared_url, html_content, resources)
        await update.message.reply_text(f"Сайт загружен и сохранен в кеш: {html_content[:200]}...")

    # Echo the URL
    await update.message.reply_text(f"Ваша ссылка: {shared_url}")

    # Create inline button for mini app
    encoded_url = urllib.parse.quote(shared_url, safe='')
    mini_app_link = f"{MINI_APP_URL}&url={encoded_url}&user_id={user_id}"
    keyboard = [[InlineKeyboardButton("Открыть в мини-приложении", web_app={"url": mini_app_link})]]
    
    # Add category selection buttons
    category_keyboard = await build_category_keyboard(shared_url, user_id)
    keyboard.extend(category_keyboard.inline_keyboard)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Нажмите кнопку выше, чтобы открыть ссылку в мини-приложении, или выберите категорию ниже:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks for category selection and color picking."""
    query = update.callback_query
    await query.answer()
    data = query.data.split('|')
    action = data[0]

    if action == "add_category":
        shared_url, user_id = data[1], int(data[2])
        context.user_data['pending_url'] = shared_url
        context.user_data['pending_user_id'] = user_id
        await query.message.delete()
        keyboard = [[InlineKeyboardButton(color, callback_data=f"color|{color}|{shared_url}|{user_id}") for color in COLORS[i:i+2]] for i in range(0, len(COLORS), 2)]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Выберите цвет для новой категории:", reply_markup=reply_markup)
        await context.bot.send_message(chat_id=query.message.chat_id, text="Введите название новой категории:")
    elif action == "color":
        color, shared_url, user_id = data[1], data[2], int(data[3])
        context.user_data['pending_color'] = color
        await query.message.delete()
        # Wait for category name from user input, handled in handle_message
    elif action == "category":
        category, color, shared_url, user_id = data[1], data[2], data[3], int(data[4])
        user_cache = load_cache(user_id)
        html_content = user_cache.get(shared_url, {}).get('html_content', '')
        title, description = await extract_metadata(shared_url, html_content)
        upload_url = f"/?uploadnew={urllib.parse.quote(shared_url)}|{urllib.parse.quote(title)}|{urllib.parse.quote(description)}|{category}|{color}"
        await query.message.delete()
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=update.effective_message.message_id)
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"Категория выбрана: {category}\nСсылка: {upload_url}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages, including new category names."""
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if 'pending_url' in context.user_data and 'pending_color' in context.user_data:
        new_category = message_text.strip()
        shared_url = context.user_data['pending_url']
        color = context.user_data['pending_color']
        user_id = context.user_data['pending_user_id']
        CUSTOM_CATEGORIES.insert(0, {"name": new_category, "color": color})
        del context.user_data['pending_url']
        del context.user_data['pending_color']
        del context.user_data['pending_user_id']
        
        # Echo the URL again
        await update.message.reply_text(f"Ваша ссылка: {shared_url}")
        
        # Rebuild keyboard with new category at the top
        encoded_url = urllib.parse.quote(shared_url, safe='')
        mini_app_link = f"{MINI_APP_URL}&url={encoded_url}&user_id={user_id}"
        keyboard = [[InlineKeyboardButton("Открыть в мини-приложении", web_app={"url": mini_app_link})]]
        category_keyboard = await build_category_keyboard(shared_url, user_id)
        keyboard.extend(category_keyboard.inline_keyboard)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Нажмите кнопку выше, чтобы открыть ссылку в мини-приложении, или выберите категорию ниже:",
            reply_markup=reply_markup
        )
    else:
        if not urls:
            await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
            return

        shared_url = urls[0]
        user_cache = load_cache(user_id)

        if shared_url in user_cache:
            html_content = user_cache[shared_url]['html_content']
            timestamp = user_cache[shared_url]['timestamp']
            await update.message.reply_text(f"Кеш найден (от {timestamp}): {html_content[:200]}...")
        else:
            html_content, resources = await fetch_website_content(shared_url)
            await save_cache(user_id, shared_url, html_content, resources)
            await update.message.reply_text(f"Сайт загружен и сохранен в кеш: {html_content[:200]}...")

        # Echo the URL
        await update.message.reply_text(f"Ваша ссылка: {shared_url}")

        # Create inline button for mini app and categories
        encoded_url = urllib.parse.quote(shared_url, safe='')
        mini_app_link = f"{MINI_APP_URL}&url={encoded_url}&user_id={user_id}"
        keyboard = [[InlineKeyboardButton("Открыть в мини-приложении", web_app={"url": mini_app_link})]]
        category_keyboard = await build_category_keyboard(shared_url, user_id)
        keyboard.extend(category_keyboard.inline_keyboard)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Нажмите кнопку выше, чтобы открыть ссылку в мини-приложении, или выберите категорию ниже:",
            reply_markup=reply_markup
        )

async def view_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display cached website content for the user."""
    user_id = update.effective_user.id
    user_cache = load_cache(user_id)
    
    if not user_cache:
        await update.message.reply_text("Кеш пуст.")
        return

    response = "Сохраненный кеш:\n"
    for url, data in user_cache.items():
        timestamp = data['timestamp']
        html_preview = data['html_content'][:100] + "..." if len(data['html_content']) > 100 else data['html_content']
        resources = data['resources']
        resources_count = len(resources) if resources else 0
        response += f"URL: {url}\nВремя: {timestamp}\nHTML: {html_preview}\nРесурсы: {resources_count} файлов\n\n"
    
    await update.message.reply_text(response)

def main():
    """Main function to run the bot."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")
    
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
