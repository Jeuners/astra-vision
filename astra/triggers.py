"""Deterministic keyword triggers that call an already-registered tool's
handler directly, bypassing the LLM's own decision to call it. Exists
because read_news, measured, is only called by the LLM in ~15-20% of
matching requests once generate_image and read_article also compete for
its attention — a simple keyword match is ~100% reliable for the same job.
"""

import json
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


def detect_news_topic(text: str) -> str | None:
    """Return a configured feed topic if `text` looks like a news request."""
    lowered = text.lower()
    if not any(word in lowered for word in _NEWS_WORDS):
        return None
    for alias, topic in _TOPIC_ALIASES.items():
        if alias in lowered and topic in TOPICS:
            return topic
    return "nachrichten" if "nachrichten" in TOPICS else None


async def trigger_tool(context, tool_name: str, arguments: dict) -> None:
    """Call an already-registered tool's handler directly, then inject the
    round-trip into `context` so the LLM's next completion already sees it
    as answered instead of having to decide to call the tool itself.
    """
    tools = getattr(context.tools, "standard_tools", None) or []
    schema = next((t for t in tools if t.name == tool_name), None)
    if schema is None:
        return

    call_id = f"trigger_{uuid.uuid4().hex[:8]}"

    class _DirectParams:
        pass

    params = _DirectParams()
    params.arguments = arguments

    async def result_callback(result, *, properties=None):
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
