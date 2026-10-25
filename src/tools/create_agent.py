"""Create the MicroAware voice assistant in ElevenLabs and print its id (instead of the dashboard steps in
docs/voice-agent.md). Run from src: ../.venv/bin/python tools/create_agent.py"""
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
API = "https://api.elevenlabs.io/v1/convai"

PROMPT = """You are the flight-engineer assistant for a Mars habitat. You help the crew understand alerts from MicroAware, which listens to the habitat's life-support fan.
Always call a tool before stating any number, status, or trend. Never guess.
Answer in two sentences or fewer, in plain words. When reading repair steps, give one or two steps at a time.
You support crew decisions; you don't make them. Recommend checks, never order actions.
If a tool fails or returns an error, say the data is unavailable.
"Score" is how unusual the fan sounds; above "threshold" means abnormal. Say "kilohertz", not "Hz"."""

ID = {"id": {"type": "string", "description": 'An alert id like A-0003, or "latest"'}}
TOOLS = [
    ("get_status", "Current state of the fan: nominal or abnormal, score, threshold, active alerts.", {}, []),
    ("get_history", "Score history and trend (rising, flat, falling), and how long the fan has been abnormal.",
     {"minutes": {"type": "number", "description": "How many minutes back, default 10"}}, []),
    ("get_alert", "Details and explanation of one alert, including what to check.", ID, ["id"]),
    ("get_fix", "Step-by-step repair instructions for one alert: tools needed, steps, safety, when to escalate.", ID, ["id"]),
    ("acknowledge_alert", "Mark an alert as acknowledged by the crew. Only call when the crew says they're on it.",
     {"id": {"type": "string", "description": "The alert id, like A-0003"}}, ["id"]),
]


def main():
    headers = {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}
    existing = {t["tool_config"]["name"]: t["id"] for t in httpx.get(f"{API}/tools", headers=headers, timeout=30).json()["tools"]}
    tool_ids = []
    for name, desc, props, required in TOOLS:
        if name in existing:  # reruns reuse the tools instead of piling up copies
            tool_ids.append(existing[name])
            continue
        r = httpx.post(f"{API}/tools", headers=headers, timeout=30, json={"tool_config": {
            "type": "client", "name": name, "description": desc, "expects_response": True,
            "parameters": {"type": "object", "properties": props, "required": required}}})
        r.raise_for_status()
        tool_ids.append(r.json()["id"])
    agent = {"name": "MicroAware flight engineer", "conversation_config": {
        "agent": {"first_message": "Flight engineer here. What do you need?", "language": "en",
                  "prompt": {"prompt": PROMPT, "tool_ids": tool_ids}}}}  # default voice: library voices with live moderation are refused
    r = httpx.post(f"{API}/agents/create", headers=headers, json=agent, timeout=30)
    if r.is_error:
        raise SystemExit(f"Agent not created ({r.status_code}): {r.text}")
    print(r.json()["agent_id"])


if __name__ == "__main__":
    main()
