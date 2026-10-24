# Kp forecaster results

**Data:** GFZ Potsdam 3-hourly Kp (`Kp_ap_since_1932.txt`, last value 2026-10-23 21:00 UTC; recent months are preliminary).
**Split:** train on 1995–2022 (81,816 windows), test on 2023-01-01 to 2026-10-23 (11,134 windows). The test period is held out and recent, and it covers the solar cycle 25 maximum.
**Model:** one `HistGradientBoostingRegressor` per horizon. Features are the last 8 Kp values (24 h) plus sin/cos of the day of year and of the UT hour. Training takes about 3 s.
**Baseline:** persistence, meaning Kp in the next windows equals the latest observed Kp.

"Quiet" means Kp < 4. Quiet P/R is the precision and recall for predicting a quiet window. Storm recall is the share of non-quiet windows (Kp ≥ 4) that the forecaster flagged as non-quiet.

| horizon | MAE model | MAE persistence | quiet P / R model | quiet P / R persistence | storm recall model / persistence |
|---|---|---|---|---|---|
| +3 h | **0.638** | 0.669 | 0.926 / 0.989 | **0.952** / 0.952 | 0.360 / **0.608** |
| +6 h | **0.780** | 0.868 | 0.911 / 0.990 | **0.937** / 0.937 | 0.213 / **0.488** |

Quiet base rate in the test set: 0.891. Always predicting "quiet" would get precision 0.891 and recall 1.0.

**NOAA SWPC forecast: not compared.** SWPC publishes only its current 3-day forecast and keeps no archive of it. Each `predict` run now saves a snapshot to `src/data/noaa_snapshots/`, and `train` scores any snapshots that have matured, so a comparison becomes possible after the system has run for a day or more.

## Honest caveats
The model beats persistence on average error: about 5% better at +3 h and 10% better at +6 h. It does this by regressing toward the quiet mean, so it is worse than persistence at the thing that matters most here. It misses most storm onsets: it catches only 36% of Kp ≥ 4 windows at +3 h, against 61% for persistence. When it says "quiet", it is right 92.6% of the time, against 95.2% for persistence and 89.1% for always guessing quiet. That gap is small. Kp is a geomagnetic index measured near Earth. It stands in for space weather in this demo and is not a model of a deep-space radio link. The model has no solar-wind inputs (no ACE/DSCOVR data), so it cannot see a CME coming. NOAA's forecasters can, and they would very likely beat this model. Because critical and normal traffic never wait, a wrong "quiet" call only costs some extra erasure-coding overhead on routine telemetry. It never delays an alert.

## Pitch line
"A small gradient-boosted model trained on 28 years of Kp beats the 'nothing changes' baseline by 5 to 10% on error. It still misses most storm onsets, so we use it only to time routine telemetry, and critical alerts never wait for a forecast."
