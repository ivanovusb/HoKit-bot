import os
import httpx
import datetime
import pytz
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Твой Telegram ID для пересылки сообщений от пользователей

CATALOG_LINK = os.getenv("CATALOG_LINK")
YOUR_TELEGRAM_ID = os.getenv("YOUR_TELEGRAM_ID")# Мой ID чата
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("Не задана переменная окружения TOKEN")
    

# Приветственное сообщение
WELCOME_MESSAGE = (
    "Добро пожаловать в бот нашего магазина HoKit!\n"
    "Вы можете ознакомиться с каталогом, оформить заказ или оставить заявку на заказ.\n\n"
    "Выберите нужный пункт меню:"
)

# Состояния диалога
STATE_MAIN_MENU = 0
STATE_ORDERING = 1
STATE_CONTACT_INFO = 2
STATE_SUPPORT = 3
STATE_CUSTOM_ORDER = 4
STATE_WAITING_FOR_ORDER_FILE = 5

user_state = {}  # Хранит текущее состояние пользователя


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_state[user_id] = STATE_MAIN_MENU

    buttons = [
        [KeyboardButton("Посмотреть каталог")],
        [KeyboardButton("Оформить заказ")],
        [KeyboardButton("Связаться с оператором")],
        [KeyboardButton("Оставить заявку на заказ")],
        [KeyboardButton("Закончить работу с ботом")]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    await update.message.reply_text(WELCOME_MESSAGE, reply_markup=reply_markup)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_state.get(user_id) != STATE_WAITING_FOR_ORDER_FILE:
        return

    document = update.message.document

    if document.mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":  # .xlsx
        file = await document.get_file()
        await file.download_to_drive(custom_path=f"orders/order_{user_id}.xlsx")

        # Перешли файл тебе
        await context.bot.send_document(chat_id=YOUR_TELEGRAM_ID, document=document.file_id)
        await context.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=f"Новый заказ от @{update.effective_user.username}"
        )

        await update.message.reply_text("Форма получена! Спасибо за заказ.")
        user_state[user_id] = STATE_MAIN_MENU
    else:
        await update.message.reply_text("Пожалуйста, пришлите файл в формате .xlsx")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_state:
        await start(update, context)
        return

    current_state = user_state.get(user_id)

    if text == "Посмотреть каталог":
        await update.message.reply_text("Подождите, я подготовлю каталог в формате PDF...")
        
        catalog_url = f"{CATALOG_LINK}/export?format=pdf&gid=0"
        # Получаем текущее время по Москве
        msk_time = datetime.datetime.now(pytz.timezone("Europe/Moscow"))
        formatted_time = msk_time.strftime("%d.%m.%Y %H:%M (МСК)")
        logger.info(f"Запрашиваемый URL: {catalog_url}")
        
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(catalog_url)
            logger.info(f"Статус ответа: {r.status_code}")
            if r.status_code == 200 and 'application/pdf' in r.headers.get('Content-Type', ''):
                caption = f"Каталог (актуален на {formatted_time})"
                await update.message.reply_document(
                document=r.content,
                filename="Каталог.pdf",
                caption=caption
            )
            else:
                logger.warning(f"Ошибка при загрузке PDF: {r.status_code}, {r.headers.get('Content-Type')}")
                await update.message.reply_text("Не удалось загрузить каталог. Попробуйте позже.")
        user_state[user_id] = STATE_MAIN_MENU

    elif text == "Оформить заказ":
        await update.message.reply_text("Подождите, я подготовлю каталог в формате Excel...")
        # Формируем ссылку на экспорт Google Таблицы в XLSX
        catalog_xlsx_url = f"{CATALOG_LINK}/export?format=xlsx"

        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(catalog_xlsx_url)
            if r.status_code == 200 and 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' in r.headers.get('Content-Type', ''):
                await update.message.reply_document(document=r.content, filename="Заявка.xlsx")
                await update.message.reply_text("Заполните колонку «Количество», затем пришлите файл обратно.")
                user_state[user_id] = STATE_WAITING_FOR_ORDER_FILE
            else:
                 await update.message.reply_text("Не удалось загрузить каталог. Попробуйте позже.")
        user_state[user_id] = STATE_ORDERING

    elif text == "Связаться с оператором":
        await update.message.reply_text("Опишите вашу проблему, и мы свяжемся с вами.")
        user_state[user_id] = STATE_SUPPORT

    elif text == "Оставить заявку на заказ":
        await update.message.reply_text("Пришлите картинку и описание того, что вы хотите заказать.")
        user_state[user_id] = STATE_CUSTOM_ORDER

    elif text == "Закончить работу с ботом":
        await update.message.reply_text("Спасибо за использование! Возвращайтесь снова.")
        user_state[user_id] = STATE_MAIN_MENU

    elif current_state == STATE_ORDERING:
        context.user_data['order'] = text
        await update.message.reply_text("Введите ваше имя:")
        user_state[user_id] = STATE_CONTACT_INFO

    elif current_state == STATE_CONTACT_INFO:
        if 'name' not in context.user_data:
            context.user_data['name'] = text
            await update.message.reply_text("Введите ваш номер телефона:")
        else:
            context.user_data['phone'] = text
            order = context.user_data.get('order')
            name = context.user_data.get('name')
            phone = context.user_data.get('phone')

            await update.message.reply_text("Спасибо! Ваш заказ принят.")

            # Сохраняем или отправляем данные администратору
            message = f"Новый заказ:\nИмя: {name}\nТелефон: {phone}\nЗаказ: {order}"
            await context.bot.send_message(chat_id=YOUR_TELEGRAM_ID, text=message)

            user_state[user_id] = STATE_MAIN_MENU

    elif current_state == STATE_SUPPORT:
        problem = text
        message = f"[Обращение от @{update.effective_user.username}]:\n{problem}"
        await context.bot.send_message(chat_id=YOUR_TELEGRAM_ID, text=message)
        await update.message.reply_text("Спасибо! Мы получили ваше обращение и скоро ответим.")
        user_state[user_id] = STATE_MAIN_MENU

    elif current_state == STATE_CUSTOM_ORDER:
        if update.message.photo:
            photo = update.message.photo[-1].file_id
            caption = update.message.caption or "Без описания"
            await context.bot.send_photo(chat_id=YOUR_TELEGRAM_ID, photo=photo, caption=f"Новая заявка:\n{caption}")
            await update.message.reply_text("Ваша заявка принята!")
            user_state[user_id] = STATE_MAIN_MENU
        elif text:
            await update.message.reply_text("Пожалуйста, пришлите фото.")
        else:
            await update.message.reply_text("Неизвестный формат данных.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_state.get(user_id) != STATE_CUSTOM_ORDER:
        return

    await update.message.reply_text("Фото получено. Теперь добавьте текстовое описание.")


def main():
    app = ApplicationBuilder().token(TOKEN).build()  # Замени YOUR_BOT_TOKEN на реальный токен

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Бот запущен...")
    app.run_polling()


if __name__ == '__main__':
    main()
