# -*- coding: utf-8 -*-
"""Tests for Gemini smart model resolution, quote-stripping, discovery caching, and secret safety."""

from __future__ import annotations

import types as py_types
import unittest
from unittest.mock import MagicMock, patch

from backend import gemini_manager
from backend.config import Config, _clean_secret


class GeminiSmartResolverTests(unittest.TestCase):
    def setUp(self):
        gemini_manager.reset_model_cache()

    def tearDown(self):
        gemini_manager.reset_model_cache()

    def test_clean_secret_strips_whitespace_and_matching_quotes(self):
        self.assertEqual(_clean_secret("  'test-key-123'  "), "test-key-123")
        self.assertEqual(_clean_secret('  "test-key-123" '), "test-key-123")
        self.assertEqual(_clean_secret("test-key-123"), "test-key-123")

    def test_discovery_filters_non_text_models_and_caches_for_30_minutes(self):
        fake_models = [
            py_types.SimpleNamespace(name="models/gemini-2.5-flash-tts", supported_actions=["generateContent"]),
            py_types.SimpleNamespace(name="models/gemini-2.5-flash-image", supported_actions=["generateContent"]),
            py_types.SimpleNamespace(name="models/gemini-omni-1.2-flash", supported_actions=["generateContent"]),
            py_types.SimpleNamespace(name="models/gemini-embedding-001", supported_actions=["embedContent"]),
            py_types.SimpleNamespace(name="models/gemini-3.1-flash-lite", supported_actions=["generateContent"]),
            py_types.SimpleNamespace(name="models/gemini-3-flash-preview", supported_actions=["generateContent"]),
        ]
        client = MagicMock()
        client.models.list.return_value = fake_models

        with patch.multiple(Config, GEMINI_API_KEY="unit-test-secret-key-xyz", GEMINI_API_KEY_SOURCE="UNIT_TEST"):
            first = gemini_manager.discover_available_gemini_models(client=client)
            second = gemini_manager.discover_available_gemini_models(client=client)

        self.assertEqual(client.models.list.call_count, 1)
        self.assertIn("gemini-3.1-flash-lite", first)
        self.assertIn("gemini-3-flash-preview", first)
        self.assertNotIn("gemini-2.5-flash-tts", first)
        self.assertNotIn("gemini-2.5-flash-image", first)
        self.assertNotIn("gemini-omni-1.2-flash", first)
        self.assertEqual(first, second)

    def test_runtime_status_never_exposes_api_key(self):
        secret = "SUPER_SECRET_SHOULD_NEVER_LEAK_999"
        with patch.multiple(
            Config,
            GEMINI_API_KEY=secret,
            GEMINI_API_KEY_SOURCE="UNIT_TEST",
            GEMINI_PRIMARY_MODEL="gemini-2.5-flash",
            GEMINI_FALLBACK_MODEL="gemini-2.5-flash-lite",
        ):
            status = gemini_manager.get_gemini_runtime_status()
        self.assertTrue(status["configured"])
        self.assertNotIn(secret, str(status))
        self.assertEqual(status["sdk_status"], "READY")

    def test_smart_failover_recovers_via_discovered_model(self):
        class Fake404(Exception):
            code = 404

        calls: list[str] = []

        def fake_generate(model, contents, config):
            calls.append(model)
            if model == "gemini-3.1-flash-lite":
                return py_types.SimpleNamespace(text="Cá kho mặn có thể thêm nước dừa tươi và kho nhỏ lửa.")
            raise Fake404("404 NOT_FOUND")

        fake_client = MagicMock()
        fake_client.models.list.return_value = [
            py_types.SimpleNamespace(name="models/gemini-3.1-flash-lite", supported_actions=["generateContent"]),
        ]
        fake_client.models.generate_content.side_effect = fake_generate

        with patch.multiple(
            Config,
            GEMINI_API_KEY="unit-test-failover-key",
            GEMINI_API_KEY_SOURCE="UNIT_TEST",
            GEMINI_PRIMARY_MODEL="gemini-3.6-flash",
            GEMINI_FALLBACK_MODEL="gemini-4-hydrogen",
            GEMINI_MAX_RETRIES=0,
        ), patch("backend.gemini_manager._build_client", return_value=fake_client):
            result = gemini_manager.generate_ai_response("Cá kho bị mặn xử lý sao?")

        self.assertTrue(result["success"])
        self.assertEqual(result["model_used"], "gemini-3.1-flash-lite")
        self.assertTrue(result["fallback_used"])
        self.assertNotIn("gemini-4-hydrogen", calls)  # skipped second broken legacy model
        self.assertIn("nước dừa tươi", result["response"])


if __name__ == "__main__":
    unittest.main()
