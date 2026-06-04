from aiogram import F, Router
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import chat_menu_kb, chat_settings_kb

router = Router()


@router.message(F.text == "⚙️ Настройки чата")
async def open_chat_settings(message: Message) -> None:
    await message.answer(
        "Настройки доступа:\nЕсли хотите, можете поделиться контактом.",
        reply_markup=chat_settings_kb,
    )


@router.message(F.text == "↩️ Вернуться к чату")
async def back_to_chat(message: Message) -> None:
    await message.answer(
        "Возвращаемся к чату.",
        reply_markup=chat_menu_kb,
    )


@router.message(F.contact)
async def share_contact(message: Message, redis: Redis, db: AsyncSession) -> None:
    await message.answer(
        "Контакт получен.",
        reply_markup=chat_menu_kb,
    )