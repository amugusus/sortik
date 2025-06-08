import osMore actions
import re
import urllib.parse
from typing import List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import sqlite3
from pathlib import Path
from datetime import datetime
import json

BOT_TOKEN = os.getenv("BOT_TOKEN")
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
DB_FILE = "web_cache.db"

def init_db():
    db_path = Path(DB_FILE)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS links (
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

def load_links(user_id: int) -> List[Dict[str, Any]]:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT url, category, color, timestamp FROM links WHERE user_id = ? ORDER BY timestamp', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {'url': row[0], 'category': row[1], 'color': row[2], 'timestamp': row[3]}
            for row in rows
        ]
    except Exception as e:
        print(f"Error loading links: {e}")
        return []

def load_custom_categories(user_id: int) -> Dict[str, str]:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT category, color FROM custom_categories WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        print(f"Error loading custom categories: {e}")
        return {}

async def save_link(user_id: int, url: str, category: str = None, color: str = None):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO links (user_id, url, category, color, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, url, category, color, timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving link: {e}")

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
        "Отправьте ссылку на сайт. Появятся кнопки категорий, чтобы открыть ссылку в мини-приложении. "
        "Все ссылки сохраняются в кеш."
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
        return

    shared_url = urls[0]
    await save_link(user_id, shared_url)  # Сохраняем ссылку без категории и цвета

    default_categories = {
        "News": "blue",
        "Tech": "green",
        "Fun": "yellow",
        "Sport": "red",
        "Music": "purple"
    }
    custom_categories = load_custom_categories(user_id)

    buttons = []
    row = []
    row.append(InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}"))
    buttons.append(row)

    for category, color in custom_categories.items():
        buttons.append([InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}")])
        # Ограничиваем длину callback_data, чтобы избежать ошибки Button_data_invalid
        callback_data = f"assign|{shared_url}|{category}|{color}"
        if len(callback_data.encode('utf-8')) > 64:
            await update.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
            return
        buttons.append([InlineKeyboardButton(category, callback_data=callback_data)])

    row = []
    for idx, (category, color) in enumerate(default_categories.items(), 1):
        row.append(InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}"))
        callback_data = f"assign|{shared_url}|{category}|{color}"
        if len(callback_data.encode('utf-8')) > 64:
            await update.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
            return
        row.append(InlineKeyboardButton(category, callback_data=callback_data))
        if idx % 3 == 0 or idx == len(default_categories):
            buttons.append(row)
            row = []

    reply_markup = InlineKeyboardMarkup(buttons)
    context.user_data['last_url_message'] = await update.message.reply_text(
        f"Ссылка: {shared_url}\nВыберите категорию для сорта:",
        reply_markup=reply_markup
    )

async def view_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    links = load_links(user_id)

    if not links:
        await update.message.reply_text("Кеш пуст.")
        return

    # Формируем строку для upload
    upload_data = []
    for link in links:
        url = link['url']
        category = link['category'] if link['category'] else "Uncategorized"
        color = link['color'] if link['color'] else "gray"
        upload_data.append(f"{url}|{category}|{color}")
    upload_string = "|||".join(upload_data)
    app_url = f"https://sortik.app/?upload={urllib.parse.quote(upload_string, safe='')}"

    buttons = [[InlineKeyboardButton("Открыть приложение с кешом", web_app={"url": app_url})]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Открыть приложение с кешом:", reply_markup=reply_markup)

async def category_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if 'last_url_message' in context.user_data:
        await context.user_data['last_url_message'].delete()
        del context.user_data['last_url_message']
    context.user_data['category_add_mode'] = True
    context.user_data['category_add_trigger'] = 'command'
    await update.message.reply_text("Назовите новую категорию:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
        context.user_data['category_add_trigger'] = 'button'
        context.user_data['current_url'] = shared_url
        await query.message.reply_text("Назовите новую категорию:")
    elif data[0] == "color":
        color = data[1]
        new_category = context.user_data.get('new_category')
        shared_url = context.user_data.get('current_url')
        if new_category and shared_url:
            await save_custom_category(user_id, new_category, color)
            await save_link(user_id, shared_url, new_category, color)
            if 'category_color_message' in context.user_data:
                await context.user_data['category_color_message'].delete()
                del context.user_data['category_color_message']

            default_categories = {
                "News": "blue",
                "Tech": "green",
                "Fun": "yellow",
                "Sport": "red",
                "Music": "purple"
            }
            custom_categories = load_custom_categories(user_id)

            buttons = []
            row = []
            row.append(InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}"))
            buttons.append(row)

            for category, color in custom_categories.items():
                buttons.append([InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}")])
                callback_data = f"assign|{shared_url}|{category}|{color}"
                if len(callback_data.encode('utf-8')) > 64:
                    await query.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
                    return
                buttons.append([InlineKeyboardButton(category, callback_data=callback_data)])

            row = []
            for idx, (category, color) in enumerate(default_categories.items(), 1):
                row.append(InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}"))
                callback_data = f"assign|{shared_url}|{category}|{color}"
                if len(callback_data.encode('utf-8')) > 64:
                    await query.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
                    return
                row.append(InlineKeyboardButton(category, callback_data=callback_data))
                if idx % 3 == 0 or idx == len(default_categories):
                    buttons.append(row)
                    row = []

            reply_markup = InlineKeyboardMarkup(buttons)
            context.user_data['last_url_message'] = await query.message.reply_text(
                f"Ссылка: {shared_url}\nВыберите категорию для сорта:",
                reply_markup=reply_markup
            )
    elif data[0] == "assign":
        shared_url, category, color = data[1], data[2], data[3]
        await save_link(user_id, shared_url, category, color)
        if 'last_url_message' in context.user_data:
            await context.user_data['last_url_message'].delete()
            del context.user_data['last_url_message']

        default_categories = {
            "News": "blue",
            "Tech": "green",
            "Fun": "yellow",
            "Sport": "red",
            "Music": "purple"
        }
        custom_categories = load_custom_categories(user_id)

        buttons = []
        row = []
        row.append(InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}"))
        buttons.append(row)

        for category, color in custom_categories.items():
            buttons.append([InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}")])
            callback_data = f"assign|{shared_url}|{category}|{color}"
            if len(callback_data.encode('utf-8')) > 64:
                await query.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
                return
            buttons.append([InlineKeyboardButton(category, callback_data=callback_data)])

        row = []
        for idx, (category, color) in enumerate(default_categories.items(), 1):
            row.append(InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}"))
            callback_data = f"assign|{shared_url}|{category}|{color}"
            if len(callback_data.encode('utf-8')) > 64:
                await query.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
                return
            row.append(InlineKeyboardButton(category, callback_data=callback_data))
            if idx % 3 == 0 or idx == len(default_categories):
                buttons.append(row)
                row = []

        reply_markup = InlineKeyboardMarkup(buttons)
        context.user_data['last_url_message'] = await query.message.reply_text(
            f"Ссылка: {shared_url}\nВыберите категорию для сорта:",
            reply_markup=reply_markup
        )

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(CommandHandler("lc", view_cache))
    application.add_handler(CommandHandler("categoryadd", category_add))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    print("Бот запущен...")
    try:
        application.run_polling()
        # Добавляем параметр drop_pending_updates=True для сброса ожидающих обновлений
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
        raise

if __name__ == "__main__":
    main()
