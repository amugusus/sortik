import os
import re
import urllib.parse
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
from datetime import datetime
import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        async with aiohttp.ClientSession(headers=headers) as session:
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

async def extract_metadata(url: str, html_content: str) -> tuple[str, str]:
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Initialize defaults
        title = "Untitled"
        description = "No description available"
        
        # Try multiple title sources
        title_sources = [
            lambda: soup.title.string.strip() if soup.title and soup.title.string else None,
            lambda: soup.find('meta', attrs={'property': 'og:title'})['content'].strip() if soup.find('meta', attrs={'property': 'og:title'}) and soup.find('meta', attrs={'property': 'og:title'}).get('content') else None,
            lambda: soup.find('meta', attrs={'name': 'twitter:title'})['content'].strip() if soup.find('meta', attrs={'name': 'twitter:title'}) and soup.find('meta', attrs={'name': 'twitter:title'}).get('content') else None,
            lambda: soup.find('h1').text.strip() if soup.find('h1') else None
        ]
        
        # Try multiple description sources
        description_sources = [
            lambda: soup.find('meta', attrs={'name': 'description'})['content'].strip() if soup.find('meta', attrs={'name': 'description'}) and soup.find('meta', attrs={'name': 'description'}).get('content') else None,
            lambda: soup.find('meta', attrs={'property': 'og:description'})['content'].strip() if soup.find('meta', attrs={'property': 'og:description'}) and soup.find('meta', attrs={'property': 'og:description'}).get('content') else None,
            lambda: soup.find('meta', attrs={'name': 'twitter:description'})['content'].strip() if soup.find('meta', attrs={'name': 'twitter:description'}) and soup.find('meta', attrs={'name': 'twitter:description'}).get('content') else None,
            lambda: ' '.join([p.text.strip() for p in soup.find_all('p')[:2]]) if soup.find_all('p') else None
        ]
        
        # Extract title from available sources
        for source in title_sources:
            try:
                result = source()
                if result and result.strip():
                    title = result
                    break
            except Exception:
                continue
        
        # Extract description from available sources
        for source in description_sources:
            try:
                result = source()
                if result and result.strip():
                    description = result
                    break
            except Exception:
                continue
        
        # Clean up title and description
        title = re.sub(r'\s+', ' ', title).strip()
        description = re.sub(r'\s+', ' ', description).strip()
        
        # Handle specific platforms with fallback
        if any(domain in url for domain in ['youtube.com', 'youtu.be', 'instagram.com', 'facebook.com', 'tiktok.com', 'twitter.com', 'x.com']):
            if title == "Untitled":
                title = soup.find('meta', attrs={'property': 'og:title'})['content'].strip() if soup.find('meta', attrs={'property': 'og:title'}) and soup.find('meta', attrs={'property': 'og:title'}).get('content') else title
            if description == "No description available":
                description = soup.find('meta', attrs={'property': 'og:description'})['content'].strip() if soup.find('meta', attrs={'property': 'og:description'}) and soup.find('meta', attrs={'property': 'og:description'}).get('content') else description
        
        return title, description
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return "Untitled", "No description available"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправьте ссылку на сайт. Появятся кнопки категорий, чтобы открывать ссылку в мини-приложении. "
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
    else:
        await update.message.reply_text(f"Кеш найден (от {user_cache[shared_url]['timestamp']}).")

    html_content = user_cache.get(shared_url, {}).get('html_content', '')
    if not html_content or "Error" in html_content:
        html_content, resources = await fetch_website_content(shared_url)
        await save_cache(user_id, shared_url, html_content, resources)

    title, description = await extract_metadata(shared_url, html_content)

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
        full_payload = f"{shared_url}|{title}|{description}|{category}|{color}"
        encoded = urllib.parse.quote(full_payload, safe='')
        button_url = f"https://sortik.app/?uploadnew={encoded}"
        row.append(InlineKeyboardButton(category, web_app={"url": button_url}))
        if idx % 3 == 0 or idx == len(categories):
            buttons.append(row)
            row = []

    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        f"Ссылка: {shared_url}\nВыберите категорию для сорта:",
        reply_markup=reply_markup
    )

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

    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
