import os
import re
import urllib.parse
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import aiohttp
from datetime import datetime
import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup
import json

BOT_TOKEN = os.getenv("BOT_TOKEN")
MINI_APP_URL = "https://sortik.app/?add=true"
URL_REGEX = r'https?://[\S]+'
DB_FILE = "web_cache.db"
CATEGORY_COLORS = ['red', 'blue', 'green', 'yellow', 'purple', 'pink', 'indigo', 'gray']
DEFAULT_CATEGORIES = ["News", "Tech", "Fun", "Sport", "Music"]

user_state = {}

# Initialize SQLite database
def init_db():
    db_path = Path(DB_FILE)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cache (
            user_id INTEGER,
            url TEXT,
            html_content TEXT,
            resources TEXT,
            timestamp TEXT,
            PRIMARY KEY (user_id, url)
        )
    ''')
    conn.commit()
    conn.close()

def load_cache(user_id: int) -> Dict[str, Dict[str, Any]]:
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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return f"Error: Failed to fetch content (status {response.status})", {}
                html_content = await response.text()

            soup = BeautifulSoup(html_content, 'html.parser')
            resources = {}
            return html_content, resources
    except Exception as e:
        return f"Error: {str(e)}", {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправьте ссылку для категоризации и сохранения."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
        return

    url = urls[0]
    user_state[user_id] = {"url": url}

    keyboard = [[InlineKeyboardButton("+", callback_data="add_category")]] + [
        [InlineKeyboardButton(cat, callback_data=f"select_category|{cat}|gray")]
        for cat in DEFAULT_CATEGORIES
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Получена ссылка: {url}\nВыберите категорию:",
        reply_markup=reply_markup
    )
    user_state[user_id]["bot_message_id"] = update.message.message_id

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    data = query.data

    if data == "add_category":
        user_state[user_id]["awaiting_new_category"] = True
        await query.message.delete()
        await query.message.reply_text("Введите название новой категории:")
    elif data.startswith("select_category"):
        _, category, color = data.split("|")
        url = user_state[user_id]["url"]
        html_content, _ = await fetch_website_content(url)
        title = BeautifulSoup(html_content, 'html.parser').title
        title_text = title.string.strip() if title else "Без названия"

        description = html_content[:100].strip().replace("\n", " ")

        encoded_data = urllib.parse.quote(f"{url}|{title_text}|{description}|{category}|{color}")
        link = f"https://sortik.app/?uploadnew={encoded_data}"

        await query.message.delete()
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=user_state[user_id].get("bot_message_id"))
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"Открыть: {link}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_state and user_state[user_id].get("awaiting_new_category"):
        category = update.message.text.strip()
        user_state[user_id]["new_category"] = category
        user_state[user_id].pop("awaiting_new_category")

        keyboard = [[InlineKeyboardButton(color, callback_data=f"select_category|{category}|{color}")]
                    for color in CATEGORY_COLORS]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.delete()
        await update.message.reply_text("Выберите цвет категории:", reply_markup=reply_markup)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
