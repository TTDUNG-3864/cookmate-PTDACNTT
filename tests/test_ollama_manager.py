import unittest
from email.message import Message
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from backend.config import Config
from backend.ollama_manager import OllamaError, _history_messages, _raise_http_error, generate_ollama_response


class OllamaManagerTests(unittest.TestCase):
    def setUp(self):
        self.profile = patch("backend.ollama_manager._server_profile", return_value=("0.40.16", frozenset({"thinking"})))
        self.profile.start()
        self.addCleanup(self.profile.stop)

    def test_chat_request_uses_top_level_think_false_and_only_returns_content(self):
        response = {"message": {"role": "assistant", "content": "  Cách làm món trứng.  ", "thinking": "private reasoning"}, "eval_count": 7}
        with patch("backend.ollama_manager._request_json", return_value=response) as request, \
             patch.object(Config, "OLLAMA_MODEL", "qwen3.5:4b"):
            # A non-empty thinking field means the server ignored think=false; discard it.
            with self.assertRaises(OllamaError) as raised:
                generate_ollama_response("Cách nấu trứng?", system_instruction="Trả lời tiếng Việt.")
        self.assertEqual(raised.exception.reason, "THINK_FALSE_NOT_HONORED")
        body = request.call_args.args[1]
        self.assertEqual(body["model"], "qwen3.5:4b")
        self.assertIs(body["think"], False)
        self.assertIs(body["stream"], False)
        self.assertNotIn("think", body["options"])

    def test_success_returns_message_content_without_thinking(self):
        response = {"message": {"role": "assistant", "content": "  Món trứng cà chua.  "}, "eval_count": 5, "total_duration": 2_000_000}
        with patch("backend.ollama_manager._request_json", return_value=response):
            result = generate_ollama_response("Tôi có trứng và cà chua.", system_instruction="Trả lời tiếng Việt.")
        self.assertEqual(result["response"], "Món trứng cà chua.")
        self.assertEqual(result["metrics"]["eval_count"], 5)
        self.assertNotIn("thinking", result)

    def test_empty_content_is_invalid(self):
        with patch("backend.ollama_manager._request_json", return_value={"message": {"content": "  "}}):
            with self.assertRaises(OllamaError) as raised:
                generate_ollama_response("Cách nấu trứng?", system_instruction="CookMate")
        self.assertEqual(raised.exception.reason, "EMPTY_CONTENT")

    def test_length_limited_content_is_rejected_as_truncated(self):
        response = {"message": {"content": "Cách nấu món ăn dang dở"}, "done_reason": "length"}
        with patch("backend.ollama_manager._request_json", return_value=response):
            with self.assertRaises(OllamaError) as raised:
                generate_ollama_response("Cách nấu món ăn?", system_instruction="CookMate")
        self.assertEqual(raised.exception.reason, "TRUNCATED_CONTENT")

    def test_history_keeps_only_bounded_recent_turns(self):
        history = []
        for idx in range(6):
            history.extend([{"role": "user", "text": f"u{idx}"}, {"role": "assistant", "text": f"a{idx}"}])
        with patch.object(Config, "CHATBOT_HISTORY_TURNS", 2):
            messages = _history_messages(history)
        self.assertEqual(messages, [
            {"role": "user", "content": "u4"}, {"role": "assistant", "content": "a4"},
            {"role": "user", "content": "u5"}, {"role": "assistant", "content": "a5"},
        ])

    def test_model_without_thinking_capability_is_not_treated_as_configured(self):
        with patch("backend.ollama_manager._server_profile", return_value=("0.39.0", frozenset({"completion"}))), \
             patch("backend.ollama_manager._request_json") as request:
            with self.assertRaises(OllamaError) as raised:
                generate_ollama_response("Cách nấu trứng?", system_instruction="CookMate")
        self.assertEqual(raised.exception.reason, "MODEL_THINKING_CAPABILITY_UNAVAILABLE")
        request.assert_not_called()

    def test_unsupported_think_error_logs_exact_version(self):
        error = HTTPError("http://localhost/api/chat", 400, "Bad Request", Message(), BytesIO(b'{"error":"think parameter is not supported"}'))
        with self.assertLogs("backend.ollama_manager", level="ERROR") as captured:
            with self.assertRaises(OllamaError) as raised:
                _raise_http_error(error, server_version="0.39.1")
        self.assertEqual(raised.exception.reason, "THINK_PARAMETER_UNSUPPORTED")
        self.assertTrue(any("OllamaVersion: 0.39.1" in line for line in captured.output))


if __name__ == "__main__":
    unittest.main()
