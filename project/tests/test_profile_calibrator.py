"""Unit-тест маппинга NLPResult → дельта-вектор.

Не грузит реальные модели: NLPResult собирается вручную.
Запуск: из корня проекта `python -m pytest tests/test_profile_calibrator.py`
(нужны установленные зависимости проекта — pgvector и т.д.).
"""

import pytest

from app.services.nlp_processor import NLPResult
from app.services.onboarding import DIMENSIONS
from app.services.profile_calibrator import ProfileCalibrator


def _idx(dim: str) -> int:
    return DIMENSIONS.index(dim)


def _result(**overrides) -> NLPResult:
    base = dict(
        sentiment_score=0.0,
        emotion_scores={"joy": 0.0, "sadness": 0.0, "anger": 0.0, "fear": 0.0},
        is_question=False,
        message_length=0,
        word_count=0,
        detected_topics=[],
    )
    base.update(overrides)
    return NLPResult(**base)


def test_delta_has_strict_dimension_length():
    delta = ProfileCalibrator._build_delta(_result())
    assert len(delta) == len(DIMENSIONS) == 12


def test_sentiment_maps_to_tone():
    delta = ProfileCalibrator._build_delta(_result(sentiment_score=0.8))
    assert delta[_idx("tone")] == pytest.approx(0.8 * 0.5)


def test_emotions_map_with_scaling():
    delta = ProfileCalibrator._build_delta(
        _result(emotion_scores={"joy": 0.5, "sadness": 0.2, "anger": 0.1, "fear": 0.4})
    )
    assert delta[_idx("joy")] == pytest.approx(0.5 * 0.6)
    assert delta[_idx("sadness")] == pytest.approx(0.2 * 0.6)
    assert delta[_idx("anger")] == pytest.approx(0.1 * 0.6)
    assert delta[_idx("fear")] == pytest.approx(0.4 * 0.6)


def test_question_sets_positive_curiosity():
    assert ProfileCalibrator._build_delta(_result(is_question=True))[_idx("curiosity")] == pytest.approx(0.4)


def test_statement_sets_negative_curiosity():
    assert ProfileCalibrator._build_delta(_result(is_question=False))[_idx("curiosity")] == pytest.approx(-0.05)


def test_tempo_and_expressiveness_scale_with_word_count():
    delta = ProfileCalibrator._build_delta(_result(word_count=25))
    assert delta[_idx("tempo")] == pytest.approx(min(25 / 20, 1.0) * 0.3 - 0.15)
    assert delta[_idx("expressiveness")] == pytest.approx(min(25 / 30, 1.0) * 0.25)


def test_depth_long_short_and_neutral():
    assert ProfileCalibrator._build_delta(_result(word_count=20))[_idx("depth")] == pytest.approx(0.1)
    assert ProfileCalibrator._build_delta(_result(word_count=3))[_idx("depth")] == pytest.approx(-0.1)
    assert ProfileCalibrator._build_delta(_result(word_count=10))[_idx("depth")] == pytest.approx(0.0)


def test_no_signal_dimensions_stay_zero():
    delta = ProfileCalibrator._build_delta(_result(sentiment_score=1.0, word_count=25, is_question=True))
    for dim in ("energy", "thinking", "humor"):
        assert delta[_idx(dim)] == 0.0


def test_clamp_bounds():
    assert ProfileCalibrator._clamp(5.0) == 1.0
    assert ProfileCalibrator._clamp(-5.0) == -1.0
    assert ProfileCalibrator._clamp(0.3) == 0.3
