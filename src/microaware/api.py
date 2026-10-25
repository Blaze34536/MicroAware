"""FastAPI app: dashboard, REST commands, and a 4 Hz WebSocket tick."""
import asyncio
import functools
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audio_source, explainer, isolate, sounds
from .engine import FAULTS, Engine
from .link import weather
from .link.downlink import Downlink, SimLink, choose_mode
from .link.serial_link import open_radio

STATIC = Path(__file__).resolve().parent.parent / "static"


class BaselineReq(BaseModel):
    seconds: float = Field(90, ge=5, le=300)


class LabelReq(BaseModel):
    label: str = Field(pattern=r"^[a-z][a-z_]{0,31}$")  # becomes part of a file name
    seconds: float = Field(15, ge=3, le=120)


class ConfigReq(BaseModel):
    threshold_scale: float | None = Field(None, ge=0.2, le=5)
    ignore_talking: bool | None = None


class GuardReq(BaseModel):
    playing: bool
    seconds: float = Field(30, gt=0, le=600)


class FlareReq(BaseModel):
    level: int = Field(ge=0, le=100)
    seconds: float = Field(30, gt=0, le=300)


class InjectReq(BaseModel):
    fault: str
    seconds: float = Field(10, gt=0, le=120)


def create_app(engine, downlink=None):
    app = FastAPI(title="MicroAware")

    def link_status():
        if downlink is None:
            return None
        return {"link": downlink.link.name, "mode": choose_mode(downlink.weather["level"], downlink.flare(), "normal"),
                "flare": downlink.flare(), "flare_left_s": max(0, round(downlink.flare_until - time.time())) if downlink.flare() else 0,
                "weather": downlink.weather, "last_minute": downlink.totals(60)}

    def need_downlink():
        if downlink is None:
            raise HTTPException(503, "The Earth link isn't running.")
        return downlink

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/earth")
    def earth():
        return FileResponse(STATIC / "earth.html")

    @app.get("/sounds")
    def sounds_page():
        return FileResponse(STATIC / "sounds.html")

    @app.get("/api/sounds")
    def sound_catalog():
        return sounds.catalog()

    @app.get("/api/sounds/{sound_id}.wav")
    def sound_wav(sound_id: str):
        try:
            return Response(sounds.wav(sound_id), media_type="audio/wav")
        except KeyError:
            raise HTTPException(404, f"No generated sound {sound_id}")

    @app.post("/api/sounds/{sound_id}/analyze")
    def sound_analyze(sound_id: str):
        if not sound_id.startswith("fan_"):
            raise HTTPException(422, "MicroAware learns one machine at a time: record a baseline of this machine to check it.")
        try:
            return sounds.analyze(sound_id)
        except KeyError:
            raise HTTPException(404, f"No sound {sound_id}")

    @app.get("/api/link/status")
    def get_link_status():
        need_downlink()
        return link_status()

    @app.post("/api/link/flare")
    def flare(req: FlareReq):
        need_downlink().set_flare(req.level, req.seconds)
        return link_status()

    @app.get("/api/link/delivery/{alert_id}")
    def delivery(alert_id: str):
        return need_downlink().delivery(alert_id) or _404(alert_id)

    @app.get("/api/link/messages")
    def messages():
        dl = need_downlink()
        return [dl.status(r) for r in dl.records[-20:][::-1]]

    @app.get("/api/link/messages/{msg_id}")
    def message(msg_id: int):
        dl = need_downlink()
        if not any(r["msg_id"] == msg_id for r in dl.records):
            raise HTTPException(404, f"No message {msg_id}")
        return dl.earth_view(msg_id)

    @app.post("/api/link/send/{alert_id}")
    def resend(alert_id: str):
        """Send an alert again, e.g. to show the same alert under a new storm."""
        dl, alert, image = need_downlink(), engine.alerts.get(alert_id), engine.image(alert_id)
        if not alert or image is None:
            _404(alert_id)
        return dl.send_alert(alert, image)

    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")

    @app.get("/api/status")
    def status():
        snap = engine.snapshot()
        return {k: snap[k] for k in ("state", "score", "threshold", "threshold_scale", "source", "machine")} | {
            "active_alerts": [a for a in snap["alerts"] if a["state"] == "active"]}

    @app.get("/api/history")
    def history(minutes: float = 10):
        return engine.history_summary(min(max(minutes, 0.5), 10))

    @app.get("/api/voice/config")
    def voice_config():
        # only the public agent id goes to the browser; API keys stay on the server
        return {"agent_id": os.environ.get("ELEVENLABS_AGENT_ID")}

    @app.get("/api/alerts")
    def alerts():
        return engine.alerts.alerts[::-1]

    @app.get("/api/alerts/{alert_id}")
    def alert(alert_id: str):
        return engine.alerts.get(alert_id) or _404(alert_id)

    @app.get("/api/alerts/{alert_id}/fix")
    def alert_fix(alert_id: str):
        """Repair steps from Gemini with the maintenance notes, or the built-in repair guide."""
        alert = engine.alerts.get(alert_id) or _404(alert_id)
        return explainer.fix(alert, llm=engine.llm)

    @app.post("/api/alerts/{alert_id}/ack")
    def ack(alert_id: str):
        return engine.alerts.ack(alert_id) or _404(alert_id)

    @app.post("/api/baseline")
    def baseline(req: BaselineReq):
        engine.start_baseline(req.seconds)
        return {"state": engine.state}

    @app.post("/api/labels/record")
    def record_label(req: LabelReq):
        if engine.detector is None:
            raise HTTPException(409, "Record the normal sound first.")
        engine.start_baseline(req.seconds, label=req.label)
        return {"state": engine.state, "label": req.label}

    @app.get("/api/labels")
    def labels():
        return engine.label_counts()

    @app.post("/api/labeler/train")
    def train_labeler():
        try:
            return {"labels": engine.train_labeler()}
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.put("/api/config")
    def config(req: ConfigReq):
        if req.threshold_scale is not None:
            engine.threshold_scale = req.threshold_scale
        if req.ignore_talking is not None:
            engine.ignore_talking = req.ignore_talking
        return {"threshold_scale": engine.threshold_scale, "threshold": engine.threshold, "ignore_talking": engine.ignore_talking}

    @app.post("/api/guard")
    def guard(req: GuardReq):
        """The browser reports when it plays alert audio or a voice session is open."""
        engine.guard(req.playing, req.seconds)
        return {"guarded": req.playing}

    @app.get("/api/voice/alert/{alert_id}.mp3")
    def voice_file(alert_id: str):
        path = engine.voice_path(alert_id)
        if not engine.alerts.get(alert_id) or not path.exists():
            _404(alert_id)
        return FileResponse(path, media_type="audio/mpeg")

    @app.post("/api/sim/inject")
    def inject(req: InjectReq):
        if req.fault not in FAULTS:
            raise HTTPException(422, f"Unknown fault {req.fault!r}. Use one of: {', '.join(FAULTS)}")
        engine.inject, engine.inject_pos = (req.fault, time.time() + req.seconds), 0
        return {"inject": req.fault, "seconds": req.seconds}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        try:
            while True:
                await sock.send_json(engine.snapshot() | {"link": link_status()})
                await asyncio.sleep(0.25)
        except WebSocketDisconnect:
            pass

    return app


