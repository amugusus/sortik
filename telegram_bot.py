import os
import re
import urllib.parse
import json
import pickle
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import aiohttp
from datetime import datetime
import asyncio

# Получение токена из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
MINI_APP_URL = "https://sortik.app/?add=true"

# Регулярное выражение для поиска URL
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
CACHE_FILE = "web_cache.pkl"

# Словарь для кэша: {user_id: {url: {content: str, timestamp: datetime}}}
cache: Dict[int, Dict[str, Dict[str, Any]]] = {}
# Словарь для категорий: {user_id: {category: color}}
categories: Dict[int, Dict[str, str]] = {}
# Предустановленные категории и цвета
DEFAULT_CATEGORIES = {
    "News": "gray",
    "Tech": "blue",
    "Fun": "yellow",
    "Sport": "green",
    "Music": "purple"
}
# Доступные цвета
COLORS = ['red', 'blue', 'green', 'yellow', 'purple', 'pink', 'indigo', 'gray']

async def fetch_website_content(url: str) -> str:
    """Асинхронно загружает содержимое сайта."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    return f"Ошибка: Не удалось загрузить содержимое (статус {response.status})"
    except Exception as e:
        return f"Ошибка: {str(e)}"

async def load_cache():
    """Загружает кэш из файла, если он существует."""
    global cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
    except Exception as e:
        print(f"Ошибка загрузки кэша: {e}")

async def save_cache():
    """Сохраняет кэш в файл."""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception as e:
        print(f"Ошибка сохранения кэша: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /start."""
    await update.message.reply_text(
        "Отправьте ссылку на видео или сайт, и я открою мини-приложение с этой ссылкой. "
        "Используйте /view_cache, чтобы посмотреть сохраненный кэш."
    )

