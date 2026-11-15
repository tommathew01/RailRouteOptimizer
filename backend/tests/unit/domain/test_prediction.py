from __future__ import annotations

import math

import pytest

from app.domain.models import PredictionSource
from app.domain.prediction import parse_prediction


@pytest.mark.parametrize(
    ("value", "expected"),
    [(73, 73.0), (73.5, 73.5), ("73", 73.0), ("73%", 73.0), (" 0 ", 0.0), (100, 100.0)],
)
def test_numeric_field_is_used(value: object, expected: float) -> None:
    result = parse_prediction(provider="RAILKIT", text="73% Chance", percentage=value)
    assert result.prediction is not None
    assert result.prediction.percentage == expected
    assert result.prediction.percentage_source is PredictionSource.FIELD
    assert result.prediction.text == "73% Chance"
    assert result.anomalies == ()


@pytest.mark.parametrize("value", [101, -1, 140.0, math.nan, math.inf, True, False, "abc", [], {}])
def test_invalid_field_becomes_null_with_anomaly_and_no_text_fallback(value: object) -> None:
    result = parse_prediction(provider="RAILKIT", text="73% Chance", percentage=value)
    assert result.prediction is not None
    assert result.prediction.percentage is None
    assert result.prediction.text == "73% Chance"  # text still preserved exactly
    assert "PREDICTION_PERCENTAGE_INVALID" in result.anomalies


def test_missing_prediction_is_normal() -> None:
    result = parse_prediction(provider="RAILKIT")
    assert result.prediction is None
    assert result.anomalies == ()


def test_text_is_preserved_exactly_including_whitespace_and_case() -> None:
    result = parse_prediction(provider="RAILKIT", text="  High Chance ")
    assert result.prediction is not None
    assert result.prediction.text == "  High Chance "
    assert result.prediction.percentage is None  # natural language is never converted


def test_strict_text_fallback_only_when_field_absent() -> None:
    result = parse_prediction(provider="RAILKIT", text="64% Chance")
    assert result.prediction is not None
    assert result.prediction.percentage == 64.0
    assert result.prediction.percentage_source is PredictionSource.TEXT


@pytest.mark.parametrize("text", ["Chance 64%", "about 64 percent", "64 % maybe? no", "Confirm"])
def test_ambiguous_text_never_yields_a_percentage(text: str) -> None:
    result = parse_prediction(provider="RAILKIT", text=text)
    assert result.prediction is not None
    assert result.prediction.percentage is None


def test_out_of_range_text_percentage_is_rejected() -> None:
    result = parse_prediction(provider="RAILKIT", text="140% Chance")
    assert result.prediction is not None
    assert result.prediction.percentage is None
    assert "PREDICTION_TEXT_PERCENTAGE_OUT_OF_RANGE" in result.anomalies


def test_non_string_text_is_an_anomaly() -> None:
    result = parse_prediction(provider="RAILKIT", text=73, percentage=None)
    assert result.prediction is None
    assert "PREDICTION_TEXT_INVALID" in result.anomalies


def test_percentage_without_text_is_kept() -> None:
    result = parse_prediction(provider="RAILKIT", percentage=55)
    assert result.prediction is not None
    assert result.prediction.text is None
    assert result.prediction.percentage == 55.0
