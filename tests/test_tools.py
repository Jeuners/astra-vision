import pytest

import astra.tools as tools_module
from astra.articles import ArticleError
from astra.comfyui import ComfyUIError
from astra.core import Settings
from astra.rss import Entry, RSSError


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


def _find(tools, name):
    return next(t for t in tools if t.name == name)


@pytest.mark.asyncio
async def test_read_news_tool_reports_headlines(monkeypatch):
    async def fake_read_topic(topic, **kwargs):
        assert topic == "tech"
        return [
            Entry(source="heise online", title="KI-Durchbruch", summary="...", link="https://x"),
            Entry(source="Golem.de", title="Neuer Chip", summary="...", link="https://y"),
        ]

    monkeypatch.setattr(tools_module, "read_topic", fake_read_topic)

    notifications = []
    schema = _find(
        tools_module.build_tools(Settings(), notifications.append, {}).standard_tools,
        "read_news",
    )

    params = FakeFunctionCallParams({"topic": "tech"})
    await schema.handler(params)

    assert [n["type"] for n in notifications] == ["activity", "tool_start", "tool_result"]
    assert "KI-Durchbruch" in notifications[2]["text"]
    assert "Neuer Chip" in notifications[2]["text"]
    assert notifications[2]["items"] == [
        {"source": "heise online", "title": "KI-Durchbruch", "link": "https://x"},
        {"source": "Golem.de", "title": "Neuer Chip", "link": "https://y"},
    ]
    assert params.results[0]["status"] == "ok"
    assert len(params.results[0]["headlines"]) == 2


@pytest.mark.asyncio
async def test_read_news_tool_reports_rss_errors(monkeypatch):
    async def failing_read_topic(topic, **kwargs):
        raise RSSError('Keine Feeds für "tech" waren erreichbar.')

    monkeypatch.setattr(tools_module, "read_topic", failing_read_topic)

    notifications = []
    schema = _find(
        tools_module.build_tools(Settings(), notifications.append, {}).standard_tools,
        "read_news",
    )

    params = FakeFunctionCallParams({"topic": "tech"})
    await schema.handler(params)

    assert [n["type"] for n in notifications] == [
        "activity",
        "tool_start",
        "activity",
        "tool_error",
    ]
    assert "error" in params.results[0]


@pytest.mark.asyncio
async def test_read_article_tool_reports_extracted_text(monkeypatch):
    async def fake_read_article(url, **kwargs):
        assert url == "https://example.com/story"
        return "Der vollständige Artikeltext."

    monkeypatch.setattr(tools_module, "read_article", fake_read_article)

    notifications = []
    schema = _find(
        tools_module.build_tools(Settings(), notifications.append, {}).standard_tools,
        "read_article",
    )

    params = FakeFunctionCallParams({"url": "https://example.com/story"})
    await schema.handler(params)

    assert [n["type"] for n in notifications] == ["activity", "tool_start", "tool_result"]
    assert notifications[2]["text"] == "Der vollständige Artikeltext."
    assert params.results[0]["status"] == "ok"
    assert params.results[0]["text"] == "Der vollständige Artikeltext."


@pytest.mark.asyncio
async def test_read_article_tool_reports_article_errors(monkeypatch):
    async def failing_read_article(url, **kwargs):
        raise ArticleError("Seite nicht erreichbar.")

    monkeypatch.setattr(tools_module, "read_article", failing_read_article)

    notifications = []
    schema = _find(
        tools_module.build_tools(Settings(), notifications.append, {}).standard_tools,
        "read_article",
    )

    params = FakeFunctionCallParams({"url": "https://example.com/story"})
    await schema.handler(params)

    assert [n["type"] for n in notifications] == [
        "activity",
        "tool_start",
        "activity",
        "tool_error",
    ]
    assert "error" in params.results[0]
