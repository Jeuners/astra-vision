"""Configuration and pure request policy, independent of audio hardware."""

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    model: str = "qwen3.5:latest"
    ollama_url: str = "http://127.0.0.1:11434"
    stt_model: str = "mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit"
    tts_language: str = "german"
    voice: str = "alba"
    port: int = 7860
    context_tokens: int = 4096
    tailnet_host: str | None = None
    comfyui_url: str = "http://100.125.107.123:8000"

    @classmethod
    def from_env(cls):
        return cls(
            model=os.getenv("ASTRA_MODEL", cls.model),
            ollama_url=os.getenv("ASTRA_OLLAMA_URL", cls.ollama_url).rstrip("/"),
            stt_model=os.getenv("ASTRA_STT_MODEL", cls.stt_model),
            tts_language=os.getenv("ASTRA_TTS_LANGUAGE", cls.tts_language),
            voice=os.getenv("ASTRA_VOICE", cls.voice),
            port=int(os.getenv("ASTRA_PORT", cls.port)),
            tailnet_host=os.getenv("ASTRA_TAILNET_HOST", cls.tailnet_host),
            comfyui_url=os.getenv("ASTRA_COMFYUI_URL", cls.comfyui_url).rstrip("/"),
        )


VOICES = (
    {"name": "alba", "display_name": "Alba", "gender": "weiblich"},
    {"name": "anna", "display_name": "Anna", "gender": "weiblich"},
    {"name": "azelma", "display_name": "Azelma", "gender": "weiblich"},
    {"name": "bill_boerst", "display_name": "Bill Boerst", "gender": "männlich"},
    {"name": "caro_davy", "display_name": "Caro Davy", "gender": "weiblich"},
    {"name": "charles", "display_name": "Charles", "gender": "männlich"},
    {"name": "cosette", "display_name": "Cosette", "gender": "weiblich"},
    {"name": "eponine", "display_name": "Eponine", "gender": "weiblich"},
    {"name": "estelle", "display_name": "Estelle", "gender": "weiblich"},
    {"name": "eve", "display_name": "Eve", "gender": "weiblich"},
    {"name": "fantine", "display_name": "Fantine", "gender": "weiblich"},
    {"name": "george", "display_name": "George", "gender": "männlich"},
    {"name": "giovanni", "display_name": "Giovanni", "gender": "männlich"},
    {"name": "jane", "display_name": "Jane", "gender": "weiblich"},
    {"name": "javert", "display_name": "Javert", "gender": "männlich"},
    {"name": "jean", "display_name": "Jean", "gender": "männlich"},
    {"name": "juergen", "display_name": "Juergen", "gender": "männlich"},
    {"name": "lola", "display_name": "Lola", "gender": "weiblich"},
    {"name": "marius", "display_name": "Marius", "gender": "männlich"},
    {"name": "mary", "display_name": "Mary", "gender": "weiblich"},
    {"name": "michael", "display_name": "Michael", "gender": "männlich"},
    {"name": "paul", "display_name": "Paul", "gender": "männlich"},
    {"name": "peter_yearsley", "display_name": "Peter Yearsley", "gender": "männlich"},
    {"name": "rafael", "display_name": "Rafael", "gender": "männlich"},
    {"name": "stuart_bell", "display_name": "Stuart Bell", "gender": "männlich"},
    {"name": "vera", "display_name": "Vera", "gender": "weiblich"},
)
VOICE_NAMES = frozenset(voice["name"] for voice in VOICES)


SYSTEM_PROMPT = (
    "Du bist Astra, ein freundlicher deutschsprachiger Gesprächsassistent. "
    "Antworte natürlich und knapp, normalerweise in ein bis drei kurzen Sätzen. "
    "Deine Antwort wird vorgelesen: kein Markdown, keine Sternchen, keine Listen. "
    "Sprich Zahlen und Abkürzungen verständlich aus. Stelle bei Bedarf eine kurze Rückfrage. "
    "Du hast keinen Internetzugang und keinen Zugriff auf Dateien oder Apps, außer den dir "
    "explizit gegebenen Werkzeugen. Behaupte nicht, andere Aktionen ausgeführt zu haben. "
    "Wenn der Nutzer ein Bild, eine Grafik oder eine Illustration möchte, rufe sofort das "
    "Werkzeug generate_image auf, statt das Bild nur in Worten zu beschreiben. "
    "Wenn der Nutzer ein Bild, ein Dokument oder ein PDF hochlädt, geht dessen Inhalt oder "
    "eine Textzusammenfassung als Nachricht in dieses Gespräch ein."
)


def trim_messages(messages: list[dict], max_chars: int = 10000) -> list[dict]:
    """Retain recent whole turns within a conservative context character budget.

    Preserves tool round-trips (assistant tool_calls + matching tool result)
    and vision attachments (an "images" field) intact instead of reducing
    every kept message down to a bare role/content pair.
    """
    system = [dict(m) for m in messages if m["role"] == "system"][:1]
    if system:
        system[0]["content"] = system[0]["content"][: max_chars // 2]
    budget = max_chars - sum(len(m["content"]) for m in system)
    turns = []
    for message in reversed(messages):
        if message["role"] not in ("user", "assistant", "tool"):
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        if not text and not message.get("tool_calls") and not message.get("images"):
            continue
        if len(text) > budget:
            if not turns:
                turns.append({**message, "content": text[-budget:]})
            break
        turns.append(message)
        budget -= len(text)
    turns.reverse()
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return system + turns


def normalize_tool_calls(messages: list[dict]) -> list[dict]:
    """Ollama's native /api/chat rejects tool_calls whose function.arguments
    is a JSON string (400 "Value looks like object..."); it wants an object.
    Pipecat's context stores tool_calls OpenAI-style, arguments as a string,
    so every request has to convert it back before it reaches Ollama.
    """
    normalized = []
    for message in messages:
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            normalized.append(message)
            continue
        new_calls = []
        for call in tool_calls:
            function = call.get("function", {})
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    pass
            new_calls.append({**call, "function": {**function, "arguments": arguments}})
        normalized.append({**message, "tool_calls": new_calls})
    return normalized


def build_request(settings: Settings, messages: list[dict]) -> dict:
    return {
        "model": settings.model,
        "messages": normalize_tool_calls(trim_messages(messages)),
        "think": False,
        "stream": True,
        "keep_alive": -1,
        "options": {
            "num_ctx": settings.context_tokens,
            "num_predict": 256,
            "temperature": 0.6,
        },
    }


def local_origin_allowed(origin: str, port: int = 7860, tailnet_host: str | None = None) -> bool:
    allowed = {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}
    if tailnet_host:
        allowed.add(f"https://{tailnet_host}")
    return origin in allowed
