"""Turns an alert's evidence into one spoken sentence and 3 checks. The LLM explains; it never decides."""
import json
import os
from pathlib import Path

import httpx

NOTES = (Path(__file__).parent / "maintenance.md").read_text()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
TIMEOUT = 6.0
_cache = {}

CANNED = {
    "imbalance": ("Fan A sounds unbalanced. Check the blades for debris or a loose blade.",
                  "Rotor imbalance", ["Stop the fan and inspect the blades", "Spin it by hand and look for wobble", "Check the blade fasteners"]),
    "loose_mount": ("Fan A is rattling. Its mount may be loose.",
                    "Loose mount", ["Check the mount screws", "Inspect the isolation grommets", "Look for contact with nearby panels"]),
    "friction": ("Fan A sounds like something is rubbing the rotor.",
                 "Friction on the rotor", ["Look for rub marks on the shroud", "Clear cables and objects from the rotor", "Listen at the bearing"]),
}


def _canned(alert):
    label = alert.get("label")
    if label in CANNED:
        spoken, cause, checks = CANNED[label]
    else:
        bands = alert["evidence"]["top_bands"]
        where = ""
        if bands:
            lo, hi = (int(x) for x in bands[0]["band_hz"].split("-"))
            where = f" near {(lo + hi) / 2000:.1f} kilohertz"
        spoken = f"Fan A has an unknown anomaly, with new sound{where}. Inspect the fan."
        cause, checks = "Unknown cause", ["Inspect the fan and its mount", "Compare with the last maintenance log", "Switch to the backup fan if it persists"]
    return {"spoken": spoken, "cause": cause, "checks": checks, "confidence": "low", "source": "canned"}


def prompt_for(alert):
    return f"""You explain machine alerts to the crew of a Mars habitat. Use only the evidence given; never invent
sensor values, part numbers, or causes the notes don't support. If the label is null or unknown, say the cause is unknown.

Maintenance notes:
{NOTES}

Alert:
{json.dumps(alert, indent=1)}

Reply with JSON only: {{"spoken": "<one sentence, at most 25 words, for text-to-speech>",
"cause": "<short likely cause>", "checks": ["<check 1>", "<check 2>", "<check 3>"], "confidence": "low|medium|high"}}"""


def gemini(prompt):
    key = os.environ["GEMINI_API_KEY"]
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": key},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def default_llm():
    return gemini if os.environ.get("GEMINI_API_KEY") else None


def _valid(out):
    return (isinstance(out, dict) and isinstance(out.get("spoken"), str) and out["spoken"].strip()
            and isinstance(out.get("checks"), list) and len(out["checks"]) == 3
            and out.get("confidence") in ("low", "medium", "high"))


def explain(alert, llm="default"):
    """Explanation dict for an alert, cached by id. llm: callable(prompt)->str, None for canned only."""
    if alert["id"] in _cache:
        return _cache[alert["id"]]
    llm = default_llm() if llm == "default" else llm
    out = None
    if llm:
        try:
            out = json.loads(llm(prompt_for(alert)))
        except Exception:
            out = None
    if _valid(out):
        out = {k: out.get(k) for k in ("spoken", "cause", "checks", "confidence")} | {"source": "llm"}
    else:
        out = _canned(alert)
    _cache[alert["id"]] = out
    return out
