"""python -m microaware.forecast train | predict"""
import sys
import time
from datetime import timedelta

import numpy as np

from . import kp_data, kp_model
from .scheduler import plan_send, weather_level


def compare_noaa():
    """Score saved NOAA forecast snapshots against what SWPC has since observed."""
    observed = dict(kp_data.fetch_recent())
    noaa_err, persist_err = [], []
    for fetched, windows in kp_data.load_noaa_snapshots().items():
        before = [t for t in observed if t + timedelta(hours=3) <= fetched]
        if not before:
            continue
        last = observed[max(before)]
        for t, kp in windows:
            if t in observed and t > max(before):
                noaa_err.append(abs(kp - observed[t]))
                persist_err.append(abs(last - observed[t]))
    if not noaa_err:
        print("\nNOAA forecast: not compared yet (SWPC keeps no forecast archive; each "
              "`predict` run saves a snapshot to src/data/noaa_snapshots/ for later scoring).")
        return
    print(f"\nNOAA forecast vs SWPC observed, {len(noaa_err)} windows from saved snapshots: "
          f"NOAA MAE {np.mean(noaa_err):.3f}, persistence MAE {np.mean(persist_err):.3f}")


def cmd_train():
    t0 = time.time()
    report = kp_model.train()
    print(f"trained in {time.time() - t0:.1f}s, saved to {kp_model.MODEL_PATH}")
    print(f"train 1995-2022 ({report[1]['n_train']} rows), test 2023-now ({report[1]['n']} rows)\n")
    print("horizon | MAE model | MAE persist | quiet P/R model | quiet P/R persist | storm recall model/persist | quiet base rate")
    for h, r in report.items():
        m, p = r["model"], r["persist"]
        print(f"  +{3 * h} h  |   {r['model_mae']:.3f}   |    {r['persist_mae']:.3f}    |"
              f"   {m['precision']:.3f}/{m['recall']:.3f}   |    {p['precision']:.3f}/{p['recall']:.3f}    |"
              f"        {m['storm_recall']:.3f}/{p['storm_recall']:.3f}         |  {r['quiet_rate']:.3f}")
    try:
        compare_noaa()
    except Exception as e:  # network trouble shouldn't hide the main table
        print(f"\nNOAA forecast: not compared ({e})")


def cmd_predict():
    recent = kp_data.fetch_recent()
    now, kp_now = recent[-1]
    forecast = kp_model.predict([k for _, k in recent], now)
    print(f"latest observed window {now:%Y-%m-%d %H:%M} UTC: Kp {kp_now:.2f} ({weather_level(kp_now)})")
    try:
        noaa = dict(kp_data.fetch_noaa_forecast())
    except Exception:
        noaa = {}
    for t, kp in forecast:
        n = f"   NOAA {noaa[t]:.2f}" if t in noaa else ""
        print(f"  {t:%Y-%m-%d %H:%M} UTC  model Kp {kp:.2f} ({weather_level(kp)}){n}")
    plan = plan_send("routine", now + timedelta(hours=3), forecast)
    print(f"routine telemetry: send at {plan['send_at']:%H:%M} UTC ({plan['reason']})")


if __name__ == "__main__":
    cmds = {"train": cmd_train, "predict": cmd_predict}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit("usage: python -m microaware.forecast train|predict")
    cmds[sys.argv[1]]()
