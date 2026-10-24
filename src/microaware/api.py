"""FastAPI app: dashboard, REST commands, and a 4 Hz WebSocket tick."""
import asyncio
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audio_source
from .engine import FAULTS, Engine

STATIC = Path(__file__).resolve().parent.parent / "static"


class BaselineReq(BaseModel):
    seconds: float = Field(90, ge=5, le=300)


class ConfigReq(BaseModel):
    threshold_scale: float = Field(ge=0.2, le=5)


class InjectReq(BaseModel):
    fault: str
    seconds: float = Field(10, gt=0, le=120)


def create_app(engine):
    app = FastAPI(title="MicroAware")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")

    @app.get("/api/status")
    def status():
        snap = engine.snapshot()
        return {k: snap[k] for k in ("state", "score", "threshold", "threshold_scale", "source", "machine")} | {
            "active_alerts": [a for a in snap["alerts"] if a["state"] == "active"]}

    @app.get("/api/alerts")
    def alerts():
        return engine.alerts.alerts[::-1]

    @app.get("/api/alerts/{alert_id}")
    def alert(alert_id: str):
        return engine.alerts.get(alert_id) or _404(alert_id)

    @app.post("/api/alerts/{alert_id}/ack")
    def ack(alert_id: str):
        return engine.alerts.ack(alert_id) or _404(alert_id)

    @app.post("/api/baseline")
    def baseline(req: BaselineReq):
        engine.start_baseline(req.seconds)
        return {"state": engine.state}

    @app.put("/api/config")
    def config(req: ConfigReq):
        engine.threshold_scale = req.threshold_scale
        return {"threshold_scale": engine.threshold_scale, "threshold": engine.threshold}

    @app.post("/api/sim/inject")
    def inject(req: InjectReq):
        if req.fault not in FAULTS:
            raise HTTPException(422, f"Unknown fault {req.fault!r}. Use one of: {', '.join(FAULTS)}")
        engine.inject = (req.fault, time.time() + req.seconds)
        return {"inject": req.fault, "seconds": req.seconds}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        try:
            while True:
                await sock.send_json(engine.snapshot())
                await asyncio.sleep(0.25)
        except WebSocketDisconnect:
            pass

    return app


def _404(alert_id):
    raise HTTPException(404, f"No alert {alert_id}")


def build():
    """Entry point for uvicorn --factory: picks the mic, or the synthetic fan if MICROAWARE_SOURCE=synth or no mic."""
    want = os.environ.get("MICROAWARE_SOURCE", "mic")
    engine = Engine(source=want)
    try:
        # keep the stream referenced, or it is garbage-collected mid-callback and PortAudio segfaults
        engine.stream = (audio_source.start_mic if want == "mic" else audio_source.start_synth)(engine.push)
    except Exception as e:
        print(f"Mic unavailable ({e}); using the synthetic fan instead.")
        engine.source = "synth"
        audio_source.start_synth(engine.push)

    def loop():
        while True:
            engine.step()
            time.sleep(0.5)

    threading.Thread(target=loop, daemon=True).start()
    return create_app(engine)
