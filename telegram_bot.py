import os
import re
import urllib.parse
import pickle
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
import aiohttp
from datetime import datetime
import asyncio

BOT_TOKEN = os.getenv("BOT_TOKEN")
MINI_APP_URL = "https://sortik.app/?add=true"
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
CACHE_FILE = "web_cache.pkl"

cache: Dict[int, Dict[str, Dict[str, Any]]] = {}
categories: Dict[int, Dict[str, str]] = {}
DEFAULT_CATEGORIES = {
    "News": "gray",
    "Tech": "blue",
    "Fun": "yellow",
    "Sport": "green",
    "Music": "purple"
}
COLORS = ['red', 'blue', 'green', 'yellow', 'purple', 'pink', 'indigo', 'gray']


async def fetch_website_content(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    return f"Ошибка: Статус {response.status}"
    except Exception as e:
        return f"Ошибка: {str(e)}"


async def load_cache():
    global cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
    except Exception as e:
        print(f"Ошибка загрузки кэша: {e}")


async def save_cache():
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception as e:
        print(f"Ошибка сохранения кэша: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправьте ссылку на сайт или видео. "
        "Я открою мини-приложение с этой ссылкой. "
        "Для просмотра кэша: /view_cache"
    )


async def build_category_keyboard(user_id: int, shared_url: str) -> InlineKeyboardMarkup:
    if user_id not in categories:
        categories[user_id] = DEFAULT_CATEGORIES.copy()

    keyboard = [[InlineKeyboardButton("+", callback_data=f"add_category_{shared_url}")]]
    used = set()

    for category, color in categories[user_id].items():
        if category not in used:
            keyboard.append([InlineKeyboardButton(category, callback_data=f"cat_{category}_{shared_url}")])
            used.add(category)

    return InlineKeyboardMarkup(keyboard)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text.strip()

    # Пользователь вводит название новой категории
    if 'pending_url' in context.user_data:
        category = message_text
        context.user_data['pending_category'] = category

        keyboard = [[InlineKeyboardButton(color.capitalize(), callback_data=f"color_{color}_{context.user_data['pending_url']}")]
                    for color in COLORS]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("Выберите цвет для категории:", reply_markup=reply_markup)
        return

    # Проверка на URL
    urls = re.findall(URL_REGEX, message_text)
    if urls:
        shared_url = urls[0]

        if user_id not in cache:
            cache[user_id] = {}

        if shared_url in cache[user_id]:
            content = cache[user_id][shared_url]['content']
            timestamp = cache[user_id][shared_url]['timestamp']
            await update.message.reply_text(f"Кэш найден (от {timestamp}): {content[:200]}...")
        else:
            content = await fetch_website_content(shared_url)
            cache[user_id][shared_url] = {
                'content': content,
                'timestamp': datetime.now()
            }
            await save_cache()
            await update.message.reply_text(f"Сайт загружен: {content[:200]}...")

        keyboard = await build_category_keyboard(user_id, shared_url)
        await update.message.reply_text(f"Полученная ссылка: {shared_url}", reply_markup=keyboard)
    else:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку или название категории.")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        _, color, url = data.split("_", 2)
        category = context.user_data.get('pending_category')
        shared_url = context.user_data.get('pending_url')

        if category and shared_url:
            if user_id not in categories:
                categories[user_id] = DEFAULT_CATEGORIES.copy()
            categories[user_id][category] = color

            await query.message.delete()

            keyboard = await build_category_keyboard(user_id, shared_url)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Полученная ссылка: {shared_url}",
                reply_markup=keyboard
            )
            context.user_data.clear()

    elif data.startswith("cat_"):
        _, category, shared_url = data.split("_", 2)
        color = categories.get(user_id, DEFAULT_CATEGORIES).get(category, "gray")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(shared_url, timeout=10) as response:
                    if response.status == 200:
                        content = await response.text()
                        title = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE)
                        title = title.group(1) if title else shared_url
                        desc = re.search(r'<meta name="description" content="(.*?)"', content, re.IGNORECASE)
                        description = desc.group(1) if desc else "Описание отсутствует"
                    else:
                        title = shared_url
                        description = f"Ошибка {response.status}"
            except Exception as e:
                title = shared_url
                description = str(e)

        encoded_url = urllib.parse.quote(shared_url, safe='')
        encoded_title = urllib.parse.quote(title, safe='')
        encoded_desc = urllib.parse.quote(description, safe='')
        mini_app_link = f"{MINI_APP_URL}&url={encoded_url}&title={encoded_title}&desc={encoded_desc}&category={category}&color={color}"

        keyboard = [[InlineKeyboardButton("Открыть мини-приложение", web_app={"url": mini_app_link})]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.delete()
        if query.message.reply_to_message:
            await context.bot.delete_message(chat_id=user_id, message_id=query.message.reply_to_message.message_id)

        await context.bot.send_message(
            chat_id=user_id,
            text=f"Ссылка: {shared_url}\nКатегория: {category} ({color})",
            reply_markup=reply_markup
        )


async def view_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in cache or not cache[user_id]:
        await update.message.reply_text("Кэш пуст.")
        return

    response = "Сохранённый кэш:\n"
    for url, data in cache[user_id].items():
        timestamp = data['timestamp']
        content_preview = data['content'][:100] + "..." if len(data['content']) > 100 else data['content']
        response += f"URL: {url}\nВремя: {timestamp}\nКонтент: {content_preview}\n\n"

    await update.message.reply_text(response)


async def main():
    if not BOT_TOKEN:
        raise ValueError("Переменная окружения BOT_TOKEN не установлена")

    await load_cache()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("view_cache", view_cache))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    asyncio.run(main())
