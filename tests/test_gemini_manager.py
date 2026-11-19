import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.config import Config
from backend.gemini_manager import (
    GeminiConfigurationError,
    GeminiInputError,
    GeminiServiceUnavailable,
    _build_client,
    generate_ai_response,
)


class FakeApiError(Exception):
    def __init__(self, status, details=None):
        super().__init__("private SDK error text must never be logged")
        self.code = status
        self.details = details or {}
        self.status = self.details.get("error", {}).get("status")
        self.response = SimpleNamespace(status_code=status, headers={})


def response(text="Món ăn ngon."):
    return SimpleNamespace(text=text, candidates=[])


class GeminiManagerTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.multiple(
            Config,
            GEMINI_API_KEY="unit-test-key",
            GEMINI_API_KEY_SOURCE="UNIT_TEST",
            GEMINI_API_KEY_CONFLICT=False,
            GEMINI_KEY_SOURCES=("UNIT_TEST",),
            GEMINI_PRIMARY_MODEL="gemini-3.6-flash",
            GEMINI_FALLBACK_MODEL="gemini-4-hydrogen",
            GEMINI_TIMEOUT=30,
            GEMINI_MAX_RETRIES=0,
        )
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_primary_success_does_not_call_fallback(self):
        with patch("backend.gemini_manager._generate_once", return_value=response()) as call:
            result = generate_ai_response("Cách nấu trứng?")
        self.assertEqual(result["model_used"], "gemini-3.6-flash")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(call.call_count, 1)
        self.assertFalse(call.call_args.kwargs["fallback"])

    def test_primary_503_uses_fallback(self):
        with patch("backend.gemini_manager._generate_once", side_effect=[FakeApiError(503), response("Fallback." )]) as call:
            result = generate_ai_response("Cách nấu trứng?")
        self.assertEqual([item.args[0] for item in call.call_args_list], ["gemini-3.6-flash", "gemini-4-hydrogen"])
        self.assertEqual(result["response"], "Fallback.")
        self.assertTrue(result["fallback_used"])

    def test_primary_429_falls_back_without_unbounded_retry(self):
        with patch("backend.gemini_manager._generate_once", side_effect=[FakeApiError(429), response()]) as call:
            result = generate_ai_response("Món nào dùng cà chua?")
        self.assertEqual(call.call_count, 2)
        self.assertTrue(result["fallback_used"])

    def test_transient_rate_limit_retries_once_then_succeeds(self):
        Config.GEMINI_MAX_RETRIES = 1
        rate_limit = FakeApiError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [{"reason": "RATE_LIMIT_EXCEEDED"}]}})
        with patch("backend.gemini_manager.time.sleep"), \
             patch("backend.gemini_manager._generate_once", side_effect=[rate_limit, response()]) as call:
            result = generate_ai_response("Món nào dùng cà chua?")
        self.assertEqual(call.call_count, 2)
        self.assertFalse(result["fallback_used"])

    def test_timeout_uses_fallback(self):
        with patch("backend.gemini_manager._generate_once", side_effect=[TimeoutError(), response()]) as call:
            result = generate_ai_response("Cách nấu trứng?")
        self.assertEqual(call.call_count, 2)
        self.assertTrue(result["fallback_used"])

    def test_both_503_return_safe_service_error(self):
        with patch("backend.gemini_manager._generate_once", side_effect=[FakeApiError(503), FakeApiError(503)]):
            with self.assertRaises(GeminiServiceUnavailable) as caught:
                generate_ai_response("Cách nấu trứng?")
        self.assertEqual(caught.exception.error_code, "AI_SERVICE_UNAVAILABLE")
        self.assertNotIn("SDK error", str(caught.exception))

    def test_both_429_return_safe_service_error(self):
        with patch("backend.gemini_manager._generate_once", side_effect=[FakeApiError(429), FakeApiError(429)]):
            with self.assertRaises(GeminiServiceUnavailable):
                generate_ai_response("Cách nấu trứng?")

    def test_fallback_authentication_error_keeps_its_specific_reason(self):
        fallback_error = GeminiConfigurationError(403, reason="PERMISSION_DENIED", source="UNIT_TEST")
        with patch("backend.gemini_manager._generate_once", side_effect=[FakeApiError(503), fallback_error]):
            with self.assertRaises(GeminiConfigurationError) as caught:
                generate_ai_response("Cách nấu trứng?")
        self.assertEqual(caught.exception.reason, "PERMISSION_DENIED")
        self.assertEqual(caught.exception.error_code, "AI_PERMISSION_DENIED")

    def test_invalid_api_key_does_not_fallback(self):
        invalid_key = FakeApiError(400, {"error": {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}})
        with self.assertLogs("backend.gemini_manager", level="ERROR") as captured, \
             patch("backend.gemini_manager._generate_once", side_effect=invalid_key) as call:
            with self.assertRaises(GeminiConfigurationError):
                generate_ai_response("Cách nấu trứng?")
        self.assertEqual(call.call_count, 1)
        self.assertIn("Reason: INVALID_API_KEY Source: UNIT_TEST", "\n".join(captured.output))

    def test_401_and_403_are_reported_as_distinct_configuration_errors(self):
        for error, expected in ((FakeApiError(401), "EXPIRED_OR_REVOKED_API_KEY"),
                                (FakeApiError(403, {"error": {"status": "PERMISSION_DENIED"}}), "PERMISSION_DENIED")):
            with self.subTest(reason=expected), patch("backend.gemini_manager._generate_once", side_effect=error):
                with self.assertRaises(GeminiConfigurationError) as caught:
                    generate_ai_response("Cách nấu trứng?")
            self.assertEqual(caught.exception.reason, expected)

    def test_missing_key_is_detected_before_client_creation(self):
        Config.GEMINI_API_KEY = ""
        with patch("google.genai.Client") as client_factory:
            with self.assertRaises(GeminiConfigurationError) as caught:
                _build_client(fallback=True)
        self.assertEqual(caught.exception.reason, "MISSING_API_KEY")
        client_factory.assert_not_called()

    def test_invalid_input_does_not_call_a_model(self):
        with patch("backend.gemini_manager._generate_once") as call:
            with self.assertRaises(GeminiInputError):
                generate_ai_response(" ")
            with self.assertRaises(GeminiInputError):
                generate_ai_response("x" * 2001)
        call.assert_not_called()

    def test_response_is_sequential_and_keeps_history_and_system_instruction(self):
        history = [{"sender": "USER", "text": "Tôi có trứng."}, {"sender": "AI", "text": "Bạn muốn làm món gì?"}]
        with patch("backend.gemini_manager._generate_once", side_effect=[FakeApiError(503), response()]) as call:
            result = generate_ai_response("Món trứng nhanh?", history, "Chỉ tư vấn món ăn.")
        self.assertTrue(result["fallback_used"])
        primary_args, fallback_args = call.call_args_list
        self.assertEqual(primary_args.args[1], fallback_args.args[1])
        self.assertEqual(primary_args.args[2], "Chỉ tư vấn món ăn.")
        self.assertEqual([item.role for item in primary_args.args[1]], ["user", "model", "user"])
        self.assertFalse(primary_args.kwargs["fallback"])
        self.assertTrue(fallback_args.kwargs["fallback"])

    def test_failure_logs_classify_http_error_without_sdk_text(self):
        with self.assertLogs("backend.gemini_manager", level="INFO") as captured:
            with patch("backend.gemini_manager._generate_once", side_effect=[FakeApiError(503), response()]):
                generate_ai_response("Cách nấu trứng?")
        log_text = "\n".join(captured.output)
        self.assertIn("http_status=503", log_text)
        self.assertIn("service_unavailable", log_text)
        self.assertNotIn("private SDK error text", log_text)
        self.assertNotIn("unit-test-key", log_text)

    def test_primary_and_fallback_clients_use_same_developer_key_and_v1beta(self):
        with patch("google.genai.Client") as client_factory:
            _build_client(fallback=False)
            primary = client_factory.call_args.kwargs
            self.assertEqual(primary["api_key"], "unit-test-key")
            self.assertEqual(primary["http_options"].api_version, "v1beta")

            _build_client(fallback=True)
            fallback = client_factory.call_args.kwargs
            self.assertEqual(fallback["api_key"], "unit-test-key")
            self.assertEqual(fallback["http_options"].api_version, "v1beta")
            for kwargs in (primary, fallback):
                self.assertNotIn("enterprise", kwargs)
                self.assertNotIn("project", kwargs)
                self.assertNotIn("location", kwargs)
        self.assertEqual(client_factory.call_count, 2)

    def test_client_auth_setup_error_is_reported_as_configuration_error(self):
        with patch("google.genai.Client", side_effect=ValueError("private client detail")):
            with self.assertRaises(GeminiConfigurationError) as caught:
                _build_client(fallback=False)
        self.assertNotIn("private client detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
