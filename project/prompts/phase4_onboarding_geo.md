# Промпт для Claude Code — шаг геолокации в онбординге

## Что нужно сделать

Добавить финальный шаг онбординга после Q5: пользователю предлагают поделиться геолокацией
или пропустить. Это повышает вероятность что пользователь вообще добавит гео — не все
заходят в настройки.

---

## 1. app/bot/states/flow.py — добавить состояние

```python
class Onboarding(StatesGroup):
    q1 = State()
    q2 = State()
    q3 = State()
    q4 = State()
    q5 = State()
    geo = State()   # ← добавить
```

---

## 2. app/bot/keyboards/reply.py — новая клавиатура

```python
geo_request_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📍 Поделиться геолокацией", request_location=True)],
        [KeyboardButton(text="Пропустить")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)
```

---

## 3. app/bot/handlers/onboarding.py — изменить финал Q5 и добавить два хендлера

### 3a. Изменить `onb_q5` — вместо перехода в idle вести на geo-шаг

```python
@router.callback_query(Onboarding.q5, F.data.startswith("onb:q5:"))
async def onb_q5(callback: CallbackQuery, state: FSMContext, db: AsyncSession) -> None:
    await _add_answer(state, f"q5_{callback.data.split(':')[2]}")

    data = await state.get_data()
    answer_keys = data.get("onb_answers", [])
    tags = data.get("onb_tags", [])

    service = OnboardingService(db)
    await service.complete(callback.from_user.id, answer_keys, tags)
    await db.commit()

    await state.set_state(Onboarding.geo)
    await callback.message.edit_text("Профиль готов — подбор стал точнее ✨")
    await callback.message.answer(
        "📍 Хочешь добавить геолокацию?\n"
        "Это поможет находить собеседников поблизости. Данные используются только для подбора.",
        reply_markup=geo_request_kb,
    )
    await callback.answer()
```

Добавить в импорты: `from app.bot.keyboards.reply import main_menu_kb, geo_request_kb`

### 3b. Хендлер для получения геолокации на шаге geo

```python
@router.message(Onboarding.geo, F.location)
async def onb_geo_received(message: Message, state: FSMContext, db: AsyncSession) -> None:
    from app.db.repositories.profiles import ProfileRepository
    profiles = ProfileRepository(db)
    await profiles.update_location(
        message.from_user.id,
        message.location.latitude,
        message.location.longitude,
    )
    # commit делает middleware
    await state.set_state(StartFlow.idle)
    await message.answer(
        "📍 Геолокация сохранена. Используй поиск чата.",
        reply_markup=main_menu_kb,
    )
```

### 3c. Хендлер для пропуска

```python
@router.message(Onboarding.geo, F.text == "Пропустить")
async def onb_geo_skip(message: Message, state: FSMContext) -> None:
    await state.set_state(StartFlow.idle)
    await message.answer(
        "Геолокацию можно добавить позже в настройках.\nИспользуй поиск чата.",
        reply_markup=main_menu_kb,
    )
```

---

## 4. app/bot/handlers/settings.py — добавить guard от срабатывания во время онбординга

Хендлер `save_location` в settings.py — catch-all без фильтра состояния. Он может
сработать на шаге `Onboarding.geo` раньше хендлера в onboarding.py если роутер settings
зарегистрирован первым. Добавить проверку в начало:

```python
@router.message(F.location)
async def save_location(message: Message, state: FSMContext, db: AsyncSession) -> None:
    if message.location is None:
        return

    current_state = await state.get_state()
    # Геолокация во время онбординга обрабатывается хендлером в onboarding.py
    if current_state is not None and "Onboarding" in current_state:
        return

    profiles = ProfileRepository(db)
    if await profiles.get(message.from_user.id) is None:
        await message.answer(
            "Сначала завершите настройку профиля через /start.",
            reply_markup=main_menu_kb,
        )
        return

    await profiles.update_location(
        message.from_user.id,
        message.location.latitude,
        message.location.longitude,
    )
    await message.answer(
        "📍 Геолокация сохранена. Теперь алгоритм учитывает близость собеседника.",
        reply_markup=main_menu_kb,
    )
```

---

## Что НЕ менять

- Вопросы Q1–Q5 и их хендлеры — не трогать
- `OnboardingService.complete()` — не трогать
- `search_filter_initial_kb` из предыдущего промпта — не трогать
- Хендлеры в `start.py` — не трогать

---

## Проверка

```bash
python -m py_compile app/bot/states/flow.py app/bot/handlers/onboarding.py app/bot/keyboards/reply.py app/bot/handlers/settings.py
```

Убедиться что в `Onboarding` есть состояние `geo` и что оба новых хендлера (`onb_geo_received`, `onb_geo_skip`) присутствуют в `onboarding.py`.
