import pytest

import astra.tools as tools_module
from astra.comfyui import ComfyUIError
from astra.core import Settings


class FakeFunctionCallParams:
    """Stand-in for pipecat's FunctionCallParams: only what the handler touches."""

    def __init__(self, arguments):
        self.arguments = arguments
        self.results = []

    async def result_callback(self, result, *, properties=None):
        self.results.append(result)


@pytest.mark.asyncio
async def test_generate_image_tool_stores_media_and_notifies(monkeypatch):
    async def fake_generate_image(endpoint, prompt, **kwargs):
        assert endpoint == "http://fake-comfyui"
        assert prompt == "a cat"
        return b"png-bytes"

    monkeypatch.setattr(tools_module, "generate_image", fake_generate_image)

    notifications = []
    media_store: dict[str, bytes] = {}
    schema = tools_module.build_tools(
        Settings(comfyui_url="http://fake-comfyui"), notifications.append, media_store
    ).standard_tools[0]

    params = FakeFunctionCallParams({"prompt": "a cat"})
    await schema.handler(params)

    assert len(media_store) == 1
    image_id, image_bytes = next(iter(media_store.items()))
    assert image_bytes == b"png-bytes"
    assert [n["type"] for n in notifications] == ["activity", "tool_start", "image"]
    assert "a cat" in notifications[1]["text"]
    assert notifications[2] == {"type": "image", "url": f"/api/media/{image_id}"}
    assert params.results[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_generate_image_tool_reports_comfyui_errors_without_storing_media(monkeypatch):
    async def failing_generate_image(endpoint, prompt, **kwargs):
        raise ComfyUIError("ComfyUI ist nicht erreichbar.")

    monkeypatch.setattr(tools_module, "generate_image", failing_generate_image)

    notifications = []
    media_store: dict[str, bytes] = {}
    schema = tools_module.build_tools(
        Settings(comfyui_url="http://fake-comfyui"), notifications.append, media_store
    ).standard_tools[0]

    params = FakeFunctionCallParams({"prompt": "a cat"})
    await schema.handler(params)

    assert media_store == {}
    assert "error" in params.results[0]
    assert [n["type"] for n in notifications] == [
        "activity",
        "tool_start",
        "activity",
        "tool_error",
    ]
