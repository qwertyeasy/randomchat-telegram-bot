# Phase 5.1 — Калибровка MBTI через NLP

## Проблема

`mbti_scores: FLOAT[4]` вычисляется **один раз** в `OnboardingService.build_mbti()`
из 5 вопросов анкеты и больше **никогда не обновляется**.

`ProfileCalibrator` (Phase 3) обновляет `personality_vector` и `interest_tags`
после каждого N-го сообщения, но не трогает `mbti_scores`.

Результат: MBTI — мертвый снимок дня 1, хотя система знает о пользователе
всё больше с каждым сообщением.

## Цель

Расширить `ProfileCalibrator.calibrate()`, чтобы он также мягко калибровал
`mbti_scores` по тем же NLP-сигналам и с тем же decay-весом `1/sqrt(msg_count+1)`.

Никаких новых моделей, никаких миграций (поле уже есть).

## Маппинг NLP-сигналов → MBTI-оси

MBTI хранится как `[ei, sn, tf, jp]` (positive = E/S/T/J):

| Ось | Сигнал (NLPResult) | Логика |
|-----|-------------------|--------|
| E/I (`ei`) | `word_count` | Длинные сообщения → E (E-люди вербализуют больше) |
| S/N (`sn`) | `is_question`, `curiosity` | Вопросы → N (интуиты исследуют); N = отрицательный полюс |
| T/F (`tf`) | `emotion_scores` (joy+sadness+anger+fear) | Высокие эмоции → F (чувствующие экспрессивны); F = отрицательный полюс |
| J/P (`jp`) | `is_question` | Вопросы → P (воспринимающие гибкие); P = отрицательный полюс |

Формулы дельт (малые — MBTI меняется медленнее вектора):

```python
ei_delta = (min(word_count / 25.0, 1.0) - 0.4) * 0.25   # > 10 слов → E
sn_delta = -0.25 if is_question else 0.05                  # вопрос → N
tf_delta = -(joy + sadness + anger + fear) * 0.12          # эмоции → F
jp_delta = -0.20 if is_question else 0.04                  # вопрос → P
```

## Изменения в коде

### 1. `app/db/repositories/profiles.py`

Добавить метод `update_mbti` (рядом с `update_vector`):

```python
async def update_mbti(self, user_id: int, mbti_scores: list[float]) -> None:
    profile = await self.get(user_id)
    if profile is None:
        return
    profile.mbti_scores = mbti_scores
    profile.updated_at = datetime.utcnow()
```

### 2. `app/services/profile_calibrator.py`

Добавить статический метод `_build_mbti_delta`:

```python
@staticmethod
def _build_mbti_delta(result: NLPResult) -> list[float]:
    """NLPResult → дельта для [ei, sn, tf, jp].
    
    Оси: положительный полюс = E / S / T / J.
    Дельты малые — MBTI калибруется медленнее, чем personality_vector.
    """
    joy   = result.emotion_scores.get("joy",     0.0)
    sad   = result.emotion_scores.get("sadness", 0.0)
    anger = result.emotion_scores.get("anger",   0.0)
    fear  = result.emotion_scores.get("fear",    0.0)

    ei = (min(result.word_count / 25.0, 1.0) - 0.4) * 0.25
    sn = -0.25 if result.is_question else 0.05
    tf = -(joy + sad + anger + fear) * 0.12
    jp = -0.20 if result.is_question else 0.04

    return [ei, sn, tf, jp]
```

Расширить метод `calibrate` — добавить блок после `update_vector`:

```python
# Калибровка MBTI (если профиль прошёл онбординг и mbti_scores уже есть)
if profile.mbti_scores and len(profile.mbti_scores) == 4:
    mbti_delta = self._build_mbti_delta(result)
    old_mbti = list(profile.mbti_scores)
    new_mbti = [
        self._clamp(old_mbti[i] + weight * mbti_delta[i])
        for i in range(4)
    ]
    await profile_repo.update_mbti(user_id, new_mbti)
```

Этот блок должен идти **перед** `await session.commit()`.

### 3. `app/services/match_explainer.py`

Обновить функцию `_mbti` — добавить индикатор уверенности:

```python
def _mbti(scores: list[float] | None, msg_count: int = 0) -> str:
    """Возвращает MBTI-тип. Префикс '~' если данных мало (< 30 сообщений)."""
    if not scores or len(scores) < 4:
        return "?"
    pairs = [("E", "I"), ("S", "N"), ("T", "F"), ("J", "P")]
    result = "".join(pos if s >= 0 else neg for s, (pos, neg) in zip(scores, pairs))
    return f"~{result}" if msg_count < 30 else result
```

В методе `_build_card` передавать `msg_count` в `_mbti`:

```python
mbti1 = _mbti(p1.mbti_scores, p1.msg_count)
mbti2 = _mbti(p2.mbti_scores, p2.msg_count)
```

`UserProfile.msg_count` уже есть в модели.

## Инварианты (не нарушать)

- **Тексты сообщений нигде не хранятся.** `_build_mbti_delta` принимает
  `NLPResult` (уже агрегат), не текст.
- **Коммит делает `calibrate`** — не добавляй лишних `commit` внутри репозитория.
- **Нет новых миграций.** `mbti_scores` уже в схеме.

## Проверка

```bash
# Синтаксис
python -m py_compile app/db/repositories/profiles.py \
                      app/services/profile_calibrator.py \
                      app/services/match_explainer.py
```

## Обновить CLAUDE.md

В блоке `Фаза 3` добавить строчку:

```
Также калибрует `mbti_scores[4]` по тем же сигналам (decay идентичный);
  `~MBTI` в карточке если < 30 сообщений.
```

В блоке `Фаза 5` обновить упоминание MBTI:

```
MBTI в карточке живой (обновляется через NLP), `~` = мало данных.
```
