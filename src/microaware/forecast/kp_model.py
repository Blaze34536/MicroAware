"""Gradient-boosted Kp forecaster for the next two 3-hour windows, scored against persistence."""
import pickle
from datetime import timedelta, timezone

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .kp_data import DATA_DIR, load_history

MODEL_PATH = DATA_DIR / "kp_model.pkl"
LAGS = 8  # 24 h of history
HORIZONS = (1, 2)  # +3 h, +6 h
QUIET_KP = 4.0
STEP = np.timedelta64(3, "h")


def _features(lags, t_last):
    """lags: (n, 8) oldest..newest; t_last: datetime64 start of the newest window."""
    t_last = np.asarray(t_last, dtype="datetime64[s]")
    doy = (t_last - t_last.astype("datetime64[Y]")).astype("timedelta64[D]").astype(float)
    hour = (t_last - t_last.astype("datetime64[D]")).astype("timedelta64[h]").astype(float)
    a, b = 2 * np.pi * doy / 365.25, 2 * np.pi * hour / 24
    return np.column_stack([lags, np.sin(a), np.cos(a), np.sin(b), np.cos(b)])


def make_dataset(times, kp):
    """Rows where the 8 lags and both targets sit on an unbroken 3-hour grid."""
    n = len(kp) - LAGS - max(HORIZONS) + 1
    last = np.arange(LAGS - 1, LAGS - 1 + n)
    span = times[last + max(HORIZONS)] - times[last - LAGS + 1]
    ok = span == (LAGS - 1 + max(HORIZONS)) * STEP  # shortcut: drops any row touching a gap
    lags = sliding_window_view(kp, LAGS)[:n]
    X = _features(lags, times[last])
    Y = np.column_stack([kp[last + h] for h in HORIZONS])
    return X[ok], Y[ok], times[last][ok]


def _quiet_scores(pred, actual):
    pq, aq = pred < QUIET_KP, actual < QUIET_KP
    tp = np.sum(pq & aq)
    return {"precision": tp / max(pq.sum(), 1), "recall": tp / max(aq.sum(), 1),
            "storm_recall": np.sum(~pq & ~aq) / max((~aq).sum(), 1)}


def train(times=None, kp=None, train_years=(1995, 2022), test_from=2023, path=MODEL_PATH):
    """Fit one model per horizon, save, and return {horizon: metrics on the held-out years}."""
    if times is None:
        times, kp = load_history()
    X, Y, t = make_dataset(times, kp)
    year = t.astype("datetime64[Y]").astype(int) + 1970
    tr = (year >= train_years[0]) & (year <= train_years[1])
    te = year >= test_from
    models, report = {}, {}
    for j, h in enumerate(HORIZONS):
        m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=0)
        with threadpool_limits(1):  # OpenMP threads thrash on a shared box: 147 s -> ~1 s per fit
            m.fit(X[tr], Y[tr, j])
        models[h] = m
        pred, persist, actual = m.predict(X[te]), X[te, LAGS - 1], Y[te, j]
        report[h] = {
            "n": int(te.sum()), "n_train": int(tr.sum()),
            "model_mae": float(np.mean(np.abs(pred - actual))),
            "persist_mae": float(np.mean(np.abs(persist - actual))),
            "quiet_rate": float(np.mean(actual < QUIET_KP)),
            "model": _quiet_scores(pred, actual), "persist": _quiet_scores(persist, actual),
        }
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(models, f)
    return report


def load(path=MODEL_PATH):
    with open(path, "rb") as f:
        return pickle.load(f)


def predict(recent_kp_values, now, models=None):
    """recent_kp_values: last 8 Kp, oldest first; now: start time of the newest window (UTC).

    Returns [(now + 3 h, kp), (now + 6 h, kp)]."""
    models = models or load()
    lags = np.asarray(recent_kp_values, dtype=float)[-LAGS:]
    if len(lags) < LAGS:
        raise ValueError(f"need {LAGS} recent Kp values, got {len(lags)}")
    t = np.datetime64(now.astimezone(timezone.utc).replace(tzinfo=None), "s")
    x = _features(lags[None, :], t[None])
    return [(now + timedelta(hours=3 * h), float(np.clip(models[h].predict(x)[0], 0, 9)))
            for h in HORIZONS]
