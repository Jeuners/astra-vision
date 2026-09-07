"""Async client for a local ComfyUI server. Knows nothing about the voice pipeline."""

import asyncio
import json
import random
import time
from pathlib import Path

import httpx

WORKFLOW_PATH = Path(__file__).resolve().parent / "comfyui_workflow.json"
SAVE_NODE = "9"
PROMPT_NODE = "57:27"
SIZE_NODE = "57:13"
SEED_NODE = "57:3"


class ComfyUIError(Exception):
    """Raised when ComfyUI is unreachable or fails to produce an image."""


async def generate_image(
    endpoint: str,
    prompt: str,
    *,
    width: int = 1024,
    height: int = 1024,
    timeout: float = 120.0,
) -> bytes:
    """Generate one PNG via the z-image-turbo workflow and return its raw bytes."""
    workflow = json.loads(WORKFLOW_PATH.read_text())
    workflow[PROMPT_NODE]["inputs"]["text"] = prompt
    workflow[SIZE_NODE]["inputs"]["width"] = width
    workflow[SIZE_NODE]["inputs"]["height"] = height
    workflow[SEED_NODE]["inputs"]["seed"] = random.randint(0, 2**32 - 1)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(f"{endpoint}/prompt", json={"prompt": workflow})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"ComfyUI ist nicht erreichbar: {exc}") from exc
        prompt_id = response.json()["prompt_id"]

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = await client.get(f"{endpoint}/history/{prompt_id}")
            history.raise_for_status()
            data = history.json().get(prompt_id)
            if data:
                images = data.get("outputs", {}).get(SAVE_NODE, {}).get("images", [])
                if images:
                    image = images[0]
                    view = await client.get(
                        f"{endpoint}/view",
                        params={
                            "filename": image["filename"],
                            "subfolder": image["subfolder"],
                            "type": image["type"],
                        },
                    )
                    view.raise_for_status()
                    return view.content
            await asyncio.sleep(1)
    raise ComfyUIError("Zeitüberschreitung beim Warten auf das generierte Bild.")
