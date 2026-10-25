# MicroAware

MicroAware listens to a habitat's life-support fan, catches faults by ear, explains them out loud, and gets the alert to Earth intact through a solar storm.

- **Hear it:** an autoencoder learns what the healthy fan sounds like. Whatever it can't explain is the fault, shown live as the "cancelled" spectrogram. A small offline speech detector (Silero VAD) pauses alerting while people talk near the mic.
- **Name and explain it:** a small classifier names known faults. Gemini (or a canned fallback) explains each alert in one sentence plus 3 checks. ElevenLabs (or the browser's voice) speaks it, and a voice agent answers crew questions from live data.
- **Send it home:** Storm Shield sends each alert from one ESP32 to another over ESP-NOW. It uses erasure coding and interleaving, and the protection adapts to live NOAA space weather or a manual "solar flare". A third ESP32 plays the Sun.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo apt install libportaudio2        # or keep the no-sudo copy in .venv/portaudio that run.sh points to
cp .env.example .env                  # optional keys; everything has a fallback
cd src && ../.venv/bin/python -m microaware.forecast train   # downloads Kp history (~16 MB), trains in seconds
```

## Run

```bash
cd src
./run.sh                                     # mic + radio if the boards are plugged in, else a simulated link
MICROAWARE_SOURCE=synth ./run.sh             # simulated fan, no hardware
MICROAWARE_RECORD=data/run.wav ./run.sh      # record everything the mic hears (rehearsal)
MICROAWARE_SOURCE=file:data/run.wav ./run.sh # replay a rehearsal through the same pipeline
MICROAWARE_LINK=sim ./run.sh                 # force the simulated link
```

On Windows, double-click `src\run.bat` (or run it from a terminal). The first run sets everything up: it creates `.venv`, installs `requirements.txt`, copies `.env.example` to `.env`, and trains the Kp forecaster. Later runs start straight away and only reinstall when `requirements.txt` changes. It needs Python 3.10 or newer from python.org or `winget install Python.Python.3.12`. Set options first, e.g. `set MICROAWARE_SOURCE=synth` then `run.bat`. The sounddevice wheel bundles PortAudio, and ESP32s are found on their COM ports automatically.

- Habitat dashboard: http://localhost:8000
- Earth ground station: http://localhost:8000/earth (open it on a second screen)

Tests: `cd src && ../.venv/bin/pytest -q`

## First-time calibration (at the venue)

1. **Baseline:** start the fan, open **Setup**, and choose **Record normal sound** (90 s). Keep the room as it will be during judging, chatter included.
2. **Fault names (optional):** pick a fault, make it on the fan, and choose **Record 15 s clip**. Do this 2–3 times per fault, then **Train fault names**.
3. **Radio:** flash the boards (see `firmware/README.md`). Put the Sun next to Earth, and keep Habitat a few meters away or in a foil-lined box. Then run `../.venv/bin/python -m microaware.link.calibrate`, which needs under 1% loss with the Sun off and 40% or more at full duty.
4. **Voice agent:** follow `docs/voice-agent.md` once.

## Demo script (about 3 min)

1. The fan runs and the dashboard reads **Nominal**: "This is a life-support fan in a Mars habitat module." Turn on spoken alerts.
2. Stick a tape flag on a blade. The cancelled spectrogram lights up, the alert fires, and the voice explains it.
3. Choose **Start talking** and ask "Is it getting worse?" The agent answers from the score history.
4. On the Earth screen, the alert has already arrived in calm mode, and both copies are intact.
5. Choose **Solar flare (30% loss)**, then **Send latest alert again**. The unprotected copy arrives striped with black, and the Storm Shield copy arrives intact with the rebuilt-packet count shown.
6. Choose **Extreme flare (70% loss)** and send again: "Here's where it breaks."
7. Close: "Same message, same storm. The difference is deciding how much protection to spend."

## Measured numbers (simulated link, random 200–400 ms Sun bursts)

| Flare (loss) | Mode | Storm Shield delivered | Unprotected delivered |
|---|---|---|---|
| 0% | calm (4 of 5) | 20/20 | 20/20 |
| 5% | active (4 of 6) | 199/200 | – |
| 20–40% | storm (4 of 12) | 199–200/200 | 0/200 |
| 50% | storm | 170/200 | 0/200 |
| 60% | storm | 52/200 | 0/200 |

The Kp forecaster's honest results are in `src/microaware/forecast/RESULTS.md`.

## If something breaks at the venue

| Problem | Do this |
|---|---|
| Footsteps or bumps cause alerts | Re-record the baseline with the room noise in it, or raise the threshold slider |
| Alerts stay paused because people keep talking | Pause in your sentences for a second, or untick **Pause alerts while people talk** in Setup |
| Fan fault too subtle | Use **Simulate a fault** in Setup, or replay a rehearsal with `MICROAWARE_SOURCE=file:` |
| No Wi-Fi | Explanations fall back to canned text, and spoken alerts use the browser's voice |
| Radio misbehaving | Unplug the boards; the link falls back to simulated and the Earth page says so |
| Sun causes delay, not loss | Move Habitat farther away or into the foil box, then recalibrate |
