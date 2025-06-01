import re
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "7459938900:AAGyV8yvIuRCrEOwLnpZKuPDB95ON_TdaQ4"
MINI_APP_URL = "https://sortik.app/?add=true"

URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправьте ссылку на видео, и я открою мини-приложение с этой ссылкой."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    urls = re.findall(URL_REGEX, message_text)

    if urls:
        shared_url = urls[0]
        encoded_url = urllib.parse.quote(shared_url, safe='')
        mini_app_link = f"{MINI_APP_URL}&url={encoded_url}"
        
        keyboard = [
            [InlineKeyboardButton("Открыть мини-приложение", web_app={"url": mini_app_link})]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Ссылка найдена: {shared_url}\nНажмите кнопку ниже:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
