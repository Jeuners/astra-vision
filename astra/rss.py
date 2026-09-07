"""Async reader for the curated RSS/Atom feeds. Knows nothing about the voice pipeline."""

import asyncio
import re
from dataclasses import dataclass

import feedparser
import httpx

from astra.feeds import FEEDS

USER_AGENT = "Mozilla/5.0 (compatible; AstraVoice/1.0; +https://github.com/Jeuners/astra-vision)"


class RSSError(Exception):
    """Raised when no feed for a topic could be read."""


@dataclass(frozen=True)
class Entry:
    source: str
    title: str
    summary: str
    link: str


def _clean_summary(html: str, max_chars: int = 220) -> str:
    text = re.sub(r"<[^>]+>", "", html or "").strip()
    return text[:max_chars]


async def _fetch_one(client: httpx.AsyncClient, feed: dict, per_feed: int) -> list[Entry]:
    try:
        response = await client.get(feed["url"])
        response.raise_for_status()
    except httpx.HTTPError:
        return []
    parsed = feedparser.parse(response.content)
    return [
        Entry(
            source=feed["name"],
            title=item.get("title", "").strip(),
            summary=_clean_summary(item.get("summary", "")),
            link=item.get("link", ""),
        )
        for item in parsed.entries[:per_feed]
    ]


async def read_topic(topic: str, *, per_feed: int = 4, total: int = 10) -> list[Entry]:
    """Fetch the latest entries for one configured topic, feeds in parallel."""
    feeds = FEEDS.get(topic)
    if not feeds:
        raise RSSError(f"Unbekanntes Thema: {topic}")
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=10, follow_redirects=True
    ) as client:
        results = await asyncio.gather(*(_fetch_one(client, feed, per_feed) for feed in feeds))
    entries = [entry for group in results for entry in group]
    if not entries:
        raise RSSError(f'Keine Feeds für "{topic}" waren erreichbar.')
    return entries[:total]
