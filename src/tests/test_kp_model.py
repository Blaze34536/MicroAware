from datetime import datetime, timedelta, timezone

import numpy as np

from microaware.forecast import kp_model


def synthetic(n=3 * 2920, seed=0):
    rng = np.random.default_rng(seed)
    times = np.datetime64("2021-01-01T00:00:00") + np.arange(n) * np.timedelta64(3, "h")
    kp = np.clip(2 + np.cumsum(rng.normal(0, 0.3, n)) % 5 + rng.normal(0, 0.5, n), 0, 9)
    return times, kp


def test_train_evaluate_predict_roundtrip(tmp_path):
    times, kp = synthetic()
    path = tmp_path / "m.pkl"
    report = kp_model.train(times, kp, train_years=(2021, 2022), test_from=2023, path=path)
    assert set(report) == {1, 2}
    assert report[1]["n"] > 0 and "model_mae" in report[1] and "persist_mae" in report[1]

    models = kp_model.load(path)
    now = datetime(2026, 10, 24, 15, tzinfo=timezone.utc)
    out = kp_model.predict([2, 3, 1, 0.67, 4, 5, 3.33, 2], now, models)
    assert [t for t, _ in out] == [now + timedelta(hours=3), now + timedelta(hours=6)]
    assert all(0 <= k <= 9 for _, k in out)
