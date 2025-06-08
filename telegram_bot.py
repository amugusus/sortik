import os
import re
import urllib.parse
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import sqlite3
from datetime import datetime
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
            category TEXT,
            color TEXT,
            timestamp TEXT,
            PRIMARY KEY (user_id, url)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_categories (
            user_id INTEGER,
            category TEXT,
            color TEXT,
            timestamp TEXT,
            PRIMARY KEY (user_id, category)
        )
    ''')
    conn.commit()
    conn.close()

def load_cache(user_id: int) -> Dict[str, Dict[str, Any]]:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT url, category, color, timestamp FROM cache WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return {
            row[0]: {
                'category': row[1],
                'color': row[2],
                'timestamp': row[3]
            } for row in rows
        }
    except Exception as e:
        print(f"Error loading cache: {e}")
        return {}

def load_custom_categories(user_id: int) -> Dict[str, str]:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT category, color FROM custom_categories WHERE user_id = ? ORDER BY timestamp DESC', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        print(f"Error loading custom categories: {e}")
        return {}

async def save_cache(user_id: int, url: str, category: str, color: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO cache (user_id, url, category, color, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, url, category, color, timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving cache: {e}")

async def save_custom_category(user_id: int, category: str, color: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO custom_categories (user_id, category, color, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (user_id, category, color, timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving custom category: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправьте ссылку на сайт. Появятся кнопки категорий, чтобы сохранить ссылку и открыть в мини-приложении."
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
        return

    shared_url = urls[0]

    default_categories = {
        "News": "blue",
        "Tech": "green",
        "Fun": "yellow",
        "Sport": "red",
        "Music": "purple"
    }
    custom_categories = load_custom_categories(user_id)
    
    buttons = []
    row = [InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}")]
    all_categories = {**custom_categories, **default_categories}
    idx = 1
    for category, color in all_categories.items():
        row.append(InlineKeyboardButton(category, callback_data=f"choose_category|{shared_url}|{category}|{color}"))
        if len(row) == 3 or (idx == len(all_categories) and row):
            buttons.append(row)
            row = []
        idx += 1

    reply_markup = InlineKeyboardMarkup(buttons)
    context.user_data['last_url_message'] = await update.message.reply_text(
        f"Ссылка: {shared_url}\nВыберите категорию:",
        reply_markup=reply_markup
    )

async def open_cached_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cache = load_cache(user_id)
    if not cache:
        await update.message.reply_text("Кеш пуст.")
        return

    parts = []
    for url, data in cache.items():
        category = data.get('category', 'Uncategorized')
        color = data.get('color', 'gray')
        parts.append(f"{url}|{category}|{color}")

    upload_string = "|||".join(parts)
    app_url = f"https://sortik.app/?upload={urllib.parse.quote(upload_string)}"

    button = InlineKeyboardMarkup([
        [InlineKeyboardButton("Открыть приложение с кешом", web_app={"url": app_url})]
    ])

    await update.message.reply_text("Открыть приложение с кешом:", reply_markup=button)

async def category_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'last_url_message' in context.user_data:
        await context.user_data['last_url_message'].delete()
        del context.user_data['last_url_message']
    context.user_data['category_add_mode'] = True
    await update.message.reply_text("Назовите новую категорию:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('category_add_mode', False):
        new_category = update.message.text.strip()
        context.user_data['new_category'] = new_category
        colors = ['red', 'blue', 'green', 'yellow', 'purple', 'pink', 'indigo', 'gray']
        buttons = []
        row = []
        for idx, color in enumerate(colors, 1):
            row.append(InlineKeyboardButton(color, callback_data=f"color|{color}"))
            if idx % 3 == 0 or idx == len(colors):
                buttons.append(row)
                row = []
        reply_markup = InlineKeyboardMarkup(buttons)
        context.user_data['category_color_message'] = await update.message.reply_text(
            f"Выберите цвет для категории '{new_category}':",
            reply_markup=reply_markup
        )
        context.user_data['category_add_mode'] = False
    else:
        await handle_url(update, context)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('|')
    user_id = update.effective_user.id

    if data[0] == "add_category":
        shared_url = data[1]
        if 'last_url_message' in context.user_data:
            await context.user_data['last_url_message'].delete()
            del context.user_data['last_url_message']
        context.user_data['category_add_mode'] = True
        context.user_data['current_url'] = shared_url
        await query.message.reply_text("Назовите новую категорию:")

    elif data[0] == "color":
        color = data[1]
        new_category = context.user_data.get('new_category')
        if new_category:
            await save_custom_category(user_id, new_category, color)
            if 'category_color_message' in context.user_data:
                await context.user_data['category_color_message'].delete()
                del context.user_data['category_color_message']
            await query.message.reply_text(f"Категория '{new_category}' сохранена.")

    elif data[0] == "choose_category":
        url, category, color = data[1], data[2], data[3]
        await save_cache(user_id, url, category, color)
        await query.message.reply_text(f"Ссылка сохранена в категории '{category}'.")

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("categoryadd", category_add))
    application.add_handler(CommandHandler("lc", open_cached_links))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
