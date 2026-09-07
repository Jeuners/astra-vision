"""Pipecat adapters for native Ollama, live Nemotron ASR, and Pocket TTS."""

import asyncio
import json
import time
from contextlib import aclosing
from uuid import uuid4

import httpx
from loguru import logger
from openai.types.chat import ChatCompletionChunk
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.types import is_given

from astra.core import Settings, build_request
from astra.inference import Models, Recognizer, drain_stream, on_executor


class NativeOllamaService(OpenAILLMService):
    """Use /api/chat so think=False cannot be lost in compatibility translation."""

    supports_developer_role = False

    def __init__(self, config: Settings, notify):
        super().__init__(
            api_key="local",
            base_url=f"{config.ollama_url}/v1",
            settings=self.Settings(model=config.model),
        )
        self.config = config
        self.notify = notify

    async def get_chat_completions(self, context: LLMContext):
        payload = build_request(self.config, context.get_messages())
        context.set_messages(payload["messages"])
        tools = self.get_llm_adapter().from_standard_tools(context.tools)
        if is_given(tools) and tools:
            payload["tools"] = list(tools)

        async def chunks():
            start = time.monotonic()
            first = True
            complete = False
            async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5)) as client:
                async with client.stream(
                    "POST", f"{self.config.ollama_url}/api/chat", json=payload
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        event = json.loads(line)
                        if event.get("error"):
                            raise RuntimeError(event["error"])
                        message = event.get("message", {})
                        if message.get("thinking"):
                            raise RuntimeError("Ollama liefert Thinking trotz think=false.")
                        for tool_index, call in enumerate(message.get("tool_calls") or []):
                            function = call.get("function", {})
                            yield ChatCompletionChunk(
                                id="local",
                                object="chat.completion.chunk",
                                created=int(time.time()),
                                model=self.config.model,
                                choices=[
                                    {
                                        "index": 0,
                                        "delta": {
                                            "tool_calls": [
                                                {
                                                    "index": tool_index,
                                                    "id": f"call_{uuid4().hex}",
                                                    "type": "function",
                                                    "function": {
                                                        "name": function.get("name", ""),
                                                        "arguments": json.dumps(
                                                            function.get("arguments") or {}
                                                        ),
                                                    },
                                                }
                                            ]
                                        },
                                        "finish_reason": None,
                                    }
                                ],
                            )
                        content = message.get("content", "")
                        if content:
                            if first:
                                self.notify(
                                    {
                                        "type": "metric",
                                        "name": "llm_ms",
                                        "value": round((time.monotonic() - start) * 1000),
                                    }
                                )
                                first = False
                            yield ChatCompletionChunk(
                                id="local",
                                object="chat.completion.chunk",
                                created=int(time.time()),
                                model=self.config.model,
                                choices=[
                                    {
                                        "index": 0,
                                        "delta": {"content": content},
                                        "finish_reason": None,
                                    }
                                ],
                            )
                        if event.get("done"):
                            complete = True
                    if not complete:
                        raise RuntimeError("Ollama hat den Antwortstream vorzeitig geschlossen.")

        return chunks()


class NemotronSTTService(STTService):
    def __init__(self, models: Models, notify):
        super().__init__(
            sample_rate=16000,
            audio_passthrough=True,
            ttfs_p99_latency=1.0,
            settings=STTSettings(model=models.settings.stt_model, language="de-DE"),
        )
        self.models = models
        self.notify = notify
        self.queue = asyncio.Queue(maxsize=100)
        self.worker = None
        self.active = False
        self.preroll = bytearray()
        self.pending = bytearray()
        self.failed = False

    async def run_stt(self, audio):
        # Audio is fed by process_audio_frame to avoid blocking VAD on inference.
        if False:
            yield None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self.worker = self.create_task(self._worker())

    async def stop(self, frame: EndFrame):
        if self.worker:
            await self.cancel_task(self.worker)
            self.worker = None
        await super().stop(frame)

    async def cancel(self, frame: CancelFrame):
        if self.worker:
            await self.cancel_task(self.worker)
            self.worker = None
        await super().cancel(frame)

    def _enqueue(self, item):
        if self.failed:
            return
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.failed = True
            self.notify(
                {"type": "error", "message": "Spracherkennung überlastet. Bitte neu verbinden."}
            )

    async def process_audio_frame(self, frame: InputAudioRawFrame, direction: FrameDirection):
        if frame.sample_rate != 16000 or frame.num_channels != 1:
            raise ValueError("Nemotron benötigt 16 kHz Mono-PCM")
        if self.active:
            self.pending.extend(frame.audio)
            while len(self.pending) >= 10240:
                self._enqueue(("audio", bytes(self.pending[:10240])))
                del self.pending[:10240]
        else:
            self.preroll.extend(frame.audio)
            del self.preroll[:-6400]  # 200 ms, includes VAD start delay.

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, VADUserStartedSpeakingFrame) and not self.active:
            self.active = True
            self._enqueue(("start", bytes(self.preroll)))
            self.preroll.clear()
        elif isinstance(frame, VADUserStoppedSpeakingFrame) and self.active:
            self.active = False
            self._enqueue(("final", bytes(self.pending)))
            self.pending.clear()
        await super().process_frame(frame, direction)

    async def _worker(self):
        recognizer = None
        previous = ""
        try:
            while True:
                kind, pcm = await self.queue.get()
                logger.debug("Nemotron chunk: {}, {} bytes", kind, len(pcm))
                if kind == "start":
                    recognizer = await on_executor(
                        self.models.stt_executor, Recognizer, self.models.stt
                    )
                    previous = ""
                if recognizer is None:
                    continue
                text = await on_executor(
                    self.models.stt_executor, recognizer.push, pcm, kind == "final"
                )
                logger.debug("Nemotron result: {}, {} characters", kind, len(text))
                if kind == "final":
                    if text:
                        await self.push_frame(
                            TranscriptionFrame(
                                text=text,
                                user_id="local",
                                timestamp=time_now_iso8601(),
                                finalized=True,
                            )
                        )
                    self.notify({"type": "partial", "text": ""})
                    recognizer = None
                elif text and text != previous:
                    await self.push_frame(
                        InterimTranscriptionFrame(
                            text=text, user_id="local", timestamp=time_now_iso8601()
                        )
                    )
                    self.notify({"type": "partial", "text": text})
                    previous = text
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failed = True
            self.notify({"type": "error", "message": f"Spracherkennung: {exc}"})
            await self.push_error_frame(ErrorFrame(error=f"Nemotron: {exc}", fatal=True))


