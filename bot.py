import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from openai import OpenAI
import logging
from datetime import datetime
import time

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация OpenAI клиента
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# ID существующего ассистента
ASSISTANT_ID = os.getenv('ASSISTANT_ID')

# Словарь для хранения threads пользователей
user_threads = {}

# Словарь для отслеживания времени последнего сообщения пользователей
user_last_message = {}

# Ограничение частоты сообщений (в секундах)
MESSAGE_COOLDOWN = 1

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot")
    
    keyboard = [
        [InlineKeyboardButton("❓ Помощь", callback_data='help')],
        [InlineKeyboardButton("ℹ️ О боте", callback_data='about')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_message = (
        f"👋 Привет, {user.first_name}! Я ваш персональный AI-ассистент.\n\n"
        "🤖 Я могу помочь вам с различными задачами и ответить на ваши вопросы.\n"
        "💭 Просто напишите мне сообщение, и я постараюсь помочь!\n\n"
        "🔍 Используйте команду /help для получения дополнительной информации."
    )
    
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    user = update.effective_user
    logger.info(f"User {user.id} requested help")
    
    help_text = (
        "🔍 Как использовать бота:\n\n"
        "1. Просто напишите свой вопрос или задачу\n"
        "2. Бот обработает ваш запрос и ответит\n"
        "3. Можно вести диалог в контексте\n\n"
        "Доступные команды:\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать это сообщение\n"
        "/reset - Сбросить историю диалога"
    )
    await update.message.reply_text(help_text)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    user = query.from_user
    logger.info(f"User {user.id} pressed button: {query.data}")
    
    await query.answer()
    
    if query.data == 'help':
        help_text = (
            "🔍 Как использовать бота:\n\n"
            "1. Просто напишите свой вопрос или задачу\n"
            "2. Бот обработает ваш запрос и ответит\n"
            "3. Можно вести диалог в контексте"
        )
        await query.message.reply_text(help_text)
    
    elif query.data == 'about':
        about_text = (
            "ℹ️ О боте:\n\n"
            "Этот бот использует OpenAI API для обработки ваших запросов.\n"
            "Версия: 1.0\n"
            "По всем вопросам: @your_username"
        )
        await query.message.reply_text(about_text)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс истории диалога"""
    user = update.effective_user
    logger.info(f"User {user.id} reset their conversation")
    
    if user.id in user_threads:
        del user_threads[user.id]
    await update.message.reply_text("🔄 История диалога сброшена!")

def check_rate_limit(user_id: int) -> bool:
    """Проверка ограничения частоты сообщений"""
    current_time = time.time()
    if user_id in user_last_message:
        time_passed = current_time - user_last_message[user_id]
        if time_passed < MESSAGE_COOLDOWN:
            return False
    user_last_message[user_id] = current_time
    return True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик входящих сообщений"""
    user = update.effective_user
    user_message = update.message.text

    # Проверка ограничения частоты сообщений
    if not check_rate_limit(user.id):
        await update.message.reply_text(
            "⚠️ Пожалуйста, подождите немного перед отправкой следующего сообщения."
        )
        return

    logger.info(f"Received message from user {user.id}: {user_message[:50]}...")

    # Отправляем сообщение о том, что бот печатает
    await update.message.reply_chat_action("typing")
    
    try:
        # Создаем новый thread для пользователя, если его нет
        if user.id not in user_threads:
            thread = client.beta.threads.create()
            user_threads[user.id] = thread.id
            logger.info(f"Created new thread for user {user.id}")
        
        # Добавляем сообщение в thread
        message = client.beta.threads.messages.create(
            thread_id=user_threads[user.id],
            role="user",
            content=user_message
        )
        
        # Запускаем выполнение
        run = client.beta.threads.runs.create(
            thread_id=user_threads[user.id],
            assistant_id=ASSISTANT_ID
        )
        
        # Ждем завершения
        while True:
            run = client.beta.threads.runs.retrieve(
                thread_id=user_threads[user.id],
                run_id=run.id
            )
            if run.status == 'completed':
                break
            elif run.status == 'failed':
                logger.error(f"Run failed for user {user.id}")
                await update.message.reply_text(
                    "😔 Произошла ошибка при обработке запроса. Попробуйте еще раз."
                )
                return
            time.sleep(0.5)
        
        # Получаем ответ
        messages = client.beta.threads.messages.list(
            thread_id=user_threads[user.id]
        )
        
        # Отправляем последнее сообщение пользователю
        assistant_message = messages.data[0].content[0].text.value
        await update.message.reply_text(assistant_message)
        logger.info(f"Sent response to user {user.id}")
        
    except Exception as e:
        logger.error(f"Error processing message from user {user.id}: {str(e)}")
        await update.message.reply_text(
            "😔 Произошла ошибка при обработке вашего запроса. "
            "Попробуйте позже или используйте /reset для сброса диалога."
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "😔 Произошла внутренняя ошибка. Пожалуйста, попробуйте позже."
            )
    except Exception as e:
        logger.error(f"Error in error handler: {str(e)}")

def main():
    """Основная функция запуска бота"""
    try:
        # Создаем приложение
        application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()

        # Добавляем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("reset", reset))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Добавляем обработчик ошибок
        application.add_error_handler(error_handler)

        # Запускаем бота
        logger.info("Bot started")
        application.run_polling()
        
    except Exception as e:
        logger.critical(f"Critical error while starting bot: {str(e)}")
        raise

if __name__ == '__main__':
    main()
