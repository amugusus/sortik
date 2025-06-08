import os
import reAdd commentMore actions
import reAdd commentMore actions
import urllib.parse
from typing import Dict, Any
from typing import List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import aiohttp
from datetime import datetime
import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime
import json

BOT_TOKEN = os.getenv("BOT_TOKEN")
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
DB_FILE = "web_cache.db"

def init_db():
    db_path = Path(DB_FILE)
@@ -20,11 +18,11 @@ def init_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cache (
        CREATE TABLE IF NOT EXISTS links (
            user_id INTEGER,
            url TEXT,
            html_content TEXT,
            resources TEXT,
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
@@ -41,50 +39,46 @@ def init_db():
    conn.commit()
    conn.close()

def load_cache(user_id: int) -> Dict[str, Dict[str, Any]]:
def load_links(user_id: int) -> List[Dict[str, Any]]:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT url, html_content, resources, timestamp FROM cache WHERE user_id = ?', (user_id,))
        cursor.execute('SELECT url, category, color, timestamp FROM links WHERE user_id = ? ORDER BY timestamp', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return {
            row[0]: {
                'html_content': row[1],
                'resources': json.loads(row[2]) if row[2] else {},
                'timestamp': datetime.fromisoformat(row[3])
            } for row in rows
        }
        return [
            {'url': row[0], 'category': row[1], 'color': row[2], 'timestamp': row[3]}
            for row in rows
        ]
    except Exception as e:
        print(f"Error loading cache: {e}")
        return {}
        print(f"Error loading links: {e}")
        return []

def load_custom_categories(user_id: int) -> Dict[str, str]:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT category, color FROM custom_categories WHERE user_id = ? ORDER BY timestamp DESC', (user_id,))
        cursor.execute('SELECT category, color FROM custom_categories WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        print(f"Error loading custom categories: {e}")
        return {}

async def save_cache(user_id: int, url: str, html_content: str, resources: Dict[str, str]):
async def save_link(user_id: int, url: str, category: str = None, color: str = None):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        resources_json = json.dumps(resources)
        cursor.execute('''
            INSERT OR REPLACE INTO cache (user_id, url, html_content, resources, timestamp)
            INSERT OR REPLACE INTO links (user_id, url, category, color, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, url, html_content, resources_json, timestamp))
        ''', (user_id, url, category, color, timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving cache: {e}")
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
@@ -100,44 +94,10 @@ async def save_custom_category(user_id: int, category: str, color: str):
    except Exception as e:
        print(f"Error saving custom category: {e}")

async def fetch_website_content(url: str) -> tuple[str, Dict[str, str]]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return f"Error: Failed to fetch content (status {response.status})", {}
                html_content = await response.text()

            soup = BeautifulSoup(html_content, 'html.parser')
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
        "Все ссылки сохраняются в кеш."
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
@@ -150,11 +110,7 @@ async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
        return

    shared_url = urls[0]
    user_cache = load_cache(user_id)

    if shared_url not in user_cache:
        html_content, resources = await fetch_website_content(shared_url)
        await save_cache(user_id, shared_url, html_content, resources)
    await save_link(user_id, shared_url)  # Сохраняем ссылку без категории и цвета

    default_categories = {
        "News": "blue",
        "Tech": "green",
        "Fun": "yellow",
        "Sport": "red",
        "Music": "purple"
    }
@@ -166,18 +122,19 @@ async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    custom_categories = load_custom_categories(user_id)
    

    buttons = []
    row = [InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}")]
    all_categories = {**custom_categories, **default_categories}
    idx = 1
    for category, color in all_categories.items():
        full_payload = f"{shared_url}|{category}|{color}"
        encoded = urllib.parse.quote(full_payload, safe='')
        button_url = f"https://sortik.app/?uploadnew={encoded}"
        row.append(InlineKeyboardButton(category, web_app={"url": button_url}))
        if len(row) == 3 or (idx == len(all_categories) and row):
    row = []
    row.append(InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}"))
    buttons.append(row)

    for category, color in custom_categories.items():
        # Ограничиваем длину callback_data, чтобы избежать ошибки Button_data_invalid
        callback_data = f"assign|{shared_url}|{category}|{color}"
        if len(callback_data.encode('utf-8')) > 64:
            await update.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
            return
        buttons.append([InlineKeyboardButton(category, callback_data=callback_data)])
        buttons.append([InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}")])

    row = []
    for idx, (category, color) in enumerate(default_categories.items(), 1):
        callback_data = f"assign|{shared_url}|{category}|{color}"
        if len(callback_data.encode('utf-8')) > 64:
            await update.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
            return
        row.append(InlineKeyboardButton(category, callback_data=callback_data))
        row.append(InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}"))
        if idx % 3 == 0 or idx == len(default_categories):
            buttons.append(row)
            row = []
        idx += 1

    reply_markup = InlineKeyboardMarkup(buttons)
    context.user_data['last_url_message'] = await update.message.reply_text(
        f"Ссылка: {shared_url}\nВыберите категорию для сорта:",
        reply_markup=reply_markup
    )
@@ -187,21 +144,25 @@ async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):

async def view_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_cache = load_cache(user_id)
    links = load_links(user_id)

    if not user_cache:
    if not links:
        await update.message.reply_text("Кеш пуст.")
        return

    response = "Сохраненный кеш:\n"
    for url, data in user_cache.items():
        timestamp = data['timestamp']
        html_preview = data['html_content'][:100] + "..." if len(data['html_content']) > 100 else data['html_content']
        resources = data['resources']
        resources_count = len(resources) if resources else 0
        response += f"URL: {url}\nВремя: {timestamp}\nHTML: {html_preview}\nРесурсы: {resources_count} файлов\n\n"
    # Формируем строку для upload
    upload_data = []
    for link in links:
        url = link['url']
        category = link['category'] if link['category'] else "Uncategorized"
        color = link['color'] if link['color'] else "gray"
        upload_data.append(f"{url}|{category}|{color}")
    upload_string = "|||".join(upload_data)
    app_url = f"https://sortik.app/?upload={urllib.parse.quote(upload_string, safe='')}"

    await update.message.reply_text(response)
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
@@ -255,6 +216,7 @@ async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
@@ -269,24 +231,61 @@ async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            custom_categories = load_custom_categories(user_id)
            

            buttons = []
            row = [InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}")]
            all_categories = {**custom_categories, **default_categories}
            idx = 1
            for category, color in all_categories.items():
                full_payload = f"{shared_url}|{category}|{color}"
                encoded = urllib.parse.quote(full_payload, safe='')
                button_url = f"https://sortik.app/?uploadnew={encoded}"
                row.append(InlineKeyboardButton(category, web_app={"url": button_url}))
                if len(row) == 3 or (idx == len(all_categories) and row):
            row = []
            row.append(InlineKeyboardButton("+", callback_data=f"add_category|{shared_url}"))
            buttons.append(row)

            for category, color in custom_categories.items():
                callback_data = f"assign|{shared_url}|{category}|{color}"
                if len(callback_data.encode('utf-8')) > 64:
                    await query.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
                    return
                buttons.append([InlineKeyboardButton(category, callback_data=callback_data)])
                buttons.append([InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}")])

            row = []
            for idx, (category, color) in enumerate(default_categories.items(), 1):
                callback_data = f"assign|{shared_url}|{category}|{color}"
                if len(callback_data.encode('utf-8')) > 64:
                    await query.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
                    return
                row.append(InlineKeyboardButton(category, callback_data=callback_data))
                row.append(InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}"))
                if idx % 3 == 0 or idx == len(default_categories):
                    buttons.append(row)
                    row = []
                idx += 1

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
            callback_data = f"assign|{shared_url}|{category}|{color}"
            if len(callback_data.encode('utf-8')) > 64:
                await query.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
                return
            buttons.append([InlineKeyboardButton(category, callback_data=callback_data)])
            buttons.append([InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}")])

        row = []
        for idx, (category, color) in enumerate(default_categories.items(), 1):
            callback_data = f"assign|{shared_url}|{category}|{color}"
            if len(callback_data.encode('utf-8')) > 64:
                await query.message.reply_text("Ошибка: URL или категория слишком длинные. Попробуйте сократить.")
                return
            row.append(InlineKeyboardButton(category, callback_data=callback_data))
            row.append(InlineKeyboardButton(category, callback_data=f"assign|{shared_url}|{category}|{color}"))
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

@@ -297,12 +296,17 @@ def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(CommandHandler("lc", view_cache))
    application.add_handler(CommandHandler("categoryadd", category_add))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    print("Бот запущен...")
    application.run_polling()
    try:
        # Добавляем параметр drop_pending_updates=True для сброса ожидающих обновлений
        application.run_polling(drop_pending_updates=True)
        application.run_polling()
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
        raise

if __name__ == "__main__":
    main()
