import asyncio
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


async def send_telegram_message(
    bot_token: str,
    chat_id: str,
    message_text: str,
    retries: int = 2,
    message_url: str | None = None,
):
    if not bot_token or not chat_id:
        logger.error("Telegram configuration missing")
        return False, "Telegram configuration missing"

    reply_markup = None
    if message_url:
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("查看原文", url=message_url)]]
        )

    last_error = None
    for attempt in range(retries + 1):
        try:
            bot = Bot(token=bot_token)
            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
            return True, None
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Telegram send failed on attempt %s: %s", attempt + 1, exc)
            if attempt < retries:
                await asyncio.sleep(2**attempt)

    return False, last_error


async def send_telegram_photo(
    bot_token: str,
    chat_id: str,
    photo_url: str,
    caption: str | None = None,
    retries: int = 2,
    message_url: str | None = None,
):
    if not bot_token or not chat_id:
        logger.error("Telegram configuration missing")
        return False, "Telegram configuration missing"
    if not photo_url:
        return False, "Photo URL is missing"

    reply_markup = None
    if message_url:
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("查看原文", url=message_url)]]
        )

    last_error = None
    for attempt in range(retries + 1):
        try:
            bot = Bot(token=bot_token)
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            return True, None
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Telegram photo send failed on attempt %s: %s", attempt + 1, exc)
            if attempt < retries:
                await asyncio.sleep(2**attempt)

    return False, last_error
