"""Phase 3 — извлечение признаков из текста сообщения.

Privacy-first: текст обрабатывается в памяти, наружу отдаётся только
агрегированный NLPResult. Сам текст нигде не сохраняется.

Тяжёлые зависимости (transformers/torch) импортируются ЛЕНИВО внутри загрузчика —
модуль импортируется и без них (graceful degradation: только структурный анализ).

Модель — `cointegrated/rubert-tiny2-cedr-emotion-detection`: один мультиметочный
классификатор эмоций (нативный русский). Из его выдачи берём и emotion_scores,
и выводим sentiment_score — отдельная sentiment-модель и перевод больше не нужны.
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

# Module-level singleton — веса грузятся один раз на процесс.
_model = None
_model_loaded = False


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
            top_k=None,  # вернуть ВСЕ метки с вероятностями
            tokenizer=settings.nlp_model,
        )
        logger.info("NLP model loaded: %s", settings.nlp_model)
    except Exception:
        logger.exception("failed to load NLP model — structural-only mode")
        _model = None
    return _model


@dataclass
class NLPResult:
    sentiment_score: float            # [-1, 1]
    emotion_scores: dict[str, float]  # joy/sadness/anger/fear -> [0, 1]
    is_question: bool
    message_length: int               # символы
    word_count: int
    detected_topics: list[str]        # коды из TOPIC_KEYWORDS (⊂ INTEREST_CODES)


class NLPProcessor:
    @staticmethod
    def warmup() -> None:
        """Прогрев: грузит синглтон заранее (вызывается в executor при старте)."""
        _get_model()

    async def process(self, text: str) -> NLPResult:
        structural = self._structural(text)
        sentiment_score, emotion_scores = await self._run_model(text)
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

    # --- B+C. Emotion + Sentiment (единая модель, CPU-bound → executor) ---

    async def _run_model(self, text: str) -> tuple[float, dict[str, float]]:
        zero_emotions = {label: 0.0 for label in EMOTION_LABELS}

        model = _get_model()
        if model is None:
            return 0.0, zero_emotions

        try:
            loop = asyncio.get_event_loop()
            preds = await loop.run_in_executor(None, model, text)

            # top_k=None → список списков: [[{label, score}, ...]]
            flat = preds[0] if preds and isinstance(preds[0], list) else preds
            scored = {str(item["label"]).lower(): float(item["score"]) for item in flat}

            emotion_scores = {label: scored.get(label, 0.0) for label in EMOTION_LABELS}

            # Sentiment из эмоций: позитив = joy, негатив = sadness+anger+fear.
            joy = scored.get("joy", 0.0)
            neg = scored.get("sadness", 0.0) + scored.get("anger", 0.0) + scored.get("fear", 0.0)
            sentiment_score = max(-1.0, min(1.0, joy - neg * 0.5))

            return sentiment_score, emotion_scores
        except Exception:
            logger.exception("NLP model inference failed")
            return 0.0, zero_emotions
