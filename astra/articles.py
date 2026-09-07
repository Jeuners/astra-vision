"""Fetch a web page and extract its clean article text. Knows nothing about
the voice pipeline or where the URL came from.
"""

import asyncio

import httpx
import trafilatura

USER_AGENT = "Mozilla/5.0 (compatible; AstraVoice/1.0; +https://github.com/Jeuners/astra-vision)"


class ArticleError(Exception):
    """Raised when a page can't be fetched or no article text could be extracted."""


async def read_article(url: str, *, max_chars: int = 4000) -> str:
    """Fetch `url` and return its main article text, stripped of navigation,
    ads, and other boilerplate. Extraction runs in a thread since trafilatura
    is CPU-bound and synchronous.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ArticleError(f"Seite nicht erreichbar: {exc}") from exc

    text = await asyncio.to_thread(
        trafilatura.extract, response.text, include_comments=False, include_tables=False
    )
    if not text or not text.strip():
        raise ArticleError("Auf der Seite wurde kein lesbarer Artikeltext gefunden.")
    return text.strip()[:max_chars]
