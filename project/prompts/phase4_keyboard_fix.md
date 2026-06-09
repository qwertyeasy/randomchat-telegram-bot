# Промпт для Claude Code — разделение клавиатур фильтра поиска

## Проблема

В `app/bot/handlers/start.py` на шаге `StartFlow.search_filter` используется `search_filter_kb`,
которая содержит кнопку "📍 Поделиться геолокацией". Если пользователь нажмёт её первой:
- `F.location` хендлер из `settings.py` сработает в состоянии `StartFlow.search_filter`
- Профиль (`UserProfile`) ещё не создан → хендлер вернёт ошибку и выйдет
- FSM зависнет на шаге выбора фильтра — пользователь не сможет продолжить регистрацию

## Решение

Разделить на две клавиатуры:
- **`search_filter_initial_kb`** — только выбор фильтра (3 кнопки), без геолокации. Используется при первичной регистрации (`start.py`).
- **`search_filter_kb`** — существующая, с геолокацией. Используется в настройках (`settings.py`).

### 1. app/bot/keyboards/reply.py

Добавить новую клавиатуру (существующую `search_filter_kb` не трогать):

```python
search_filter_initial_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")],
        [KeyboardButton(text="Не указано")],
    ],
    resize_keyboard=True,
)
```

### 2. app/bot/handlers/start.py

Заменить импорт и использование клавиатуры:

```python
# Добавить в импорт:
from app.bot.keyboards.reply import ..., search_filter_initial_kb

# В хендлере gender() заменить:
await message.answer("Выбери фильтр поиска:", reply_markup=search_filter_kb)
# на:
await message.answer("Выбери фильтр поиска:", reply_markup=search_filter_initial_kb)
```

Больше ничего в start.py не менять.

### 3. app/bot/handlers/settings.py — защита F.location от невалидного состояния

Дополнительно обезопасить `save_location` — он уже проверяет наличие профиля, но стоит
явно сбрасывать состояние FSM если оно не то:

```python
@router.message(F.location)
async def save_location(message: Message, state: FSMContext, db: AsyncSession) -> None:
    if message.location is None:
        return

    # Если пользователь в процессе регистрации — геолокация пока недоступна
    current_state = await state.get_state()
    if current_state is not None and current_state.startswith("StartFlow"):
        await message.answer("Сначала завершите регистрацию.")
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

## Что НЕ менять

- Логику хендлеров `search_filter`, `filter_choice` — не трогать
- Существующую `search_filter_kb` — не трогать (используется в settings)
- Онбординг — не трогать

## Проверка

```bash
python -m py_compile app/bot/keyboards/reply.py app/bot/handlers/start.py app/bot/handlers/settings.py
```

Убедиться что в `start.py` нигде не осталось `search_filter_kb` (только `search_filter_initial_kb`).
