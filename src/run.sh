#!/usr/bin/env bash
# Starts MicroAware. MICROAWARE_SOURCE=synth uses a simulated fan instead of the mic.
cd "$(dirname "$0")"
ROOT=$(cd .. && pwd)
# shortcut: PortAudio unpacked into .venv because apt needs sudo; drop this once libportaudio2 is installed system-wide
export LD_LIBRARY_PATH="$ROOT/.venv/portaudio/root/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
exec "$ROOT/.venv/bin/uvicorn" --factory microaware.api:build --host 127.0.0.1 --port "${PORT:-8000}" "$@"
