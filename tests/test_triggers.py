import pytest

from astra.triggers import detect_article_reference, detect_news_topic, trigger_tool


def test_detect_article_reference_matches_digit():
    assert detect_article_reference("Hole mir Detail zu Artikel 2") == 2
    assert detect_article_reference("Artikel Nummer 4 bitte") == 4


def test_detect_article_reference_matches_number_words():
    assert detect_article_reference("Erzähl mir mehr zu Artikel zwei") == 2
    assert detect_article_reference("zweiter Artikel bitte") == 2
    assert detect_article_reference("die dritte Schlagzeile interessiert mich") == 3


def test_detect_article_reference_returns_none_without_article_word():
    assert detect_article_reference("Wie ist das Wetter?") is None
    assert detect_article_reference("Erzähl mir die Nachrichten.") is None


def test_detect_news_topic_matches_hilden():
    assert detect_news_topic("Gib mir die aktuellen News Hilden") == "hilden"
    assert detect_news_topic("Erzähl mir die Nachrichten aus Hilden.") == "hilden"


def test_detect_news_topic_matches_tech_aliases():
    assert detect_news_topic("Was gibt es für Nachrichten aus der Technik?") == "tech"
    assert detect_news_topic("News zu KI?") == "tech"


def test_detect_news_topic_falls_back_to_general():
    assert detect_news_topic("Erzähl mir die Nachrichten.") == "nachrichten"


def test_detect_news_topic_returns_none_without_trigger_word():
    assert detect_news_topic("Wie ist das Wetter heute?") is None
    assert detect_news_topic("Erzeuge ein Bild von einer Katze.") is None


class FakeSchema:
    def __init__(self, name, handler):
        self.name = name
        self.handler = handler


class FakeStandardTools:
    def __init__(self, schemas):
        self.standard_tools = schemas


class FakeContext:
    def __init__(self, schemas):
        self.tools = FakeStandardTools(schemas)
        self.messages: list[dict] = []

    def add_messages(self, messages):
        self.messages.extend(messages)


@pytest.mark.asyncio
async def test_trigger_tool_calls_handler_and_injects_round_trip():
    calls = []

    async def handler(params):
        calls.append(params.arguments)
        await params.result_callback({"status": "ok", "headlines": ["a", "b"]})

    context = FakeContext([FakeSchema("read_news", handler)])
    await trigger_tool(context, "read_news", {"topic": "hilden"})

    assert calls == [{"topic": "hilden"}]
    assert len(context.messages) == 2
    assistant_msg, tool_msg = context.messages
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "read_news"
    assert assistant_msg["tool_calls"][0]["function"]["arguments"] == {"topic": "hilden"}
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == assistant_msg["tool_calls"][0]["id"]
    assert "headlines" in tool_msg["content"]


@pytest.mark.asyncio
async def test_trigger_tool_is_a_noop_for_unknown_tool_name():
    context = FakeContext([FakeSchema("read_news", lambda params: None)])
    await trigger_tool(context, "does_not_exist", {})
    assert context.messages == []
