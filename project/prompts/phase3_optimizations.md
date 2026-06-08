# Промпт для Claude Code — Фаза 3: оптимизация NLP под нагрузку

## Контекст

NLP pipeline реализован (Phase 3). Нужно адаптировать его под нагрузку ~200 одновременных чатов
(~40 сообщений/сек в пике). Три конкретных правки — не больше.

Текущее состояние файлов:
- `app/services/nlp_processor.py` — NLPProcessor, singleton-модели, structural + sentiment + emotion
- `app/services/profile_calibrator.py` — ProfileCalibrator.calibrate(), decay weight, update_vector
- `app/bot/handlers/text.py` — relay_text, fire-and-forget через asyncio.create_task + _bg_tasks set
- `app/core/config.py` — Settings с nlp_enabled, nlp_use_translation, nlp_min_message_length, nlp_sentiment_model

---

## Правка 1 — сменить модель на rubert-tiny2

В `app/core/config.py` изменить дефолт:

```python
# было
nlp_sentiment_model: str = "blanchefort/rubert-base-cased-sentiment-rurewiews"

# стало
nlp_sentiment_model: str = "cointegrated/rubert-tiny2"
```

`rubert-tiny2` — дистиллированная версия rubert, в 6–8 раз быстрее (30–80ms vs 300–500ms на CPU),
весит ~60MB вместо ~450MB. Теряет ~5–10% качества — для калибровки профиля несущественно.

Модель поддерживает классификацию через pipeline("text-classification", ...) — API идентичен,
менять логику в nlp_processor.py не нужно. Только дефолт в конфиге.

---

## Правка 2 — семафор на параллельные NLP-задачи

В `app/bot/handlers/text.py` добавить module-level семафор и обернуть им _calibrate_profile.

Текущий код _calibrate_profile:
```python
async def _calibrate_profile(user_id: int, text: str) -> None:
    try:
        calibrator = ProfileCalibrator(session_maker)
        await calibrator.calibrate(user_id, text)
    except Exception:
        logger.exception("profile calibration failed for user %d", user_id)
```

Нужно стало:
```python
# module-level, создаётся один раз
_NLP_SEMAPHORE = asyncio.Semaphore(4)

async def _calibrate_profile(user_id: int, text: str) -> None:
    async with _NLP_SEMAPHORE:
        try:
            calibrator = ProfileCalibrator(session_maker)
            await calibrator.calibrate(user_id, text)
        except Exception:
            logger.exception("profile calibration failed for user %d", user_id)
```

Семафор(4) означает: не более 4 одновременных torch-инференсов. Остальные задачи ждут в очереди —
пользователи не чувствуют задержки (fire-and-forget). Предотвращает взрывной рост потребления памяти.

Значение 4 вынести в конфиг:
```python
# app/core/config.py
nlp_max_concurrent: int = 4
```

И использовать в хендлере:
```python
_NLP_SEMAPHORE = asyncio.Semaphore(settings.nlp_max_concurrent)
```

Важно: семафор создаётся на module level при импорте модуля, не внутри функции.

---

## Правка 3 — обрабатывать каждое N-е сообщение

В `app/bot/handlers/text.py` в relay_text перед созданием task добавить проверку msg_count.

Нужно читать `user.msg_count` из БД и пропускать NLP если `msg_count % nlp_process_every != 0`.

Добавить в конфиг:
```python
# app/core/config.py
nlp_process_every: int = 3  # обрабатывать каждое 3-е сообщение
```

В хендлере — читать msg_count асинхронно из уже открытой db-сессии (она передаётся в хендлер
через middleware и доступна как параметр `db: AsyncSession`):

```python
# app/bot/handlers/text.py — внутри relay_text, после service.relay(...)

if text and settings.nlp_enabled:
    from app.db.repositories.users import UserRepository
    user_repo = UserRepository(db)
    user = await user_repo.get(message.from_user.id)
    should_process = (
        user is not None and
        user.msg_count % settings.nlp_process_every == 0
    )
    if should_process:
        task = asyncio.create_task(_calibrate_profile(message.from_user.id, text))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
```

Импорт UserRepository перенести наверх файла (не оставлять внутри функции).

---

## Итог трёх правок

После изменений при нагрузке 200 чатов (~40 msg/sec):
- Модель rubert-tiny2: 30–80ms вместо 300–500ms
- Каждое 3-е сообщение: ~13 NLP-задач/сек вместо 40
- Семафор(4): не более 4 параллельных инференсов, остальные ждут в очереди

Итоговая нагрузка: 13 задач/сек × 50ms = ~0.65 CPU-секунды/сек → комфортно на 1–2 ядрах CPU.

---

## Что НЕ менять

- Логику ProfileCalibrator.calibrate() и decay weight — не трогать
- Структуру NLPProcessor — не трогать
- Порядок роутеров в bot/router.py — не трогать
- Любые файлы кроме: app/core/config.py, app/bot/handlers/text.py

После реализации:
1. `python -m py_compile app/core/config.py app/bot/handlers/text.py`
2. Показать финальный diff изменённых файлов