async def build_category_keyboard(user_id: int, shared_url: str, encoded_url: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру с категориями и кнопкой '+' для добавления новой."""
    if user_id not in categories:
        categories[user_id] = DEFAULT_CATEGORIES.copy()
    
    keyboard = []
    # Добавление пользовательских категорий
    for category, color in categories[user_id].items():
        if category not in DEFAULT_CATEGORIES:
            keyboard.append([InlineKeyboardButton(category, callback_data=f"cat_{category}_{shared_url}")])
    
    # Добавление предустановленных категорий
    for category, color in DEFAULT_CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(category, callback_data=f"cat_{category}_{shared_url}")])
    
    # Кнопка '+' для новой категории
    keyboard.insert(0, [InlineKeyboardButton("+", callback_data=f"add_category_{shared_url}")])
    
    return InlineKeyboardMarkup(keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает входящие сообщения с URL."""
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if urls:
        shared_url = urls[0]
        encoded_url = urllib.parse.quote(shared_url, safe='')

        # Инициализация кэша пользователя
        if user_id not in cache:
            cache[user_id] = {}

        # Проверка, есть ли URL в кэше
        if shared_url in cache[user_id]:
            content = cache[user_id][shared_url]['content']
            timestamp = cache[user_id][shared_url]['timestamp']
            await update.message.reply_text(f"Кэш найден (от {timestamp}): {content[:200]}...")
        else:
            # Загрузка и сохранение содержимого сайта в кэш
            content = await fetch_website_content(shared_url)
            cache[user_id][shared_url] = {
                'content': content,
                'timestamp': datetime.now()
            }
            await save_cache()
            await update.message.reply_text(f"Сайт загружен и сохранен в кэш: {content[:200]}...")

        # Ответ с дублированием ссылки и выбором категорий
        keyboard = await build_category_keyboard(user_id, shared_url, encoded_url)
        await update.message.reply_text(f"Полученная ссылка: {shared_url}", reply_markup=keyboard)
    else:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия на кнопки категорий и выбора цвета."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("add_category_"):
        shared_url = data[len("add_category_"):]
        context.user_data['pending_url'] = shared_url
        await query.message.reply_text("Введите название новой категории:")
        return

    elif data.startswith("color_"):
        parts = data.split("_")
        color = parts[1]
        category = context.user_data.get('pending_category')
        shared_url = context.user_data.get('pending_url')
        
        if category and shared_url:
            if user_id not in categories:
                categories[user_id] = DEFAULT_CATEGORIES.copy()
            categories[user_id][category] = color
            # Удаление сообщения с выбором цвета
            await query.message.delete()
            # Повторное отображение исходного сообщения с обновленными категориями
            encoded_url = urllib.parse.quote(shared_url, safe='')
            keyboard = await build_category_keyboard(user_id, shared_url, encoded_url)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Полученная ссылка: {shared_url}",
                reply_markup=keyboard
            )
            context.user_data.clear()

    elif data.startswith("cat_"):
        parts = data.split("_")
        category = parts[1]
        shared_url = parts[2]
        color = categories.get(user_id, DEFAULT_CATEGORIES).get(category, "gray")
        
        # Извлечение названия и описания из ссылки
        async with aiohttp.ClientSession() as session:
            async with session.get(shared_url, timeout=10) as response:
                if response.status == 200:
                    content = await response.text()
                    title = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE)
                    title = title.group(1) if title else shared_url
                    desc = re.search(r'<meta name="description" content="(.*?)"', content, re.IGNORECASE)
                    description = desc.group(1) if desc else "Описание отсутствует"
                else:
                    title = shared_url
                    description = f"Ошибка: Не удалось загрузить содержимое (статус {response.status})"
        
        # Формирование URL для мини-приложения
        encoded_url = urllib.parse.quote(shared_url, safe='')
        encoded_title = urllib.parse.quote(title, safe='')
        encoded_desc = urllib.parse.quote(description, safe='')
        mini_app_link = f"{MINI_APP_URL}&url={encoded_url}&title={encoded_title}&desc={encoded_desc}&category={category}&color={color}"
        
        keyboard = [[InlineKeyboardButton("Открыть мини-приложение", web_app={"url": mini_app_link})]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Удаление сообщения пользователя и бота
        await query.message.delete()
        await context.bot.delete_message(chat_id=user_id, message_id=query.message.reply_to_message.message_id)
        
        # Отправка ссылки на мини-приложение
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Ссылка: {shared_url}\nКатегория: {category} ({color})",
            reply_markup=reply_markup
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовый ввод для названия новой категории."""
    user_id = update.effective_user.id
    if 'pending_url' in context.user_data:
        category = update.message.text.strip()
        context.user_data['pending_category'] = category
        
        # Создание клавиатуры для выбора цвета
        keyboard = [[InlineKeyboardButton(color.capitalize(), callback_data=f"color_{color}_{context.user_data['pending_url']}")]
                    for color in COLORS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Удаление сообщения бота "Введите категорию"
        await context.bot.delete_message(chat_id=user_id, message_id=update.message.reply_to_message.message_id)
        
        # Запрос выбора цвета
        await update.message.reply_text("Выберите цвет для категории:", reply_markup=reply_markup)

async def view_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает сохраненный кэш пользователя."""
    user_id = update.effective_user.id
    if user_id not in cache or not cache[user_id]:
        await update.message.reply_text("Кэш пуст.")
        return

    response = "Сохраненный кэш:\n"
    for url, data in cache[user_id].items():
        timestamp = data['timestamp']
        content_preview = data['content'][:100] + "..." if len(data['content']) > 100 else data['content']
        response += f"URL: {url}\nВремя: {timestamp}\nКонтент: {content_preview}\n\n"
    
    await update.message.reply_text(response)

async def main():
    """Основная функция для запуска бота."""
    if not BOT_TOKEN:
        raise ValueError("Переменная окружения BOT_TOKEN не установлена")
    
    # Загрузка кэша
    await load_cache()
    
    # Инициализация приложения
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен...")
    
    # Запуск polling с использованием событийного цикла
    await application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Создаем событийный цикл и запускаем асинхронную функцию main
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()

