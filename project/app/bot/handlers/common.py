from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/find — найти чат\n"
        "/next — следующий собеседник\n"
        "/stop — выйти из чата\n"
        "/delete — удалить диалог вручную"
    )


@router.message(Command("delete"))
async def delete_cmd(message: Message) -> None:
    await message.answer("Удалите диалог с ботом вручную в интерфейсе Telegram.")