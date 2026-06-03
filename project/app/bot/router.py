from aiogram import Router

from app.bot.handlers.common import router as common_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.queue import router as queue_router
from app.bot.handlers.chat import router as chat_router

router = Router()
router.include_router(start_router)
router.include_router(queue_router)
router.include_router(chat_router)
router.include_router(common_router)