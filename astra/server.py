"""Loopback-only WebRTC voice app. One live session shares the warm models."""

import asyncio
import base64
import contextlib
import os
import sys
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from astra.core import (
    SYSTEM_PROMPT,
    VOICE_NAMES,
    VOICES,
    Settings,
    build_request,
    local_origin_allowed,
)
from astra.documents import extract_pdf_text
from astra.inference import Models, on_executor
from astra.triggers import detect_article_reference, detect_news_topic, trigger_tool

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


class Offer(BaseModel):
    sdp: str = Field(min_length=10, max_length=65536)
    type: Literal["offer"]
    voice: str | None = None

    @field_validator("voice")
    @classmethod
    def voice_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in VOICE_NAMES:
            raise ValueError("Unbekannte Stimme")
        return value


class Disconnect(BaseModel):
    pc_id: str = Field(max_length=100)


async def run_voice(connection, models, config, voice_state, voice_name, context):
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        InterruptionFrame,
        LLMFullResponseStartFrame,
        VADUserStartedSpeakingFrame,
    )
    from pipecat.observers.base_observer import BaseObserver
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.workers.runner import WorkerRunner

    from astra.services import LocalPocketTTSService, NativeOllamaService, NemotronSTTService

    notify = connection.send_app_message

    class UIObserver(BaseObserver):
        def __init__(self):
            super().__init__()
            self.seen = deque(maxlen=128)

        async def on_push_frame(self, data):
            frame = data.frame
            relevant = (
                BotStartedSpeakingFrame,
                BotStoppedSpeakingFrame,
                InterruptionFrame,
                LLMFullResponseStartFrame,
                VADUserStartedSpeakingFrame,
            )
            if not isinstance(frame, relevant) or frame.id in self.seen:
                return
            self.seen.append(frame.id)
            if isinstance(frame, BotStartedSpeakingFrame):
                notify({"type": "state", "state": "speaking"})
            elif isinstance(frame, LLMFullResponseStartFrame):
                notify({"type": "state", "state": "responding"})
            else:
                notify({"type": "state", "state": "listening"})

    transport = SmallWebRTCTransport(
        connection,
        TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        ),
    )
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    confidence=0.7,
                    start_secs=0.1,
                    stop_secs=0.7,
                    min_volume=0.6,
                )
            ),
        ),
    )
    stt = NemotronSTTService(models, notify)
    llm = NativeOllamaService(config, notify)
    tts = LocalPocketTTSService(models, voice_state, voice_name)
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
        enable_rtvi=False,
        idle_timeout_secs=None,
        observers=[UIObserver()],
    )

    @transport.event_handler("on_client_connected")
    async def connected(transport, client):
        notify({"type": "state", "state": "listening"})

    @transport.event_handler("on_client_disconnected")
    async def disconnected(transport, client):
        await worker.cancel()

    last_headlines: list[dict] = []

    @aggregators.user().event_handler("on_user_turn_stopped")
    async def user_turn(aggregator, strategy, message):
        if message.content:
            notify({"type": "transcript", "role": "user", "text": message.content})
            topic = detect_news_topic(message.content)
            if topic:
                result = await trigger_tool(context, "read_news", {"topic": topic})
                if result and result.get("status") == "ok":
                    last_headlines[:] = result.get("headlines", [])
                return
            number = detect_article_reference(message.content)
            if number is not None:
                match = next((h for h in last_headlines if h.get("number") == number), None)
                if match:
                    await trigger_tool(context, "read_article", {"url": match["link"]})

    @aggregators.assistant().event_handler("on_assistant_turn_stopped")
    async def assistant_turn(aggregator, message):
        if message.content or message.interrupted:
            notify(
                {
                    "type": "transcript",
                    "role": "assistant",
                    "text": message.content or "…",
                    "interrupted": message.interrupted,
                }
            )

    @worker.event_handler("on_pipeline_error")
    async def error(worker, frame):
        notify({"type": "error", "message": frame.error})

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


