# Промпт для Claude Code — смена модели NLP на rubert-tiny2-cedr

## Что изменилось в конфиге

В `app/core/config.py` поле `nlp_sentiment_model` переименовано в `nlp_model` и теперь равно:
```
nlp_model: str = "cointegrated/rubert-tiny2-cedr-emotion-detection"
```
Также добавлены: `nlp_max_concurrent: int = 4`, `nlp_process_every: int = 3`.

## Что нужно обновить в nlp_processor.py

Новая модель (`rubert-tiny2-cedr-emotion-detection`) — это мультиметочный классификатор эмоций.
Она возвращает вероятности по меткам: `joy, sadness, anger, fear, surprise, neutral` (строчные).
Это НЕ то же самое, что старая sentiment-модель с метками `POSITIVE/NEUTRAL/NEGATIVE`.

### Изменение 1 — убрать отдельные синглтоны sentiment/emotion, оставить один

Убрать:
```python
_sentiment_model = None
_sentiment_loaded = False
_emotion_model = None
_emotion_loaded = False
```

Заменить на один синглтон:
```python
_model = None
_model_loaded = False
```

Убрать функции `_get_sentiment_model()` и `_get_emotion_model()`.
Добавить одну:
```python
def _get_model():
    global _model, _model_loaded
    if _model_loaded:
        return _model
    _model_loaded = True

    if not settings.nlp_enabled:
        return None

    try:
        from transformers import pipeline
        _model = pipeline(
            "text-classification",
            model=settings.nlp_model,
            top_k=None,          # возвращает ВСЕ метки с вероятностями
            tokenizer=settings.nlp_model,
        )
        logger.info("NLP model loaded: %s", settings.nlp_model)
    except Exception:
        logger.exception("failed to load NLP model — structural-only mode")
        _model = None
    return _model
```

### Изменение 2 — обновить warmup

```python
@staticmethod
def warmup() -> None:
    _get_model()
```

### Изменение 3 — обновить метод process()

Убрать вызовы `_run_sentiment` и `_run_emotion`. Заменить на один вызов `_run_model`:

```python
async def process(self, text: str) -> NLPResult:
    structural = self._structural(text)
    sentiment_score, emotion_scores = await self._run_model(text)
    return NLPResult(
        sentiment_score=sentiment_score,
        emotion_scores=emotion_scores,
        **structural,
    )
```

### Изменение 4 — новый метод _run_model()

Убрать методы `_run_sentiment` и `_run_emotion`. Добавить:

```python
async def _run_model(self, text: str) -> tuple[float, dict[str, float]]:
    """Единый проход: emotion + sentiment из rubert-tiny2-cedr."""
    zero_emotions = {label: 0.0 for label in EMOTION_LABELS}

    model = _get_model()
    if model is None:
        return 0.0, zero_emotions

    try:
        loop = asyncio.get_event_loop()
        preds = await loop.run_in_executor(None, model, text)

        # pipeline с top_k=None возвращает список списков: [[{label, score}, ...]]
        flat = preds[0] if preds and isinstance(preds[0], list) else preds
        scored = {item["label"].lower(): float(item["score"]) for item in flat}

        # Emotion scores — напрямую из модели
        emotion_scores = {label: scored.get(label, 0.0) for label in EMOTION_LABELS}

        # Sentiment выводим из эмоций: позитив = joy, негатив = sadness+anger+fear
        joy = scored.get("joy", 0.0)
        neg = scored.get("sadness", 0.0) + scored.get("anger", 0.0) + scored.get("fear", 0.0)
        sentiment_score = max(-1.0, min(1.0, joy - neg * 0.5))

        return sentiment_score, emotion_scores

    except Exception:
        logger.exception("NLP model inference failed")
        return 0.0, zero_emotions
```

### Изменение 5 — убрать _translate_ru_en и весь код argostranslate

Функция `_translate_ru_en` больше не нужна: новая модель нативно русская.
Убрать функцию целиком. Убрать импорт argostranslate (его и не было в requirements, но убрать
любые ссылки в коде).

`nlp_use_translation` в конфиге оставить (флаг может понадобиться для будущих English-моделей),
но логику перевода из nlp_processor убрать.

---

## Что НЕ менять

- `NLPResult` dataclass — не трогать, поля те же
- `_structural()` — не трогать
- `TOPIC_KEYWORDS`, `QUESTION_WORDS`, `EMOTION_LABELS` — не трогать
- `profile_calibrator.py` — не трогать вообще
- `text.py` — не трогать

---

## Проверка

```bash
python -m py_compile app/services/nlp_processor.py app/core/config.py
```

Показать финальный nlp_processor.py целиком.
