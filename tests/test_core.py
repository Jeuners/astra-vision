import unittest

from astra.core import (
    Settings,
    build_request,
    local_origin_allowed,
    normalize_tool_calls,
    trim_messages,
)


class CoreTests(unittest.TestCase):
    def test_thinking_is_disabled_in_every_native_request(self):
        request = build_request(Settings(), [{"role": "user", "content": "Hallo"}])
        self.assertIs(request["think"], False)
        self.assertIs(request["stream"], True)
        self.assertEqual(request["model"], "qwen3.5:latest")
        self.assertNotIn("think", request["options"])
        self.assertEqual(request["options"]["num_ctx"], 4096)

    def test_history_stays_bounded_and_preserves_system_and_latest_user(self):
        messages = [{"role": "system", "content": "Deutsch"}]
        for i in range(40):
            messages.extend(
                [
                    {"role": "user", "content": f"Frage {i}"},
                    {"role": "assistant", "content": "Antwort " * 100},
                ]
            )
        messages.append({"role": "user", "content": "Neueste Frage"})
        trimmed = trim_messages(messages, max_chars=5000)
        self.assertEqual(trimmed[0], messages[0])
        self.assertEqual(trimmed[1]["role"], "user")
        self.assertEqual(trimmed[-1], messages[-1])
        self.assertLessEqual(sum(len(m["content"]) for m in trimmed), 5000)
        self.assertEqual(len(messages), 82)

    def test_rejects_foreign_web_origins(self):
        self.assertTrue(local_origin_allowed("http://localhost:7860"))
        self.assertTrue(local_origin_allowed("http://127.0.0.1:7860"))
        self.assertFalse(local_origin_allowed("https://evil.example"))
        self.assertFalse(local_origin_allowed("http://localhost.evil.example:7860"))
        self.assertFalse(local_origin_allowed("null"))

    def test_huge_last_message_is_bounded(self):
        trimmed = trim_messages(
            [
                {"role": "system", "content": "Deutsch"},
                {"role": "user", "content": "x" * 20000},
            ],
            max_chars=5000,
        )
        self.assertLessEqual(sum(len(m["content"]) for m in trimmed), 5000)

    def test_tool_round_trip_survives_trimming(self):
        messages = [
            {"role": "system", "content": "Deutsch"},
            {"role": "user", "content": "Zeig mir ein Bild von einer Katze."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "generate_image", "arguments": {}}}],
            },
            {"role": "tool", "content": '{"status": "ok"}', "tool_call_id": "call_1"},
            {"role": "assistant", "content": "Fertig, schau mal!"},
        ]
        trimmed = trim_messages(messages, max_chars=5000)
        roles = [m["role"] for m in trimmed]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        self.assertEqual(trimmed[2]["tool_calls"][0]["function"]["name"], "generate_image")
        self.assertEqual(trimmed[3]["tool_call_id"], "call_1")

    def test_tool_call_string_arguments_are_normalized_to_an_object(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "generate_image", "arguments": '{"prompt": "a cat"}'},
                    }
                ],
            }
        ]
        normalized = normalize_tool_calls(messages)
        self.assertEqual(
            normalized[0]["tool_calls"][0]["function"]["arguments"], {"prompt": "a cat"}
        )
        # The original message is untouched (immutable transform).
        self.assertIsInstance(messages[0]["tool_calls"][0]["function"]["arguments"], str)

    def test_build_request_normalizes_tool_call_arguments_end_to_end(self):
        messages = [
            {"role": "user", "content": "Erzeuge ein Bild."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "generate_image", "arguments": '{"prompt": "a cat"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"status": "ok"}'},
        ]
        request = build_request(Settings(), messages)
        tool_call_message = next(m for m in request["messages"] if m.get("tool_calls"))
        self.assertIsInstance(tool_call_message["tool_calls"][0]["function"]["arguments"], dict)

    def test_image_attachment_survives_trimming(self):
        messages = [
            {"role": "system", "content": "Deutsch"},
            {
                "role": "user",
                "content": '[Hochgeladenes Bild "katze.png"]',
                "images": ["base64data"],
            },
        ]
        trimmed = trim_messages(messages, max_chars=5000)
        self.assertEqual(trimmed[1]["images"], ["base64data"])


if __name__ == "__main__":
    unittest.main()
