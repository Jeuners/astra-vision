"""Deterministic keyword triggers that call an already-registered tool's
handler directly, bypassing the LLM's own decision to call it. Exists
because read_news, measured, is only called by the LLM in ~15-20% of
matching requests once generate_image and read_article also compete for
its attention — a simple keyword match is ~100% reliable for the same job.
"""

import json
import re
import uuid

from astra.feeds import TOPICS

_NEWS_WORDS = ("nachrichten", "news")
_TOPIC_ALIASES = {
    "hilden": "hilden",
    "technik": "tech",
    "tech": "tech",
    "ki": "tech",
    "wirtschaft": "wirtschaft",
}

_ARTICLE_WORDS = ("artikel", "schlagzeile")
_NUMBER_WORDS = {
    "eins": 1, "eine": 1, "einen": 1, "erste": 1, "ersten": 1, "erster": 1,
    "zwei": 2, "zweite": 2, "zweiten": 2, "zweiter": 2,
    "drei": 3, "dritte": 3, "dritten": 3, "dritter": 3,
    "vier": 4, "vierte": 4, "vierten": 4, "vierter": 4,
    "fünf": 5, "fünfte": 5, "fünften": 5, "fünfter": 5,
    "sechs": 6, "sechste": 6, "sechsten": 6, "sechster": 6,
    "sieben": 7, "siebte": 7, "siebten": 7, "siebter": 7,
    "acht": 8, "achte": 8, "achten": 8, "achter": 8,
    "neun": 9, "neunte": 9, "neunten": 9, "neunter": 9,
    "zehn": 10, "zehnte": 10, "zehnten": 10, "zehnter": 10,
}  # fmt: skip


def detect_news_topic(text: str) -> str | None:
    """Return a configured feed topic if `text` looks like a news request."""
    lowered = text.lower()
    if not any(word in lowered for word in _NEWS_WORDS):
        return None
    for alias, topic in _TOPIC_ALIASES.items():
        if alias in lowered and topic in TOPICS:
            return topic
    return "nachrichten" if "nachrichten" in TOPICS else None


def detect_article_reference(text: str) -> int | None:
    """Return the 1-based article number if `text` asks for one, e.g.
    "Artikel 2", "Artikel Nummer drei", "zweiter Artikel", "Detail zu
    Schlagzeile 4". Resolution against the last shown headlines is the
    caller's job — this only extracts the number.
    """
    lowered = text.lower()
    if not any(word in lowered for word in _ARTICLE_WORDS):
        return None
    match = re.search(r"(?:artikel|schlagzeile)\D{0,15}(\d+)", lowered)
    if match:
        return int(match.group(1))
    for word, number in _NUMBER_WORDS.items():
        if re.search(rf"(?:artikel|schlagzeile)\D{{0,15}}{word}\b", lowered):
            return number
        if re.search(rf"\b{word}\D{{0,15}}(?:artikel|schlagzeile)", lowered):
            return number
    return None


async def trigger_tool(context, tool_name: str, arguments: dict) -> dict | None:
    """Call an already-registered tool's handler directly, then inject the
    round-trip into `context` so the LLM's next completion already sees it
    as answered instead of having to decide to call the tool itself.
    Returns the tool's result dict (or None if the tool wasn't found).
    """
    tools = getattr(context.tools, "standard_tools", None) or []
    schema = next((t for t in tools if t.name == tool_name), None)
    if schema is None:
        return None

    call_id = f"trigger_{uuid.uuid4().hex[:8]}"
    captured: dict = {}

    class _DirectParams:
        pass

    params = _DirectParams()
    params.arguments = arguments

    async def result_callback(result, *, properties=None):
        captured["result"] = result
        context.add_messages(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": arguments},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                },
            ]
        )

    params.result_callback = result_callback
    await schema.handler(params)
    return captured.get("result")
