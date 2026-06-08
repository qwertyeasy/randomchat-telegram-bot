from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.reply import main_menu_kb
from app.bot.states.flow import Onboarding, StartFlow
from app.services.onboarding import INTEREST_CODES, OnboardingService

router = Router()

Q1_TEXT = "1/5 · Как ты общаешься?"
Q2_TEXT = "2/5 · Твой стиль?"
Q3_TEXT = "3/5 · Настроение сейчас?"
Q4_TEXT = "4/5 · Что интересно? (можно выбрать несколько)"
Q5_TEXT = "5/5 · Кто ты?"

INTEREST_LABELS = {
    "music": "Музыка",
    "movies": "Кино",
    "sport": "Спорт",
    "games": "Игры",
    "books": "Книги",
    "travel": "Путешествия",
    "tech": "Технологии",
    "other": "Другое",
}


def _single_choice_kb(question: str, options: list[tuple[str, str]]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for answer, label in options:
        builder.button(text=label, callback_data=f"onb:{question}:{answer}")
    builder.adjust(1)
    return builder


def q1_kb():
    return _single_choice_kb(
        "q1",
        [("short", "Кратко и по делу"), ("long", "Люблю длинные диалоги")],
    ).as_markup()


def q2_kb():
    return _single_choice_kb(
        "q2",
        [("listen", "Больше слушаю"), ("tell", "Больше рассказываю")],
    ).as_markup()


def q3_kb():
    return _single_choice_kb(
        "q3",
        [("positive", "Позитивное"), ("neutral", "Нейтральное"), ("vent", "Хочу выговориться")],
    ).as_markup()


def q4_kb(selected: list[str]):
    builder = InlineKeyboardBuilder()
    for code in INTEREST_CODES:
        mark = "✅ " if code in selected else ""
        builder.button(text=f"{mark}{INTEREST_LABELS[code]}", callback_data=f"onb:q4:t:{code}")
    builder.adjust(2)
    builder.button(text="Готово ➡️", callback_data="onb:q4:done")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def q5_kb():
    return _single_choice_kb(
        "q5",
        [("intro", "Интроверт"), ("extra", "Экстраверт"), ("mid", "Что-то среднее")],
    ).as_markup()


async def start_onboarding(message: Message, state: FSMContext) -> None:
    await state.update_data(onb_answers=[], onb_tags=[])
    await state.set_state(Onboarding.q1)
    await message.answer(
        "Пара коротких вопросов, чтобы точнее подбирать собеседников.\n\n" + Q1_TEXT,
        reply_markup=q1_kb(),
    )


async def _add_answer(state: FSMContext, key: str) -> None:
    data = await state.get_data()
    answers = list(data.get("onb_answers", []))
    answers.append(key)
    await state.update_data(onb_answers=answers)


@router.callback_query(Onboarding.q1, F.data.startswith("onb:q1:"))
async def onb_q1(callback: CallbackQuery, state: FSMContext) -> None:
    await _add_answer(state, f"q1_{callback.data.split(':')[2]}")
    await state.set_state(Onboarding.q2)
    await callback.message.edit_text(Q2_TEXT, reply_markup=q2_kb())
    await callback.answer()


@router.callback_query(Onboarding.q2, F.data.startswith("onb:q2:"))
async def onb_q2(callback: CallbackQuery, state: FSMContext) -> None:
    await _add_answer(state, f"q2_{callback.data.split(':')[2]}")
    await state.set_state(Onboarding.q3)
    await callback.message.edit_text(Q3_TEXT, reply_markup=q3_kb())
    await callback.answer()


@router.callback_query(Onboarding.q3, F.data.startswith("onb:q3:"))
async def onb_q3(callback: CallbackQuery, state: FSMContext) -> None:
    await _add_answer(state, f"q3_{callback.data.split(':')[2]}")
    await state.set_state(Onboarding.q4)
    data = await state.get_data()
    await callback.message.edit_text(Q4_TEXT, reply_markup=q4_kb(data.get("onb_tags", [])))
    await callback.answer()


@router.callback_query(Onboarding.q4, F.data.startswith("onb:q4:t:"))
async def onb_q4_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.split(":")[3]
    data = await state.get_data()
    tags = list(data.get("onb_tags", []))
    if code in tags:
        tags.remove(code)
    else:
        tags.append(code)
    await state.update_data(onb_tags=tags)
    await callback.message.edit_reply_markup(reply_markup=q4_kb(tags))
    await callback.answer()


@router.callback_query(Onboarding.q4, F.data == "onb:q4:done")
async def onb_q4_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onboarding.q5)
    await callback.message.edit_text(Q5_TEXT, reply_markup=q5_kb())
    await callback.answer()


@router.callback_query(Onboarding.q5, F.data.startswith("onb:q5:"))
async def onb_q5(callback: CallbackQuery, state: FSMContext, db: AsyncSession) -> None:
    await _add_answer(state, f"q5_{callback.data.split(':')[2]}")

    data = await state.get_data()
    answer_keys = data.get("onb_answers", [])
    tags = data.get("onb_tags", [])

    service = OnboardingService(db)
    await service.complete(callback.from_user.id, answer_keys, tags)
    await db.commit()

    await state.set_state(StartFlow.idle)
    await callback.message.edit_text("Профиль готов — подбор стал точнее ✨")
    await callback.message.answer("Используй поиск чата.", reply_markup=main_menu_kb)
    await callback.answer()
