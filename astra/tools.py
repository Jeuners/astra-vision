"""LLM-callable tools. Each tool owns its handler; server.py only wires in
per-session dependencies (notify, media_store) and hands the result to pipecat.
"""

import uuid
from collections.abc import Callable

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from astra.comfyui import ComfyUIError, generate_image
from astra.core import Settings
from astra.feeds import TOPICS
from astra.rss import RSSError, read_topic


def build_tools(config: Settings, notify: Callable[[dict], None], media_store: dict[str, bytes]) -> ToolsSchema:
    """Assemble the tool set available to the LLM for one session."""

    async def handle_generate_image(params):
        prompt = params.arguments.get("prompt", "")
        notify({"type": "activity", "text": "Astra erzeugt ein Bild …"})
        notify({"type": "tool_start", "text": f'Anfrage an ComfyUI: "{prompt}"'})
        try:
            image = await generate_image(config.comfyui_url, prompt)
        except ComfyUIError as exc:
            notify({"type": "activity", "text": "Bilderzeugung fehlgeschlagen."})
            notify({"type": "tool_error", "text": f"ComfyUI-Anfrage fehlgeschlagen: {exc}"})
            await params.result_callback({"error": str(exc)})
            return
        image_id = uuid.uuid4().hex
        media_store[image_id] = image
        notify({"type": "image", "url": f"/api/media/{image_id}"})
        await params.result_callback(
            {"status": "ok", "message": "Bild wurde erzeugt und dem Nutzer angezeigt."}
        )

    async def handle_read_news(params):
        topic = params.arguments.get("topic", "")
        notify({"type": "activity", "text": "Astra liest Nachrichten …"})
        notify({"type": "tool_start", "text": f'Lese RSS-Feeds: "{topic}"'})
        try:
            entries = await read_topic(topic)
        except RSSError as exc:
            notify({"type": "activity", "text": "Nachrichten konnten nicht geladen werden."})
            notify({"type": "tool_error", "text": str(exc)})
            await params.result_callback({"error": str(exc)})
            return
        headlines = "\n".join(f"- ({entry.source}) {entry.title}" for entry in entries)
        notify({"type": "tool_result", "text": headlines})
        await params.result_callback(
            {
                "status": "ok",
                "headlines": [
                    {"source": e.source, "title": e.title, "summary": e.summary, "link": e.link}
                    for e in entries
                ],
            }
        )

    read_news_schema = FunctionSchema(
        name="read_news",
        description=(
            "Lies aktuelle Schlagzeilen aus kuratierten deutschen RSS-Feeds zu einem "
            "Themenbereich vor. Nutze dieses Werkzeug, wenn der Nutzer nach aktuellen "
            "Nachrichten, News oder was gerade in einem Themenbereich passiert, fragt."
        ),
        properties={
            "topic": {
                "type": "string",
                "enum": list(TOPICS),
                "description": (
                    "'tech' für Technologie & KI, 'nachrichten' für allgemeine "
                    "Tagesnachrichten, 'wirtschaft' für Wirtschaftsnews."
                ),
            },
        },
        required=["topic"],
        handler=handle_read_news,
    )

    generate_image_schema = FunctionSchema(
        name="generate_image",
        description=(
            "Erzeuge ein Bild anhand einer Beschreibung und zeige es dem Nutzer an. "
            "Nutze dieses Werkzeug, wenn der Nutzer explizit ein Bild, eine Grafik "
            "oder eine Illustration wünscht."
        ),
        properties={
            "prompt": {
                "type": "string",
                "description": (
                    "Konkrete, szenenorientierte Bildbeschreibung auf Englisch, "
                    "mit Hinweisen zu Licht und Kamera, z.B. "
                    "'close-up, cinematic light, warm tones'."
                ),
            },
        },
        required=["prompt"],
        handler=handle_generate_image,
    )
    return ToolsSchema(standard_tools=[generate_image_schema, read_news_schema])
