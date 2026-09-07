import httpx
import pytest

import astra.rss as rss_module
from astra.rss import RSSError, read_topic

SAMPLE_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test Feed</title>
<item><title>Erste Meldung</title><description>&lt;p&gt;Kurzer Text&lt;/p&gt;</description><link>https://example.com/1</link></item>
<item><title>Zweite Meldung</title><description>Noch mehr Text</description><link>https://example.com/2</link></item>
</channel></rss>"""


def _patched_client(monkeypatch, handler):
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_read_topic_combines_entries_from_all_feeds(monkeypatch):
    monkeypatch.setitem(
        rss_module.FEEDS,
        "testtopic",
        (
            {"name": "Feed A", "url": "https://feed-a.example/rss"},
            {"name": "Feed B", "url": "https://feed-b.example/rss"},
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SAMPLE_RSS)

    _patched_client(monkeypatch, handler)
    entries = await read_topic("testtopic")

    assert len(entries) == 4
    assert entries[0].title == "Erste Meldung"
    assert entries[0].summary == "Kurzer Text"
    assert entries[0].link == "https://example.com/1"
    assert entries[0].source in ("Feed A", "Feed B")


@pytest.mark.asyncio
async def test_read_topic_skips_unreachable_feeds(monkeypatch):
    monkeypatch.setitem(
        rss_module.FEEDS,
        "testtopic",
        (
            {"name": "Down", "url": "https://down.example/rss"},
            {"name": "Up", "url": "https://up.example/rss"},
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "down" in str(request.url):
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, content=SAMPLE_RSS)

    _patched_client(monkeypatch, handler)
    entries = await read_topic("testtopic")

    assert len(entries) == 2
    assert all(entry.source == "Up" for entry in entries)


@pytest.mark.asyncio
async def test_read_topic_raises_for_unknown_topic():
    with pytest.raises(RSSError):
        await read_topic("does-not-exist")


@pytest.mark.asyncio
async def test_read_topic_raises_when_every_feed_fails(monkeypatch):
    monkeypatch.setitem(
        rss_module.FEEDS,
        "testtopic",
        ({"name": "Down", "url": "https://down.example/rss"},),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patched_client(monkeypatch, handler)
    with pytest.raises(RSSError):
        await read_topic("testtopic")
