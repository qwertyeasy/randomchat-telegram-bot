from aiogram import Router

from app.bot.handlers.chat import router as chat_router
from app.bot.handlers.content import router as content_router
from app.bot.handlers.help import router as help_router
from app.bot.handlers.queue import router as queue_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.text import router as text_router
from app.bot.handlers.stop import router as stop_router
from app.bot.handlers.chat_settings import router as chat_settings_router
from app.bot.handlers.settings import router as settings_router

router = Router(name=__name__)

router.include_routers(
    start_router,
    help_router,
    queue_router,
    chat_router,
    content_router,
    stop_router,
    chat_settings_router,
    settings_router,
    text_router,
)