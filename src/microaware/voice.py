"""ElevenLabs text-to-speech for alerts. Without a key the dashboard falls back to the browser's own speech."""
import os

import httpx


def synthesize(text, severity, path):
    """Write an MP3 of `text` to `path`; returns False if TTS is unavailable or fails."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    voice = os.environ.get("ELEVENLABS_VOICE_URGENT" if severity == "critical" else "ELEVENLABS_VOICE_CALM")
    if not key or not voice:
        return False
    try:
        r = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key},
            json={"text": text, "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")},
            timeout=10,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"TTS failed ({e}); the dashboard will use browser speech.")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return True
