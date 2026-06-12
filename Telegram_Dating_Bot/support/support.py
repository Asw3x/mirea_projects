import json
import logging
from pathlib import Path
from typing import Iterable, List, Union

from telegram import Message, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Замените на ваш токен от BotFather
API_TOKEN = '8493898902:AAGpC8jof-Nj2envdTEcpAFzng6NOrtjSUg'
# Замените на ID чата модераторов (можно получить, например, через /start в нужном чату)
MODERATORS_CHAT_ID = -4858042954

# Включаем логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).with_name("support_links.json")
MAX_LINKS_CACHED = 2000


def _load_message_links() -> dict[int, int]:
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as fh:
            raw_data = json.load(fh)
            return {int(k): int(v) for k, v in raw_data.items()}
    except Exception as exc:
        logger.warning("Failed to load stored message links: %s", exc)
        return {}


def _persist_message_links() -> None:
    try:
        with STATE_FILE.open("w", encoding="utf-8") as fh:
            json.dump(message_links, fh)
    except Exception as exc:
        logger.error("Failed to persist message links: %s", exc)


def _trim_message_links() -> None:
    overflow = len(message_links) - MAX_LINKS_CACHED
    if overflow <= 0:
        return
    for old_key in list(message_links.keys())[:overflow]:
        message_links.pop(old_key, None)


def _remember_forwarded_messages(
    forwarded: Union[Message, List[Message]],
    user_chat_id: int,
) -> None:
    forwarded_messages: Iterable[Message]
    if isinstance(forwarded, list):
        forwarded_messages = forwarded
    else:
        forwarded_messages = (forwarded,)

    for msg in forwarded_messages:
        message_links[msg.message_id] = user_chat_id

    _trim_message_links()
    _persist_message_links()

# Словарь для связи сообщений: {message_id в чате модераторов: chat_id пользователя}
message_links = _load_message_links()

async def forward_to_moderators(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пересылает сообщение пользователя в чат модераторов"""
    try:
        user_id = update.effective_user.id
        user_chat_id = update.effective_chat.id
        
        # Пересылаем сообщение в чат модераторов
        forwarded_msg = await update.message.forward(MODERATORS_CHAT_ID)
        _remember_forwarded_messages(forwarded_msg, user_chat_id)
        
        # Сохраняем связь между сообщениями
        # Отправляем подтверждение пользователю
        await update.message.reply_text("✅ Ваше сообщение отправлено модераторам. Ожидайте ответа.")
        
        logger.info(f"Сообщение от пользователя {user_id} переслано в чат модераторов")
        
    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения: {e}")
        await update.message.reply_text("❌ Произошла ошибка при отправке сообщения.")

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends hint when user issues /start."""
    await update.message.reply_text(
        "Пиши своё сообщение сюда, оно будет отправлено модераторам)"
    )


async def handle_moderator_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответы модераторов и пересылает пользователям"""
    # Проверяем, что сообщение из чата модераторов и является ответом
    if (update.effective_chat.id == MODERATORS_CHAT_ID and 
        update.message.reply_to_message):
        
        try:
            # Получаем ID оригинального сообщения, на которое ответили
            original_msg_id = update.message.reply_to_message.message_id
            
            # Ищем chat_id пользователя по ID сообщения
            user_chat_id = message_links.get(original_msg_id)
            
            if user_chat_id:
                # Отправляем ответ пользователю
                if update.message.text:
                    await context.bot.send_message(
                        chat_id=user_chat_id,
                        text=f"📨 Ответ от модераторов:\n{update.message.text}"
                    )
                elif update.message.caption:
                    # Если есть медиа с подписью
                    if update.message.photo:
                        await context.bot.send_photo(
                            chat_id=user_chat_id,
                            photo=update.message.photo[-1].file_id,
                            caption=f"📨 Ответ от модераторов:\n{update.message.caption}"
                        )
                    elif update.message.video:
                        await context.bot.send_video(
                            chat_id=user_chat_id,
                            video=update.message.video.file_id,
                            caption=f"📨 Ответ от модераторов:\n{update.message.caption}"
                        )
                    elif update.message.document:
                        await context.bot.send_document(
                            chat_id=user_chat_id,
                            document=update.message.document.file_id,
                            caption=f"📨 Ответ от модераторов:\n{update.message.caption}"
                        )
                else:
                    # Пересылаем медиа без текста
                    await update.message.forward(user_chat_id)
                
                logger.info(f"Ответ модератора отправлен пользователю {user_chat_id}")
                message_links.pop(original_msg_id, None)
                _persist_message_links()
                
            else:
                await update.message.reply_text("⚠ Не удалось найти пользователя для этого сообщения.")
                
        except Exception as e:
            logger.error(f"Ошибка при отправке ответа пользователю: {e}")
            await update.message.reply_text("❌ Ошибка при отправке ответа пользователю.")

def main():
    """Запуск бота"""
    # Создаем Application
    application = Application.builder().token(API_TOKEN).build()
    
    application.add_handler(CommandHandler("start", handle_start))
    # Обработчик для сообщений от пользователей (пересылка модераторам)
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            forward_to_moderators
        )
    )
    
    # Обработчик для ответов модераторов
    application.add_handler(
        MessageHandler(
            filters.Chat([MODERATORS_CHAT_ID]) & filters.REPLY,
            handle_moderator_reply
        )
    )
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
