# Offline ML baseline

**Language:** English · [Русский](ml-baseline.ru.md) · [简体中文](ml-baseline.zh-CN.md)

Run the self-contained example after installing the project:

```bash
python -m backtest.examples.ml_baseline
```

It creates synthetic hourly observations without reading a source, artifact,
credential, or local user data. Exactly one logistic-regression model uses four
features: event count, mean event value, and error share over the preceding six
hours, plus the current UTC hour. Each vector is built before the synthetic
outcome for that hour is generated.

The first 70% of observations form the candidate training period. Unknown
labels are counted separately. A training label available only at or after the
test-period start is purged, preventing the temporal split from using a future
outcome. Feature normalization is fitted on training rows only. The remaining
known labels form a fixed holdout; the command reports accuracy, Brier score,
log loss, and accounting counts. The seed makes the example reproducible.

The numbers are educational diagnostics on generated data, not measurements
from a chain or evidence of trading performance. The model is not serialized,
registered as a production model, or admitted to the strategy engine.