def create_app(config=None, *, load_models=True):
    config = config or Settings.from_env()
    models = Models(config)
    status = {"ready": False, "stage": "starting", "error": None}
    sessions = {}
    media_store: dict[str, bytes] = {}
    lock = asyncio.Lock()

    async def warmup():
        try:
            status["stage"] = "Gesprächssteuerung wird vorbereitet"

            def prepare_pipeline():
                import nltk
                from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
                    LocalSmartTurnAnalyzerV3,
                )
                from pipecat.audio.vad.silero import SileroVADAnalyzer

                from astra import services  # noqa: F401

                nltk.data.path.insert(0, str(ROOT / ".cache" / "nltk"))
                nltk.data.find("tokenizers/punkt_tab")
                nltk.sent_tokenize("Hallo. Alles bereit.")
                LocalSmartTurnAnalyzerV3()
                SileroVADAnalyzer()

            await asyncio.to_thread(prepare_pipeline)
            status["stage"] = "Spracherkennung wird geladen"
            await on_executor(models.stt_executor, models.load_stt)
            status["stage"] = "Deutsche Stimme wird geladen"
            await on_executor(models.tts_executor, models.load_tts)
            await on_executor(models.tts_executor, models.get_voice, config.voice)
            status["stage"] = "Qwen wird vorbereitet"
            async with httpx.AsyncClient(timeout=180) as client:
                payload = build_request(config, [{"role": "user", "content": "Sage Hallo."}])
                payload["stream"] = False
                payload["options"]["num_predict"] = 12
                response = await client.post(f"{config.ollama_url}/api/chat", json=payload)
                response.raise_for_status()
                result = response.json()
                if result.get("error") or not result.get("message", {}).get("content"):
                    raise RuntimeError(f"Ollama: {result.get('error', 'Keine Antwort')}")
                if result["message"].get("thinking"):
                    raise RuntimeError("Ollama hat Thinking nicht ausgeschaltet")
            status.update(ready=True, stage="Bereit")
            logger.info("Astra bereit auf http://localhost:{}", config.port)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Modelle konnten nicht geladen werden")
            message = str(exc) or type(exc).__name__
            if isinstance(exc, httpx.TimeoutException):
                message = "Ollama antwortet nicht rechtzeitig. Bitte den lokalen Modelldienst prüfen."
            status.update(ready=False, stage="Start fehlgeschlagen", error=message)

    @asynccontextmanager
    async def lifespan(app):
        warming = asyncio.create_task(warmup()) if load_models else None
        try:
            yield
        finally:
            if warming:
                warming.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await warming
            for connection, task, _ in list(sessions.values()):
                await connection.disconnect()
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await models.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.status = status

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        allowed_hosts = {"localhost", "127.0.0.1"}
        if config.tailnet_host:
            allowed_hosts.add(config.tailnet_host)
        if request.url.hostname not in allowed_hosts:
            return JSONResponse({"detail": "Nur lokal erreichbar"}, status_code=403)
        if request.method == "POST" and not local_origin_allowed(
            request.headers.get("origin", ""), config.port, config.tailnet_host
        ):
            return JSONResponse({"detail": "Ungültiger Ursprung"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'"
        )
        return response

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "web" / "index.html")

    @app.get("/api/status")
    async def health():
        return {**status, "busy": bool(sessions), "model": config.model, "thinking": False}

    @app.get("/api/voices")
    async def voices():
        return {"voices": list(VOICES), "default": config.voice}

    @app.post("/api/offer")
    async def offer(body: Offer):
        if not status["ready"]:
            raise HTTPException(503, status["error"] or status["stage"])
        async with lock:
            if sessions:
                raise HTTPException(
                    409, "Ein Gespräch läuft bereits. Beende es im anderen Fenster."
                )
            voice_name = body.voice or config.voice
            voice_state = await on_executor(models.tts_executor, models.get_voice, voice_name)
            from pipecat.processors.aggregators.llm_context import LLMContext
            from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

            from astra.tools import build_tools

            connection = SmallWebRTCConnection(ice_servers=[], connection_timeout_secs=20)
            try:
                await connection.initialize(body.sdp, body.type)
            except Exception:
                await connection.disconnect()
                raise

            notify = connection.send_app_message
            context = LLMContext(
                [{"role": "system", "content": SYSTEM_PROMPT}],
                tools=build_tools(config, notify, media_store),
            )

            async def session():
                try:
                    await run_voice(connection, models, config, voice_state, voice_name, context)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Gespräch fehlgeschlagen")
                    connection.send_app_message({"type": "error", "message": str(exc)})
                finally:
                    await connection.disconnect()
                    sessions.pop(connection.pc_id, None)

            task = asyncio.create_task(session())
            sessions[connection.pc_id] = (connection, task, context)
            return connection.get_answer()

    @app.post("/api/disconnect")
    async def disconnect(body: Disconnect):
        pair = sessions.get(body.pc_id)
        if pair:
            connection, task, _ = pair
            await connection.disconnect()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return {"ok": True}

    @app.get("/api/media/{image_id}")
    async def media(image_id: str):
        image = media_store.get(image_id)
        if image is None:
            raise HTTPException(404, "Bild nicht gefunden")
        return Response(content=image, media_type="image/png")

    @app.post("/api/upload")
    async def upload(pc_id: str = Form(...), file: UploadFile = File(...)):  # noqa: B008
        pair = sessions.get(pc_id)
        if not pair:
            raise HTTPException(404, "Keine aktive Sitzung")
        connection, _, context = pair
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Datei zu groß (max. 15 MB)")
        if file.content_type == "application/pdf":
            text = extract_pdf_text(data)
            if not text:
                raise HTTPException(422, "Im PDF wurde kein Text gefunden")
            context.add_message(
                {
                    "role": "user",
                    "content": f'[Hochgeladenes Dokument "{file.filename}"]\n\n{text}',
                }
            )
        elif file.content_type in {"image/png", "image/jpeg", "image/webp"}:
            context.add_message(
                {
                    "role": "user",
                    "content": f'[Hochgeladenes Bild "{file.filename}"]',
                    "images": [base64.b64encode(data).decode()],
                }
            )
        else:
            raise HTTPException(415, "Nur PDF, PNG, JPEG oder WebP werden unterstützt")
        connection.send_app_message({"type": "upload", "filename": file.filename})
        return {"ok": True}

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    logger.remove()
    logger.add(sys.stderr, level=os.getenv("ASTRA_LOG_LEVEL", "INFO"))
    config = Settings.from_env()
    uvicorn.run(create_app(config), host="127.0.0.1", port=config.port, access_log=False)


if __name__ == "__main__":
    main()
