import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List

from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# =================== НАСТРОЙКИ ===================
BOT_TOKEN = "8809507486:AAExj1dHodnDp8TIZO2roxN1iyUbOds0Bq8"  # Замените на ваш токен

# Пороги спама
SPAM_LIMIT = 5  # Количество одинаковых сообщений
SPAM_WINDOW = 10  # Время в секундах, за которое считается спам
BAN_DURATION = 86400  # Длительность бана в секундах (24 часа)

LOG_FILE = "spam_bot.log"

# =================== НАСТРОЙКА ЛОГИРОВАНИЯ ===================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# =================== ХРАНИЛИЩЕ ДЛЯ СООБЩЕНИЙ ===================
user_messages: Dict[int, List[dict]] = defaultdict(list)
user_warnings: Dict[int, int] = defaultdict(int)


# =================== ФУНКЦИЯ ПРОВЕРКИ АДМИНИСТРАТОРА ===================
async def is_admin(update: Update, user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором канала."""
    if update.effective_chat is None:
        return False
    try:
        admins = await update.effective_chat.get_administrators()
        return any(admin.user.id == user_id for admin in admins)
    except Exception as e:
        logger.error(f"Ошибка проверки администратора: {e}")
        return False


# =================== ОСНОВНАЯ ЛОГИКА ОБРАБОТКИ СООБЩЕНИЙ ===================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает каждое сообщение в канале."""

    # Проверка на наличие текста
    if not update.effective_message or not update.effective_message.text:
        return

    message = update.effective_message
    user_id = message.from_user.id
    chat_id = message.chat_id
    text = message.text.strip()

    # Пропускаем сообщения без текста
    if not text:
        return

    # Пропускаем администраторов
    if await is_admin(update, user_id):
        logger.info(f"Администратор {user_id} пропущен.")
        return

    current_time = datetime.now()

    # Очищаем старые сообщения пользователя
    user_messages[user_id] = [
        msg for msg in user_messages[user_id]
        if (current_time - msg['time']).total_seconds() < SPAM_WINDOW
    ]

    # Добавляем новое сообщение
    user_messages[user_id].append({
        'text': text,
        'time': current_time,
        'chat_id': chat_id
    })

    # Считаем количество одинаковых сообщений в окне
    similar_messages = sum(
        1 for msg in user_messages[user_id]
        if msg['text'] == text
    )

    # Проверка на спам
    if similar_messages >= SPAM_LIMIT:
        logger.warning(f"СПАМ от {user_id} в чате {chat_id}: {text}")

        try:
            # Бан пользователя
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=current_time + timedelta(seconds=BAN_DURATION)
            )

            # Уведомление в чат
            username = message.from_user.username or 'без username'
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🚫 Пользователь @{username} "
                    f"забанен за спам на {BAN_DURATION // 3600} часов."
                )
            )

            logger.info(f"Пользователь {user_id} забанен за спам.")

            # Очищаем историю сообщений пользователя после бана
            user_messages[user_id] = []
            user_warnings[user_id] = 0

        except Exception as e:
            logger.error(f"Ошибка при бане пользователя {user_id}: {e}")
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Ошибка бана пользователя. Проверьте права бота."
            )


# =================== КОМАНДА /START ===================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение."""
    await update.message.reply_text(
        "🤖 Бот-антиспам активен!\n\n"
        f"Порог спама: {SPAM_LIMIT} повторений за {SPAM_WINDOW} сек.\n"
        f"Длительность бана: {BAN_DURATION // 3600} часов.\n\n"
        "Администраторы не проверяются."
    )


# =================== КОМАНДА /STATS ===================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика по пользователям."""
    if not await is_admin(update, update.effective_user.id):
        await update.message.reply_text("❌ Только для администраторов.")
        return

    total_users = len(user_messages)
    total_warnings = sum(user_warnings.values())

    await update.message.reply_text(
        f"📊 Статистика:\n\n"
        f"👤 Отслеживаемых пользователей: {total_users}\n"
        f"⚠️ Предупреждений выдано: {total_warnings}"
    )


# =================== КОМАНДА /UNBAN ===================
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разбан пользователя по ID."""
    if not await is_admin(update, update.effective_user.id):
        await update.message.reply_text("❌ Только для администраторов.")
        return

    if not context.args:
        await update.message.reply_text("Укажите ID пользователя: /unban 123456789")
        return

    try:
        user_id = int(context.args[0])
        chat_id = update.effective_chat.id

        await context.bot.unban_chat_member(chat_id, user_id)
        await update.message.reply_text(f"✅ Пользователь {user_id} разбанен.")

        # Очищаем историю
        if user_id in user_messages:
            user_messages[user_id] = []

        logger.info(f"Пользователь {user_id} разбанен администратором.")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


# =================== ЗАПУСК БОТА (ИСПРАВЛЕН ДЛЯ PYTHON 3.14) ===================
def main():
    """Запуск бота."""
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА":
        print("❌ ОШИБКА: Укажите ваш токен в переменной BOT_TOKEN!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Регистрация команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("unban", unban))

    # Обработка всех текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Бот-антиспам запущен!")
    logger.info("Бот-антиспам запущен.")

    # ИСПРАВЛЕННЫЙ ЗАПУСК ДЛЯ PYTHON 3.14
    try:
        asyncio.run(app.run_polling())
    except RuntimeError as e:
        if "event loop" in str(e).lower():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(app.run_polling())
        else:
            raise


if __name__ == "__main__":
    main()