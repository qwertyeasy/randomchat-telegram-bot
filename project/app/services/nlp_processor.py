"""Phase 3 — извлечение признаков из текста сообщения.

Privacy-first: текст обрабатывается в памяти, наружу отдаётся только
агрегированный NLPResult. Сам текст нигде не сохраняется.

Тяжёлые зависимости (transformers/torch/argostranslate) импортируются ЛЕНИВО
внутри загрузчиков — модуль импортируется и без них (graceful degradation:
работает только структурный анализ).
"""

import asyncio
import logging
import re
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)

QUESTION_WORDS = {"как", "что", "почему", "зачем", "когда", "где", "кто", "сколько"}

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "music": ["музык", "песн", "альбом", "плейлист", "трек", "концерт", "группа", "исполнитель"],
    "movies": ["фильм", "сериал", "кино", "смотрел", "режиссёр", "актёр", "сцена"],
    "sport": ["спорт", "футбол", "трениров", "зал", "бег", "качал", "игра"],
    "games": ["игр", "геймер", "стрим", "мод", "персонаж", "уровень"],
    "books": ["книг", "читал", "автор", "роман", "глав", "страниц"],
    "travel": ["путешеств", "поездк", "город", "страна", "туризм", "билет", "отель"],
    "tech": ["програм", "код", "сервер", "питон", "разработк", "технолог", "алгоритм"],
}

EMOTION_LABELS = ("joy", "sadness", "anger", "fear")

_SENTIMENT_VALUE = {"POSITIVE": 1.0, "NEUTRAL": 0.0, "NEGATIVE": -1.0}

# Module-level singletons — веса грузятся один раз на процесс.
_sentiment_model = None
_sentiment_loaded = False
_emotion_model = None
_emotion_loaded = False


def _get_sentiment_model():
    global _sentiment_model, _sentiment_loaded
    if _sentiment_loaded:
        return _sentiment_model
    _sentiment_loaded = True

    if not settings.nlp_enabled:
        _sentiment_model = None
        return None

    try:
        from transformers import pipeline

        _sentiment_model = pipeline(
            "sentiment-analysis",
            model=settings.nlp_sentiment_model,
            tokenizer=settings.nlp_sentiment_model,
        )
        logger.info("sentiment model loaded: %s", settings.nlp_sentiment_model)
    except Exception:
        logger.exception("failed to load sentiment model — degrading to structural-only")
        _sentiment_model = None
    return _sentiment_model


def _get_emotion_model():
    global _emotion_model, _emotion_loaded
    if _emotion_loaded:
        return _emotion_model
    _emotion_loaded = True

    # Emotion-модель английская; без перевода её не используем (см. spec).
    if not settings.nlp_enabled or not settings.nlp_use_translation:
        _emotion_model = None
        return None

    try:
        from transformers import pipeline

        _emotion_model = pipeline(
            "text-classification",
            model="j-hartmann/emotion-english-distilroberta-base",
            top_k=None,
        )
        logger.info("emotion model loaded")
    except Exception:
        logger.exception("failed to load emotion model — emotions disabled")
        _emotion_model = None
    return _emotion_model


def _translate_ru_en(text: str) -> str | None:
    try:
        import argostranslate.translate

        return argostranslate.translate.translate(text, "ru", "en")
    except Exception:
        logger.exception("ru->en translation unavailable")
        return None


@dataclass
class NLPResult:
    sentiment_score: float           # [-1, 1]
    emotion_scores: dict[str, float]  # joy/sadness/anger/fear -> [0, 1]
    is_question: bool
    message_length: int              # символы
    word_count: int
    detected_topics: list[str]       # коды из TOPIC_KEYWORDS (⊂ INTEREST_CODES)


class NLPProcessor:
    @staticmethod
    def warmup() -> None:
        """Прогрев: грузит синглтоны заранее (вызывается в executor при старте)."""
        _get_sentiment_model()
        _get_emotion_model()

    async def process(self, text: str) -> NLPResult:
        structural = self._structural(text)
        sentiment_score = await self._run_sentiment(text)
        emotion_scores = await self._run_emotion(text)
        return NLPResult(
            sentiment_score=sentiment_score,
            emotion_scores=emotion_scores,
            **structural,
        )

    # --- A. Структурный анализ (детерминированный, без моделей) ---

    @staticmethod
    def _structural(text: str) -> dict:
        stripped = text.strip()
        lowered = stripped.lower()
        tokens = re.findall(r"\w+", lowered, flags=re.UNICODE)

        is_question = "?" in stripped or any(tok in QUESTION_WORDS for tok in tokens)
        detected_topics = [
            topic
            for topic, keywords in TOPIC_KEYWORDS.items()
            if any(kw in lowered for kw in keywords)
        ]

        return {
            "is_question": is_question,
            "message_length": len(text),
            "word_count": len(stripped.split()),
            "detected_topics": detected_topics,
        }

    # --- B. Sentiment (модель, CPU-bound → executor) ---

    async def _run_sentiment(self, text: str) -> float:
        model = _get_sentiment_model()
        if model is None:
            return 0.0
        try:
            loop = asyncio.get_event_loop()
            preds = await loop.run_in_executor(None, model, text)
            top = preds[0] if isinstance(preds, list) else preds
            if isinstance(top, list):  # некоторые пайплайны возвращают список списков
                top = top[0]
            value = _SENTIMENT_VALUE.get(str(top["label"]).upper(), 0.0)
            return value * float(top["score"])
        except Exception:
            logger.exception("sentiment inference failed")
            return 0.0

    # --- C. Emotion (англ. модель + опциональный перевод) ---

    async def _run_emotion(self, text: str) -> dict[str, float]:
        zero = {label: 0.0 for label in EMOTION_LABELS}

        if not settings.nlp_use_translation:
            return zero
        model = _get_emotion_model()
        if model is None:
            return zero

        loop = asyncio.get_event_loop()
        en_text = await loop.run_in_executor(None, _translate_ru_en, text)
        if not en_text:
            return zero

        try:
            preds = await loop.run_in_executor(None, model, en_text)
            flat = preds[0] if preds and isinstance(preds[0], list) else preds
            scored = {str(item["label"]).lower(): float(item["score"]) for item in flat}
            return {label: scored.get(label, 0.0) for label in EMOTION_LABELS}
        except Exception:
            logger.exception("emotion inference failed")
            return zero
