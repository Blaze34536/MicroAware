"""Turns an alert's evidence into one spoken sentence and 3 checks. The LLM explains; it never decides."""
import json
import os
from pathlib import Path

import httpx

NOTES = (Path(__file__).parent / "maintenance.md").read_text()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
TIMEOUT = 6.0
FIX_TIMEOUT = 20.0  # asked for on demand, so it can take longer than the spoken explanation
_cache = {}
_fix_cache = {}

CANNED = {
    "imbalance": ("Fan A sounds unbalanced. Check the blades for debris or a loose blade.",
                  "Rotor imbalance", ["Stop the fan and inspect the blades", "Spin it by hand and look for wobble", "Check the blade fasteners"]),
    "loose_mount": ("Fan A is rattling. Its mount may be loose.",
                    "Loose mount", ["Check the mount screws", "Inspect the isolation grommets", "Look for contact with nearby panels"]),
    "bearing": ("Fan A has a high-pitched whine. A bearing may be wearing out.",
                "Bearing wear", ["Listen at the motor end cap", "Feel for heat at the bearing", "Spin it by hand and feel for roughness"]),
    "air_leak": ("Fan A is hissing. Air may be leaking from the duct.",
                 "Air leak", ["Feel along the duct joints for escaping air", "Check the duct clamps", "Check the filter housing seal"]),
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


def gemini(prompt, timeout=TIMEOUT):
    key = os.environ["GEMINI_API_KEY"]
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": key},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
        timeout=timeout,
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


SAFE = "Switch the fan off at its breaker and wait for the rotor to stop. Keep the backup fan running."
FIXES = {
    "imbalance": ("Clean or replace the unbalanced blade.", ["Flashlight", "3 mm hex key", "Isopropyl wipes"],
                  ["Inspect each blade for debris, tape or ice and remove it", "Spin the rotor by hand and watch for wobble",
                   "Retighten any loose blade clips", "Replace a cracked or bent blade from the spare kit in bay 3"]),
    "bearing": ("Relubricate the bearing, or replace the motor if it stays rough.", ["Machine oil", "3 mm hex key", "Flashlight"],
                ["Feel the motor end cap for heat", "Add 2 drops of machine oil at the end-cap port",
                 "Spin by hand: it should turn smoothly and quietly", "If it is still rough or whining, swap in the spare motor from bay 3"]),
    "loose_mount": ("Tighten the mount and replace worn grommets.", ["Phillips screwdriver", "Spare grommets"],
                    ["Retighten the 4 mount screws", "Replace cracked isolation grommets",
                     "Move any cable or panel touching the housing"]),
    "air_leak": ("Find and seal the air leak at the duct.", ["Aluminium duct tape", "Flat screwdriver", "Tissue"],
                 ["Hold a tissue along each duct joint to find escaping air", "Retighten the clamp at that joint",
                  "Seal a split seam with aluminium duct tape", "Reseat the filter housing if the leak is there"]),
    "friction": ("Clear what is rubbing the rotor.", ["Phillips screwdriver", "Flashlight"],
                 ["Look for rub marks on the shroud", "Clear cables or objects from the rotor",
                  "Recentre the shroud: loosen its 4 screws, centre it, retighten"]),
}


def _canned_fix(alert):
    summary, tools, steps = FIXES.get(alert.get("label"), (
        "The cause is unknown: inspect the fan step by step.", ["Flashlight", "Phillips screwdriver", "3 mm hex key"],
        ["Check the blades for debris or damage", "Check the mount screws and grommets",
         "Listen at the motor end cap for a whine", "Feel along the ducts for escaping air"]))
    return {"summary": summary, "tools": tools, "steps": [SAFE.split(".")[0]] + steps, "safety": SAFE,
            "escalate": "If the sound comes back after the fix, run on the backup fan and log it for Earth.", "source": "canned"}


def fix_prompt_for(alert):
    return f"""You help the crew of a Mars habitat repair a life-support fan. Use only the maintenance notes and the
alert evidence; never invent part numbers, tools or locations the notes don't mention. If the label is null, say the
cause is unknown and give an inspection order instead of a repair. The first step must make it safe: power off at the
breaker and wait for the rotor to stop, with the backup fan running.

Maintenance notes:
{NOTES}

Alert:
{json.dumps(alert, indent=1)}

Reply with JSON only: {{"summary": "<one sentence>", "tools": ["<tool>", ...], "steps": ["<short step>", ... 3 to 8 steps],
"safety": "<one sentence>", "escalate": "<when to stop and switch to the backup fan or call Earth>"}}"""


def _valid_fix(out):
    return (isinstance(out, dict) and all(isinstance(out.get(k), str) and out[k].strip() for k in ("summary", "safety", "escalate"))
            and isinstance(out.get("steps"), list) and 3 <= len(out["steps"]) <= 8 and all(isinstance(s, str) for s in out["steps"])
            and isinstance(out.get("tools"), list))


def fix(alert, llm="default"):
    """Repair steps for an alert, cached by id: Gemini with the maintenance notes, else the built-in repair guide."""
    if alert["id"] in _fix_cache:
        return _fix_cache[alert["id"]]
    llm = (lambda p: gemini(p, FIX_TIMEOUT)) if llm == "default" and default_llm() else None if llm == "default" else llm
    out = None
    if llm:
        try:
            out = json.loads(llm(fix_prompt_for({k: v for k, v in alert.items() if k != "audio"})))
        except Exception:
            out = None
    if _valid_fix(out):
        out = {k: out[k] for k in ("summary", "tools", "steps", "safety", "escalate")} | {"source": "llm"}
    else:
        out = _canned_fix(alert)
    _fix_cache[alert["id"]] = out
    return out