def _404(alert_id):
    raise HTTPException(404, f"No alert {alert_id}")


def build():
    """Entry point for uvicorn --factory. MICROAWARE_SOURCE: mic (default), synth, or file:<path.wav>."""
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    want = os.environ.get("MICROAWARE_SOURCE", "mic")
    key = os.environ.get("ELEVENLABS_API_KEY")
    engine = Engine(source=want.split(":")[0], isolator=functools.partial(isolate.isolate, api_key=key) if key else None)
    on_audio = engine.push
    if os.environ.get("MICROAWARE_RECORD"):
        on_audio, _close = audio_source.recorder(engine.push, os.environ["MICROAWARE_RECORD"])
        print(f"Recording everything heard to {os.environ['MICROAWARE_RECORD']}")
    try:
        if want.startswith("file:"):
            audio_source.start_file(on_audio, want[5:])
        else:
            # keep the stream referenced, or it is garbage-collected mid-callback and PortAudio segfaults
            engine.stream = (audio_source.start_mic if want == "mic" else audio_source.start_synth)(on_audio)
    except Exception as e:
        print(f"Mic unavailable ({e}); using the synthetic fan instead.")
        engine.source = "synth"
        audio_source.start_synth(engine.push)

    def loop():
        while True:
            engine.step()
            time.sleep(0.5)

    threading.Thread(target=loop, daemon=True).start()

    link = None
    if os.environ.get("MICROAWARE_LINK", "auto") != "sim":
        try:
            link = open_radio()
        except Exception as e:
            print(f"Radio unavailable ({e}).")
    if link is None:
        print("No Habitat + Earth boards found; using the simulated link.")
    downlink = Downlink(link or SimLink())
    engine.on_alert_ready.append(downlink.send_alert)
    weather.start_polling(downlink)
    return create_app(engine, downlink)
