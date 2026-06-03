from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Справка")
async def help_command(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/find(🔍 Найти чат)\nначать поиск по установленным фильтрам\n\n"
        "/next(⏭ Следующий)\nзавершить текущий диалог и автоматически начать поиск следующего собеседника\n\n"
        "/stop(⏹ Выйти)\nзавершить текущий диалог и выйти в главное меню\n\n"
        "/help(ℹ️ Справка)\nпоказать эту подсказку\n\n"
        "/complain(⚠️ Пожаловаться)\nотправить жалобу на собеседника (доступно только во время диалога)"
    )