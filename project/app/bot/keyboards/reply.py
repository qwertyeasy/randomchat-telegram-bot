from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Найти чат")],
        [KeyboardButton(text="ℹ️ Справка"), KeyboardButton(text="⚙️ Настройки")],
    ],
    resize_keyboard=True,
)

chat_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⏭ Следующий"), KeyboardButton(text="⏹ Выйти")],
        [KeyboardButton(text="⚠️ Пожаловаться"), KeyboardButton(text="⚙️ Настройки чата")],
    ],
    resize_keyboard=True,
)

consent_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="✅ Принимаю")]],
    resize_keyboard=True,
)

gender_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Мужчина"), KeyboardButton(text="Женщина")],
    ],
    resize_keyboard=True,
)

search_filter_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")],
        [KeyboardButton(text="Не указано")],
        [KeyboardButton(text="📍 Поделиться геолокацией", request_location=True)],
    ],
    resize_keyboard=True,
)

chat_settings_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Поделиться контактом", request_contact=True)],
        [KeyboardButton(text="↩️ Вернуться к чату")],
    ],
    resize_keyboard=True,
)