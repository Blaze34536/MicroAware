# Setting up the voice assistant (ElevenLabs Agents)

Quickest: `cd src && ../.venv/bin/python tools/create_agent.py` creates the agent and its 5 tools through the API and prints the id to put in `.env` as `ELEVENLABS_AGENT_ID`. It uses ElevenLabs' default voice: voices with live moderation are refused for agents.

By hand in the ElevenLabs dashboard instead, about 10 minutes:

1. **Agents → Create agent → Blank.** Name it "MicroAware flight engineer".
2. **System prompt:**

   > You are the flight-engineer assistant for a Mars habitat. You help the crew understand alerts from MicroAware, which listens to the habitat's life-support fan.
   > Always call a tool before stating any number, status, or trend. Never guess.
   > Answer in two sentences or fewer, in plain words.
   > You support crew decisions; you don't make them. Recommend checks, never order actions.
   > If a tool fails or returns an error, say the data is unavailable.
   > "Score" is how unusual the fan sounds; above "threshold" means abnormal. Say "kilohertz", not "Hz".

3. **First message:** "Flight engineer here. What do you need?"
4. **Tools → Add tool → Client tool** for each row below. Turn **Wait for response** on for all of them. Names must match exactly.

| Name | Description | Parameters |
|---|---|---|
| `get_status` | Current state of the fan: nominal or abnormal, score, threshold, active alerts. | none |
| `get_history` | Score history and trend (rising, flat, falling), and how long the fan has been abnormal. | `minutes` (number, optional, default 10) |
| `get_alert` | Details and explanation of one alert, including what to check. | `id` (string, an alert id like A-0003, or "latest") |
| `get_fix` | Step-by-step repair instructions for one alert: tools needed, steps, safety, when to escalate. | `id` (string, an alert id or "latest") |
| `acknowledge_alert` | Mark an alert as acknowledged by the crew. Only call when the crew says they're on it. | `id` (string, required) |

5. Copy the agent id (starts with `agent_`) into `.env` as `ELEVENLABS_AGENT_ID`, then restart `./run.sh`.
6. If the agent is private, also enable authentication later. For the demo, a public agent with a short session is simplest; delete it after the event.

While a session is open, the dashboard pauses alerting so the conversation isn't scored as a fan fault.
