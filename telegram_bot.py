import os
import re
import urllib.parse
from collections import defaultdict
from typing import Dict, List
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'

# Временное хранилище
user_states = defaultdict(dict)

# Предустановленные категории
default_categories = [
    {"name": "News", "color": "blue"},
    {"name": "Tech", "color": "green"},
    {"name": "Fun", "color": "pink"},
    {"name": "Sport", "color": "red"},
    {"name": "Music", "color": "purple"},
]

COLOR_CHOICES = ['red', 'blue', 'green', 'yellow', 'purple', 'pink', 'indigo', 'gray']


def get_category_keyboard(user_id: int) -> InlineKeyboardMarkup:
    user_data = user_states.get(user_id, {})
    custom_categories = user_data.get("custom_categories", [])
    categories = custom_categories + default_categories
    keyboard = [[InlineKeyboardButton(cat["name"], callback_data=f"cat:{cat['name']}") for cat in categories]]
    keyboard.append([InlineKeyboardButton("+", callback_data="add_category")])
    return InlineKeyboardMarkup(keyboard)


def get_color_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(color, callback_data=f"color:{color}")]
        for color in COLOR_CHOICES
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправьте ссылку, и я помогу вам выбрать категорию.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    # Если пользователь в режиме создания новой категории — перенаправим в другой хендлер
    if user_states.get(user_id, {}).get("stage") == "awaiting_new_category":
        await handle_new_category_name(update, context)
        return

    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
        return

    shared_url = urls[0]
    user_states[user_id] = {
        "url": shared_url,
        "message_id": update.message.message_id,
        "stage": "choosing_category"
    }

    await update.message.reply_text(
        f"Вы прислали ссылку:\n{shared_url}\n\nВыберите категорию:",
        reply_markup=get_category_keyboard(user_id)
    )


async def handle_new_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    new_cat_name = update.message.text.strip()
    if not new_cat_name:
        await update.message.reply_text("Название категории не может быть пустым.")
        return

    user_states[user_id]["new_category_name"] = new_cat_name
    user_states[user_id]["stage"] = "awaiting_color"

    await update.message.reply_text("Выберите цвет для новой категории:", reply_markup=get_color_keyboard())


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "add_category":
        user_states[user_id]["stage"] = "awaiting_new_category"
        await query.message.reply_text("Введите название новой категории:")
        return

    if data.startswith("color:"):
        color = data.split(":")[1]
        new_cat = user_states[user_id].get("new_category_name")
        if new_cat:
            user_states[user_id].setdefault("custom_categories", [])
            user_states[user_id]["custom_categories"].insert(0, {"name": new_cat, "color": color})

        # Очистка и возврат к выбору категорий
        await query.message.delete()
        url = user_states[user_id].get("url")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Вы прислали ссылку:\n{url}\n\nВыберите категорию:",
            reply_markup=get_category_keyboard(user_id)
        )
        return

    if data.startswith("cat:"):
        category = data.split(":")[1]
        all_categories = user_states[user_id].get("custom_categories", []) + default_categories
        selected_cat = next((c for c in all_categories if c["name"] == category), None)

        if selected_cat:
            url = user_states[user_id]["url"]
            site_title = urllib.parse.urlparse(url).netloc
            site_desc = f"Описание сайта для {site_title}"
            final_link = f"/?uploadnew={url}|{site_title}|{site_desc}|{category}|{selected_cat['color']}"

            # Удалим предыдущее сообщение и сообщение пользователя
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=user_states[user_id]["message_id"])
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
            except Exception as e:
                print("Ошибка удаления сообщений:", e)

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"[Перейти к загрузке]({final_link})",
                parse_mode=ParseMode.MARKDOWN
            )


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не установлен в переменной окружения.")

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    # ВАЖНО: сначала проверяем стадии пользователя, потом общие текстовые
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()
