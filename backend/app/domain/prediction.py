"""Provider prediction parsing (doc 01 §8, doc 07 §7).

* The provider text is preserved exactly.
* A percentage comes from the numeric field when it is a finite number in [0, 100].
* Only when that field is absent, a strictly validated leading ``"NN% ..."`` text is accepted.
* Anything else yields ``None`` plus an anomaly. Nothing is ever invented.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.domain.models import Prediction, PredictionSource

_NUMERIC_TEXT = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,2})?)\s*%?\s*$")
#: Only the documented shape ("73% Chance") or a bare "73%" is accepted as a text fallback.
_LEADING_PERCENT = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,2})?)\s*%\s*(?:chance|confirmation chance)?\s*$", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class ParsedPrediction:
    prediction: Prediction | None
    anomalies: tuple[str, ...] = ()


def _as_percentage(value: object) -> float | None:
    if isinstance(value, bool):  # bool is an int subclass: never a percentage
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str) and (match := _NUMERIC_TEXT.match(value)):
        number = float(match.group(1))
    else:
        return None
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        return None
    return number


def parse_prediction(
    *, provider: str, text: object = None, percentage: object = None
) -> ParsedPrediction:
    """``None`` means "not supplied"; absence of a prediction is normal and never an error."""
    anomalies: list[str] = []
    text_value = text if isinstance(text, str) and text.strip() else None
    if text is not None and text_value is None and not (isinstance(text, str)):
        anomalies.append("PREDICTION_TEXT_INVALID")

    value: float | None = None
    source: PredictionSource | None = None
    if percentage is not None:
        value = _as_percentage(percentage)
        if value is None:
            anomalies.append("PREDICTION_PERCENTAGE_INVALID")
        else:
            source = PredictionSource.FIELD
    elif text_value is not None and (match := _LEADING_PERCENT.match(text_value)):
        candidate = float(match.group(1))
        if 0.0 <= candidate <= 100.0:
            value, source = candidate, PredictionSource.TEXT
        else:
            anomalies.append("PREDICTION_TEXT_PERCENTAGE_OUT_OF_RANGE")

    if text_value is None and value is None:
        return ParsedPrediction(None, tuple(anomalies))
    return ParsedPrediction(
        Prediction(provider=provider, text=text_value, percentage=value, percentage_source=source),
        tuple(anomalies),
    )
