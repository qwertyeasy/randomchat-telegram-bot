from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/find — найти собеседника\n"
        "/next — переключиться на следующего\n"
        "/stop — выйти из чата\n"
        "/help — показать эту подсказку\n\n"
        "Кнопки:\n"
        "🔍 Найти чат — начать поиск\n"
        "⏭ Следующий — сменить собеседника\n"
        "⏹ Выйти — завершить чат\n"
        "⚠️ Пожаловаться — отправить жалобу"
    )