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
import json

BOT_TOKEN = os.getenv("BOT_TOKEN")
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
DB_FILE = "web_cache.db"

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

            resources = {}
            resource_tags = [
                ('link', 'href', r'\.css$'),
                ('script', 'src', r'\.js$'),
                ('img', 'src', r'\.(png|jpg|jpeg|gif)$')
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправьте ссылку на сайт. Появятся кнопки категорий, чтобы открыть ссылку в мини-приложении. "
        "HTML и ресурсы сайта будут сохранены в кеш."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
        return

    shared_url = urls[0]
    user_cache = load_cache(user_id)

    if shared_url not in user_cache:
        html_content, resources = await fetch_website_content(shared_url)
        await save_cache(user_id, shared_url, html_content, resources)

    categories = {
        "News": "blue",
        "Tech": "green",
        "Fun": "yellow",
        "Sport": "red",
        "Music": "purple"
    }

    buttons = []
    row = []
    for idx, (category, color) in enumerate(categories.items(), 1):
        full_payload = f"{shared_url}|{category}|{color}"
        encoded = urllib.parse.quote(full_payload, safe='')
        button_url = f"https://sortik.app/?uploadnew={encoded}"
        row.append(InlineKeyboardButton(category, web_app={"url": button_url}, callback_data=f"clean_{user_id}_{update.message.message_id}"))
        if idx % 3 == 0 or idx == len(categories):
            buttons.append(row)
            row = []

    reply_markup = InlineKeyboardMarkup(buttons)

    context.user_data['last_user_message_id'] = update.message.message_id
    sent_message = await update.message.reply_text(
        f"Ссылка: {shared_url}\nВыберите категорию для сорта:",
        reply_markup=reply_markup
    )
    context.user_data['last_bot_message_id'] = sent_message.message_id

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("clean_"):
        try:
            user_id, user_message_id = map(int, query.data.split("_")[1:])
            bot_message_id = context.user_data.get('last_bot_message_id')
            
            if bot_message_id:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_message_id)
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=user_message_id)
            
            context.user_data.pop('last_user_message_id', None)
            context.user_data.pop('last_bot_message_id', None)
        except Exception as e:
            print(f"Error deleting messages: {e}")

async def view_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_button))

    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
