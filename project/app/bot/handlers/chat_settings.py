from aiogram import F, Router
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import chat_menu_kb, chat_settings_kb, main_menu_kb
from app.services.session_manager import SessionManager

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
    sessions = SessionManager(redis, db)
    session_id = await sessions.get_session_id(message.from_user.id)
    if not session_id:
        await message.answer(
            "Поделиться контактом можно только во время чата.",
            reply_markup=main_menu_kb,
        )
        return

    partner_id = await sessions.get_partner(session_id, message.from_user.id)
    if not partner_id:
        await message.answer(
            "Не удалось определить собеседника.",
            reply_markup=chat_menu_kb,
        )
        return

    contact = message.contact
    await message.bot.send_message(partner_id, "Собеседник поделился контактом:")
    await message.bot.send_contact(
        chat_id=partner_id,
        phone_number=contact.phone_number,
        first_name=contact.first_name,
        last_name=contact.last_name,
    )
    await message.answer(
        "Контакт отправлен собеседнику.",
        reply_markup=chat_menu_kb,
    )
