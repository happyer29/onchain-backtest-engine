"""Public synthetic ML example stays deterministic and time-causal."""

from backtest.examples.ml_baseline import (
    FEATURE_NAMES,
    fit_logistic,
    make_observations,
    run_demo,
    split_by_time,
)


def test_example_has_one_model_and_four_finite_features() -> None:
    report = run_demo()
    assert report["model"] == "logistic_regression"
    assert report["feature_names"] == FEATURE_NAMES
    assert len(FEATURE_NAMES) == 4
    assert 0 <= report["accuracy"] <= 1
    assert 0 <= report["brier_score"] <= 1
    assert report["log_loss"] >= 0


def test_example_is_deterministic() -> None:
    assert run_demo() == run_demo()


def test_future_observations_do_not_change_prior_features() -> None:
    short = make_observations(100)
    long = make_observations(200)
    assert short == long[:100]


def test_split_purges_unavailable_labels_and_counts_unknown() -> None:
    train, test, counts = split_by_time(make_observations(100))
    assert train and test
    assert counts["purged_train"] > 0
    assert counts["unknown_train"] > 0
    assert counts["unknown_test"] > 0
    assert all(
        row.label_available_hour is not None and row.label_available_hour < test[0].hour
        for row in train
    )
    assert 0 <= fit_logistic(train).probability(test[0].features) <= 1
