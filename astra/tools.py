"""LLM-callable tools. Each tool owns its handler; server.py only wires in
per-session dependencies (notify, media_store) and hands the result to pipecat.
"""

import uuid
from collections.abc import Callable

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from astra.articles import ArticleError, read_article
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
        notify(
            {
                "type": "tool_result",
                "text": "\n".join(f"- ({entry.source}) {entry.title}" for entry in entries),
                "items": [
                    {"source": e.source, "title": e.title, "link": e.link} for e in entries
                ],
            }
        )
        await params.result_callback(
            {
                "status": "ok",
                "headlines": [
                    {"source": e.source, "title": e.title, "summary": e.summary, "link": e.link}
                    for e in entries
                ],
            }
        )

    async def handle_read_article(params):
        url = params.arguments.get("url", "")
        notify({"type": "activity", "text": "Astra liest den Artikel …"})
        notify({"type": "tool_start", "text": f'Lade Artikel: "{url}"'})
        try:
            text = await read_article(url)
        except ArticleError as exc:
            notify({"type": "activity", "text": "Artikel konnte nicht geladen werden."})
            notify({"type": "tool_error", "text": str(exc)})
            await params.result_callback({"error": str(exc)})
            return
        notify({"type": "tool_result", "text": text[:800]})
        await params.result_callback({"status": "ok", "text": text})

    read_article_schema = FunctionSchema(
        name="read_article",
        description=(
            "Lade eine Artikel-URL (z.B. aus einem vorherigen read_news-Ergebnis) und lies "
            "den vollständigen Artikeltext. Rufe dieses Werkzeug auf, wenn der Nutzer zu "
            "einer bereits genannten Schlagzeile mehr Details wissen will — erfinde selbst "
            "keine Details. Fasse den Text danach mündlich in eigenen Worten zusammen, "
            "lies ihn nicht roh vor."
        ),
        properties={
            "url": {
                "type": "string",
                "description": "Die 'link'-URL des Artikels aus dem read_news-Ergebnis.",
            },
        },
        required=["url"],
        handler=handle_read_article,
    )

    read_news_schema = FunctionSchema(
        name="read_news",
        description=(
            "Lies aktuelle Schlagzeilen aus kuratierten deutschen RSS-Feeds zu einem "
            "Themenbereich vor. Rufe dieses Werkzeug sofort auf, wenn der Nutzer nach "
            "aktuellen Nachrichten, News oder was gerade in einem Themenbereich passiert, "
            "fragt — erfinde selbst keine Nachrichten und kündige den Abruf nicht nur an. "
            "Fasse die zurückgegebenen Schlagzeilen danach mündlich in eigenen Worten "
            "zusammen, statt sie roh vorzulesen."
        ),
        properties={
            "topic": {
                "type": "string",
                "enum": list(TOPICS),
                "description": (
                    "'tech' für Technologie & KI, 'nachrichten' für allgemeine "
                    "Tagesnachrichten, 'wirtschaft' für Wirtschaftsnews, 'hilden' für "
                    "lokale Nachrichten aus Hilden."
                ),
            },
        },
        required=["topic"],
        handler=handle_read_news,
    )

    generate_image_schema = FunctionSchema(
        name="generate_image",
        description=(
            "Erzeuge ein Bild anhand einer Beschreibung und zeige es dem Nutzer sofort an. "
            "Rufe dieses Werkzeug auf, sobald der Nutzer ein Bild, eine Grafik oder eine "
            "Illustration möchte — beschreibe das Bild nicht nur in Worten, erzeuge es "
            "tatsächlich."
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
    return ToolsSchema(
        standard_tools=[generate_image_schema, read_news_schema, read_article_schema]
    )