def next_chunk(stream):
    return next(stream, None)


class LocalPocketTTSService(TTSService):
    def __init__(self, models: Models, voice_state: dict, voice_name: str):
        super().__init__(
            push_start_frame=True,
            push_stop_frames=True,
            settings=TTSSettings(model="pocket-tts", voice=voice_name, language="de"),
        )
        self.models = models
        self.voice_state = voice_state

    async def run_tts(self, text: str, context_id: str):
        import torch

        stream = self.models.tts.generate_audio_stream(self.voice_state, text, copy_state=True)

        async def audio():
            try:
                while True:
                    chunk = await on_executor(self.models.tts_executor, next_chunk, stream)
                    if chunk is None:
                        break
                    yield (chunk.clamp(-1, 1) * 32767).to(torch.int16).numpy().tobytes()
            finally:
                await on_executor(self.models.tts_executor, drain_stream, stream)

        try:
            async with aclosing(audio()) as audio_stream:
                async with aclosing(
                    self._stream_audio_frames_from_iterator(
                        audio_stream,
                        in_sample_rate=self.models.tts.sample_rate,
                        context_id=context_id,
                    )
                ) as frames:
                    async for frame in frames:
                        yield frame
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield ErrorFrame(error=f"Sprachausgabe: {exc}")
