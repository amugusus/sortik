import os
import re
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

BOT_TOKEN = os.getenv("BOT_TOKEN")
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video_url = "https://github.com/amugusus/sortik/raw/main/sortik.mp4"
    await update.message.reply_video(
        video=video_url,
        caption="Пришлите ссылки для сортировки)"
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)
    
    if not urls:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
        return

    shared_url = urls[0]
    await update.message.delete()
    if 'last_url_message' in context.user_data:
        await context.user_data['last_url_message'].delete()
        del context.user_data['last_url_message']
    context.user_data['current_url'] = shared_url

    default_categories = {
        "News": "blue",
        "Tech": "green",
        "Fun": "yellow",
        "Sport": "red",
        "Music": "purple"
    }
    custom_categories = context.user_data.get('custom_categories', {})
    
    buttons = []
    row = [InlineKeyboardButton("+", callback_data="add_category")]
    all_categories = {**custom_categories, **default_categories}
    sorted_categories = dict(sorted(all_categories.items(), key=lambda x: x[0]))
    idx = 1
    for category, color in sorted_categories.items():
        button_url = f"https://sortik.app/?uploadnew={urllib.parse.quote(shared_url, safe='')}|{urllib.parse.quote(category, safe='')}|{urllib.parse.quote(color, safe='')}"
        row.append(InlineKeyboardButton(category, web_app={"url": button_url}))
        if len(row) == 3 or (idx == len(all_categories) and row):
            buttons.append(row)
            row = []
        idx += 1

    reply_markup = InlineKeyboardMarkup(buttons)
    context.user_data['last_url_message'] = await update.message.reply_text(
        f"Ваша ссылка: {shared_url}\nВыберите категорию:",
        reply_markup=reply_markup
    )

async def category_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'last_url_message' in context.user_data:
        await context.user_data['last_url_message'].delete()
        del context.user_data['last_url_message']
    context.user_data['category_add_mode'] = True
    context.user_data['category_add_trigger'] = 'command'
    context.user_data['category_name_message'] = await update.message.reply_text("Назовите новую категорию:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('category_add_mode', False):
        new_category = update.message.text.strip()
        context.user_data['new_category'] = new_category
        await update.message.delete()
        if 'category_name_message' in context.user_data:
            await context.user_data['category_name_message'].delete()
            del context.user_data['category_name_message']
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
    
    if data[0] == "add_category":
        if 'last_url_message' in context.user_data:
            await context.user_data['last_url_message'].delete()
            del context.user_data['last_url_message']
        context.user_data['category_add_mode'] = True
        context.user_data['category_add_trigger'] = 'button'
        context.user_data['category_name_message'] = await query.message.reply_text("Назовите новую категорию:")
    elif data[0] == "color":
        color = data[1]
        new_category = context.user_data.get('new_category')
        shared_url = context.user_data.get('current_url')
        if new_category and shared_url:
            custom_categories = context.user_data.get('custom_categories', {})
            custom_categories[new_category] = color
            context.user_data['custom_categories'] = custom_categories
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
            buttons = []
            row = [InlineKeyboardButton("+", callback_data="add_category")]
            all_categories = {**custom_categories, **default_categories}
            sorted_categories = dict(sorted(all_categories.items(), key=lambda x: x[0]))
            idx = 1
            for category, color in sorted_categories.items():
                button_url = f"https://sortik.app/?uploadnew={urllib.parse.quote(shared_url, safe='')}|{urllib.parse.quote(category, safe='')}|{urllib.parse.quote(color, safe='')}"
                row.append(InlineKeyboardButton(category, web_app={"url": button_url}))
                if len(row) == 3 or (idx == len(all_categories) and row):
                    buttons.append(row)
                    row = []
                idx += 1

            reply_markup = InlineKeyboardMarkup(buttons)
            context.user_data['last_url_message'] = await query.message.reply_text(
                f"Ваша ссылка: {shared_url}\nВыберите категорию:",
                reply_markup=reply_markup
            )

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("categoryadd", category_add))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
