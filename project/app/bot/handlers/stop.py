from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.services.chat import ChatService

router = Router()


@router.message(Command("stop"))
async def stop_command(message: Message, chat_service: ChatService) -> None:
    await chat_service.end_chat_for_user(message.from_user.id)


@router.callback_query(F.data == "stop")
async def stop_callback(callback: CallbackQuery, chat_service: ChatService) -> None:
    await chat_service.end_chat_for_user(callback.from_user.id)
    await callback.answer()