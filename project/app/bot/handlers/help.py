from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message


router = Router()


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Справка")
async def help_command(message: Message) -> None:
    await message.answer(
        "Доступные кнопки:\n\n"
        "🔍 Найти чат — начать поиск собеседника\n"
        "⏭ Следующий — завершить диалог и искать нового\n"
        "⏹ Выйти — завершить диалог и вернуться в меню\n"
        "⚠️ Пожаловаться — отправить жалобу на собеседника\n"
        "⚙️ Настройки — изменить фильтр поиска\n"
        "⚙️ Настройки чата — открыть контакт и вернуться к чату\n"
        "ℹ️ Справка — показать это сообщение"
    )