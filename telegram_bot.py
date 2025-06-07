import os
import re
import urllib.parse
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
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
CATEGORIES = {
    "News": "blue",
    "Tech": "green",
    "Fun": "yellow",
    "Sport": "red",
    "Music": "purple"
}
# Store custom categories per user (in memory for simplicity; consider DB for persistence)
USER_CATEGORIES = {}
COLOR_OPTIONS = ['red', 'blue', 'green', 'yellow', 'purple', 'pink', 'indigo', 'gray']

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
            # Fetch HTML content
            async with session.get(url, timeout=10) as response:
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
        return f"Error: {str(e)}", {}

async def extract_metadata(url: str) -> tuple[str, str]:
    """Extract title and description from a URL's content."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return "Untitled", "No description available"
                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Extract title
                title = soup.title.string if soup.title else "Untitled"
                title = title.strip() if title else "Untitled"
                
                # Extract description (meta tag or first paragraph)
                description = ""
                meta_desc = soup.find('meta', attrs={'name': 'description'})
                if meta_desc and meta_desc.get('content'):
                    description = meta_desc['content'].strip()
                else:
                    p_tag = soup.find('p')
                    description = p_tag.text.strip() if p_tag else "No description available"
                
                return title, description
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return "Untitled", "No description available"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Отправьте ссылку на сайт, и над строкой ввода появится кнопка 'Открыть в мини-приложении'. "
        "Я также сохраню кэш (HTML и ресурсы), связанный с вашим аккаунтом. "
        "Используйте /view_cache, чтобы посмотреть кэш."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages with URLs, echo the URL, and show category buttons."""
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
        return

    shared_url = urls[0]
    # Load user-specific cache from database
    user_cache = load_cache(user_id)

    # Check if URL is already in cache
    if shared_url in user_cache:
        html_content = user_cache[shared_url]['html_content']
        timestamp = user_cache[shared_url]['timestamp']
        await update.message.reply_text(f"Кеш найден (от {timestamp}): {html_content[:200]}...")
    else:
        # Fetch and cache website content and resources
        html_content, resources = await fetch_website_content(shared_url)
        await save_cache(user_id, shared_url, html_content, resources)
        await update.message.reply_text(f"Сайт загружен и сохранен в кеш: {html_content[:200]}...")

    # Echo the URL in a message
    await update.message.reply_text(f"Полученная ссылка: {shared_url}")

    # Create inline buttons for categories
    keyboard = []
    # Add "+" button for new category
    keyboard.append([InlineKeyboardButton("+", callback_data=f"new_category|{shared_url}")])
    
    # Add user-defined categories first
    user_cats = USER_CATEGORIES.get(user_id, {})
    for cat, color in user_cats.items():
        keyboard.append([InlineKeyboardButton(cat, callback_data=f"category|{cat}|{color}|{shared_url}")])
    
    # Add predefined categories
    for cat, color in CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(cat, callback_data=f"category|{cat}|{color}|{shared_url}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send a message with the button that appears above the input field
    context.user_data['last_message'] = await update.message.reply_text(
        "Нажмите кнопку выше, чтобы открыть ссылку в мини-приложении:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Открыть в мини-приложении", web_app={"url": f"{MINI_APP_URL}&url={urllib.parse.quote(shared_url, safe='')}&user_id={user_id}"})]
        ])
    )
    context.user_data['category_message'] = await update.message.reply_text(
        "Выберите категорию для ссылки:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks for category selection and color choice."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data.split("|")
    action = data[0]

    if action == "new_category":
        shared_url = data[1]
        # Delete the category selection message
        await query.message.delete()
        # Ask for new category name
        context.user_data['pending_url'] = shared_url
        context.user_data['category_message'] = await query.message.reply_text(
            "Введите название новой категории:"
        )
    elif action == "color":
        category = data[1]
        shared_url = data[2]
        color = data[3]
        # Delete the color selection message
        await query.message.delete()
        # Save the new category with the selected color
        if user_id not in USER_CATEGORIES:
            USER_CATEGORIES[user_id] = {}
        USER_CATEGORIES[user_id][category] = color
        # Re-display the original message with updated categories
        keyboard = []
        keyboard.append([InlineKeyboardButton("+", callback_data=f"new_category|{shared_url}")])
        for cat, col in USER_CATEGORIES.get(user_id, {}).items():
            keyboard.append([InlineKeyboardButton(cat, callback_data=f"category|{cat}|{col}|{shared_url}")])
        for cat, col in CATEGORIES.items():
            keyboard.append([InlineKeyboardButton(cat, callback_data=f"category|{cat}|{col}|{shared_url}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.user_data['category_message'] = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Выберите категорию для ссылки:",
            reply_markup=reply_markup
        )
    elif action == "category":
        category = data[1]
        color = data[2]
        shared_url = data[3]
        # Extract metadata
        title, description = await extract_metadata(shared_url)
        # Construct the mini-app URL
        encoded_url = urllib.parse.quote(shared_url, safe='')
        upload_url = f"/?uploadnew={encoded_url}|{urllib.parse.quote(title)}|{urllib.parse.quote(description)}|{urllib.parse.quote(category)}|{color}"
        # Delete both the bot's messages and the user's message
        await query.message.delete()  # Category selection message
        if 'last_message' in context.user_data:
            await context.user_data['last_message'].delete()
        await update.effective_message.delete()  # User's original message
        # Send the final mini-app URL
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Ссылка добавлена в категорию '{category}' (цвет: {color}):\n{upload_url}"
        )

async def handle_new_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for new category name and prompt for color."""
    user_id = update.effective_user.id
    category_name = update.message.text.strip()
    shared_url = context.user_data.get('pending_url', '')
    
    if not category_name or not shared_url:
        await update.message.reply_text("Ошибка: некорректное название категории или потеряна ссылка.")
        return
    
    # Delete the "Enter category name" message
    if 'category_message' in context.user_data:
        await context.user_data['category_message'].delete()
    
    # Create color selection buttons
    keyboard = []
    for color in COLOR_OPTIONS:
        keyboard.append([InlineKeyboardButton(color.capitalize(), callback_data=f"color|{category_name}|{shared_url}|{color}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Prompt for color selection
    context.user_data['category_message'] = await update.message.reply_text(
        "Выберите цвет для категории:",
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
    
    # Initialize database at startup
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_category))
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
