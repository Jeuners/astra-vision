import httpx
import pytest

from astra.articles import ArticleError, read_article

SAMPLE_HTML = b"""<!doctype html>
<html><head><title>Testartikel</title></head>
<body>
<nav>Navigation, sollte nicht im Ergebnis landen</nav>
<article>
<h1>Ein wichtiger Titel</h1>
<p>Dies ist der erste Absatz des eigentlichen Artikeltexts, lang genug fuer
eine sinnvolle Extraktion durch trafilatura, mit mehreren Saetzen.</p>
<p>Und hier folgt ein zweiter Absatz mit weiterem Inhalt, damit die
Extraktion genug Text zum Erkennen des Hauptinhalts hat.</p>
</article>
<footer>Footer-Boilerplate, sollte auch nicht im Ergebnis landen</footer>
</body></html>"""


def _patched_client(monkeypatch, handler):
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_read_article_extracts_main_text(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SAMPLE_HTML)

    _patched_client(monkeypatch, handler)
    text = await read_article("https://example.com/article")

    assert "wichtiger Titel" in text or "erste Absatz" in text
    assert "Navigation" not in text
    assert "Footer-Boilerplate" not in text


@pytest.mark.asyncio
async def test_read_article_respects_max_chars(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SAMPLE_HTML)

    _patched_client(monkeypatch, handler)
    text = await read_article("https://example.com/article", max_chars=20)

    assert len(text) <= 20


@pytest.mark.asyncio
async def test_read_article_raises_when_page_unreachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patched_client(monkeypatch, handler)
    with pytest.raises(ArticleError):
        await read_article("https://example.com/article")


@pytest.mark.asyncio
async def test_read_article_raises_when_no_text_extractable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body></body></html>")

    _patched_client(monkeypatch, handler)
    with pytest.raises(ArticleError):
        await read_article("https://example.com/article")
