"""LLM-callable tools. Each tool owns its handler; server.py only wires in
per-session dependencies (notify, media_store) and hands the result to pipecat.
"""

import uuid
from collections.abc import Callable

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from astra.comfyui import ComfyUIError, generate_image
from astra.core import Settings


def build_tools(config: Settings, notify: Callable[[dict], None], media_store: dict[str, bytes]) -> ToolsSchema:
    """Assemble the tool set available to the LLM for one session."""

    async def handle_generate_image(params):
        prompt = params.arguments.get("prompt", "")
        try:
            image = await generate_image(config.comfyui_url, prompt)
        except ComfyUIError as exc:
            await params.result_callback({"error": str(exc)})
            return
        image_id = uuid.uuid4().hex
        media_store[image_id] = image
        notify({"type": "image", "url": f"/api/media/{image_id}"})
        await params.result_callback(
            {"status": "ok", "message": "Bild wurde erzeugt und dem Nutzer angezeigt."}
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
    return ToolsSchema(standard_tools=[generate_image_schema])
