"""Kp data sources: GFZ Potsdam history (cached), SWPC last 7 days, SWPC 3-day forecast."""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
HISTORY_PATH = DATA_DIR / "kp_history.txt"
SNAPSHOT_DIR = DATA_DIR / "noaa_snapshots"
GFZ_URL = "https://kp.gfz.de/app/files/Kp_ap_since_1932.txt"  # old kp.gfz-potsdam.de 301s here
SWPC_RECENT_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
SWPC_FORECAST_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
TIMEOUT = httpx.Timeout(300.0, connect=60.0)


def _get(url, tries=3):
    for i in range(tries):  # the network here drops connections now and then
        try:
            r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
            r.raise_for_status()
            return r
        except httpx.TransportError:
            if i == tries - 1:
                raise


def download_history(force=False):
    if force or not HISTORY_PATH.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(_get(GFZ_URL).text)
    return HISTORY_PATH


def parse_history(path=HISTORY_PATH):
    """Returns (times as datetime64[s] window starts in UTC, kp float array). Missing Kp (-1) dropped."""
    rows = np.loadtxt(path, comments="#", usecols=(0, 1, 2, 3, 7))
    rows = rows[rows[:, 4] >= 0]
    days = np.array([f"{int(y):04d}-{int(m):02d}-{int(d):02d}" for y, m, d in rows[:, :3]], dtype="datetime64[s]")
    times = days + (rows[:, 3] * 3600).astype("timedelta64[s]")
    return times, rows[:, 4]


def load_history(force_download=False):
    return parse_history(download_history(force_download))


def _ts(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def fetch_recent():
    """Last ~7 days of completed 3-hour windows: list of (window start UTC datetime, kp)."""
    return [(_ts(x["time_tag"]), float(x["Kp"])) for x in _get(SWPC_RECENT_URL).json()]


def fetch_noaa_forecast(save_snapshot=True):
    """NOAA's estimated + predicted Kp windows: list of (window start, kp).

    SWPC keeps no archive of this JSON, so each fetch is saved to let us score NOAA later."""
    raw = _get(SWPC_FORECAST_URL).json()
    out = [(_ts(x["time_tag"]), float(x["kp"])) for x in raw if x["observed"] != "observed"]
    if save_snapshot and out:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
        (SNAPSHOT_DIR / f"{stamp}.json").write_text(json.dumps([(t.isoformat(), k) for t, k in out]))
    return out


def load_noaa_snapshots():
    """{fetch_time: [(window start, kp), ...]} from saved snapshots."""
    out = {}
    for p in sorted(SNAPSHOT_DIR.glob("*.json")):
        fetched = datetime.strptime(p.stem, "%Y%m%dT%H%M").replace(tzinfo=timezone.utc)
        out[fetched] = [(datetime.fromisoformat(t), k) for t, k in json.loads(p.read_text())]
    return out
