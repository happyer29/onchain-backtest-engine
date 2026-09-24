"""Offline synthetic classification example with four causal features.

Run ``python -m backtest.examples.ml_baseline``. No source connection, local
artifact, strategy, or production model is used or modified.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from itertools import pairwise

FEATURE_NAMES = (
    "events_in_previous_6_hours",
    "mean_value_previous_6_hours",
    "error_share_previous_6_hours",
    "hour_of_day",
)
LABEL_DELAY_HOURS = 6
_FEATURE_COUNT = len(FEATURE_NAMES)


@dataclass(frozen=True, slots=True)
class Observation:
    hour: int
    features: tuple[float, float, float, float]
    label: int | None
    label_available_hour: int | None


@dataclass(frozen=True, slots=True)
class LogisticModel:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    bias: float

    def probability(self, features: tuple[float, float, float, float]) -> float:
        _check_features(features)
        score = self.bias + sum(
            weight * (value - mean) / scale
            for weight, value, mean, scale in zip(
                self.weights, features, self.means, self.scales, strict=True
            )
        )
        return _sigmoid(score)


def _sigmoid(value: float) -> float:
    if value >= 0:
        tail = math.exp(-value)
        return 1.0 / (1.0 + tail)
    tail = math.exp(value)
    return tail / (1.0 + tail)


def _check_features(features: tuple[float, float, float, float]) -> None:
    if len(features) != _FEATURE_COUNT or any(not math.isfinite(value) for value in features):
        raise ValueError("expected four finite features")


def make_observations(rows: int = 600, seed: int = 42) -> tuple[Observation, ...]:
    """Synthetic hourly events; each feature uses only earlier hours."""
    if not 50 <= rows <= 10_000 or not 0 <= seed <= 2**32 - 1:
        raise ValueError("rows or seed outside example bounds")
    rng = random.Random(seed)
    history: list[list[tuple[float, bool]]] = []
    observations: list[Observation] = []
    for hour in range(rows):
        prior = [event for group in history[max(0, hour - 6) : hour] for event in group]
        count = len(prior)
        mean_value = sum(value for value, _ in prior) / count if count else 0.0
        error_share = sum(error for _, error in prior) / count if count else 0.0
        features = (float(count), mean_value, error_share, float(hour % 24))
        chance = _sigmoid(
            -2.0 + 0.18 * count + 0.012 * mean_value + error_share - 0.025 * (hour % 24)
        )
        label = None if hour % 23 == 0 else int(rng.random() < chance)
        observations.append(
            Observation(
                hour,
                features,
                label,
                hour + LABEL_DELAY_HOURS if label is not None else None,
            )
        )
        history.append(
            [(rng.random() * 100.0, rng.random() < 0.15) for _ in range(rng.randrange(4))]
        )
    return tuple(observations)


def split_by_time(
    observations: tuple[Observation, ...],
) -> tuple[tuple[Observation, ...], tuple[Observation, ...], dict[str, int]]:
    if len(observations) < 10 or any(
        left.hour >= right.hour for left, right in pairwise(observations)
    ):
        raise ValueError("observations must be strictly time ordered")
    cut = int(len(observations) * 0.7)
    test_start = observations[cut].hour
    train: list[Observation] = []
    test: list[Observation] = []
    counts = {"purged_train": 0, "unknown_train": 0, "unknown_test": 0}
    for index, row in enumerate(observations):
        _check_features(row.features)
        if row.label is None:
            counts["unknown_train" if index < cut else "unknown_test"] += 1
            continue
        if row.label not in (0, 1):
            raise ValueError("labels must be binary or unknown")
        if index < cut:
            if row.label_available_hour is None or row.label_available_hour >= test_start:
                counts["purged_train"] += 1
            elif row.label_available_hour < row.hour:
                raise ValueError("label availability predates observation")
            else:
                train.append(row)
        else:
            test.append(row)
    return tuple(train), tuple(test), counts


def fit_logistic(train: tuple[Observation, ...]) -> LogisticModel:
    if {row.label for row in train} != {0, 1}:
        raise ValueError("training requires both known label classes")
    means = tuple(
        sum(row.features[index] for row in train) / len(train) for index in range(_FEATURE_COUNT)
    )
    scales = tuple(
        math.sqrt(sum((row.features[index] - means[index]) ** 2 for row in train) / len(train))
        or 1.0
        for index in range(_FEATURE_COUNT)
    )
    weights = [0.0] * _FEATURE_COUNT
    bias = 0.0
    for _ in range(400):
        gradient = [0.0] * _FEATURE_COUNT
        bias_gradient = 0.0
        for row in train:
            scaled = tuple(
                (value - mean) / scale
                for value, mean, scale in zip(row.features, means, scales, strict=True)
            )
            score = bias + sum(
                weight * value for weight, value in zip(weights, scaled, strict=True)
            )
            error = _sigmoid(score) - row.label  # type: ignore[operator]
            bias_gradient += error
            for index, value in enumerate(scaled):
                gradient[index] += error * value
        bias -= 0.15 * bias_gradient / len(train)
        for index in range(_FEATURE_COUNT):
            weights[index] -= 0.15 * (gradient[index] / len(train) + 0.01 * weights[index])
    return LogisticModel(means, scales, tuple(weights), bias)


def run_demo(rows: int = 600, seed: int = 42) -> dict[str, object]:
    train, test, counts = split_by_time(make_observations(rows, seed))
    model = fit_logistic(train)
    if not test:
        raise ValueError("test period has no known labels")
    probabilities = tuple(model.probability(row.features) for row in test)
    known_labels: list[int] = []
    for row in test:
        if row.label is None:
            raise ValueError("test period contains an unknown label")
        known_labels.append(row.label)
    labels = tuple(known_labels)
    epsilon = 1e-15
    return {
        "model": "logistic_regression",
        "feature_names": FEATURE_NAMES,
        "rows": rows,
        "train_rows": len(train),
        "test_rows": len(test),
        **counts,
        "accuracy": sum((p >= 0.5) == y for p, y in zip(probabilities, labels, strict=True))
        / len(test),
        "brier_score": sum((p - y) ** 2 for p, y in zip(probabilities, labels, strict=True))
        / len(test),
        "log_loss": sum(
            -(
                y * math.log(max(min(p, 1 - epsilon), epsilon))
                + (1 - y) * math.log(max(min(1 - p, 1 - epsilon), epsilon))
            )
            for p, y in zip(probabilities, labels, strict=True)
        )
        / len(test),
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2))
