# -*- coding: utf-8 -*-
"""Tests for OllamaServiceManager auto-start, model verification, and safe ownership cleanup."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.config import Config
from backend.ollama_manager import OllamaServiceManager


class OllamaLifecycleTests(unittest.TestCase):
    def setUp(self):
        OllamaServiceManager._proc = None
        OllamaServiceManager._spawned_by_cookmate = False
        OllamaServiceManager._warmed_up = False
        OllamaServiceManager._warmup_started = False
        OllamaServiceManager._last_error = ""

    def tearDown(self):
        OllamaServiceManager._proc = None
        OllamaServiceManager._spawned_by_cookmate = False

    def test_has_model_normalizes_latest_tag(self):
        with patch.object(
            OllamaServiceManager,
            "list_local_models",
            return_value=(True, ["qwen3.5:4b", "llama3:latest"]),
        ):
            ok_qwen, _ = OllamaServiceManager.has_model("qwen3.5:4b")
            ok_llama, _ = OllamaServiceManager.has_model("llama3")
            missing, _ = OllamaServiceManager.has_model("mistral:7b")

        self.assertTrue(ok_qwen)
        self.assertTrue(ok_llama)
        self.assertFalse(missing)

    def test_ensure_started_reuses_already_running_ollama_without_spawning(self):
        with patch.object(
            OllamaServiceManager,
            "list_local_models",
            return_value=(True, [Config.OLLAMA_MODEL]),
        ), patch.object(OllamaServiceManager, "_spawn_serve") as spawn, \
             patch.object(OllamaServiceManager, "_start_warmup_thread") as warm, \
             patch.object(OllamaServiceManager, "find_ollama_binary", return_value="ollama"):
            status = OllamaServiceManager.ensure_started(background_warm=True)

        spawn.assert_not_called()
        warm.assert_called_once()
        self.assertTrue(status["running"])
        self.assertTrue(status["model_ready"])
        self.assertFalse(status["spawned_by_cookmate"])

    def test_ensure_started_handles_missing_binary_gracefully(self):
        with patch.object(OllamaServiceManager, "list_local_models", return_value=(False, [])), \
             patch.object(OllamaServiceManager, "find_ollama_binary", return_value=None), \
             patch.object(Config, "OLLAMA_AUTO_START", True):
            status = OllamaServiceManager.ensure_started(background_warm=False)

        self.assertFalse(status["running"])
        self.assertFalse(status["binary_found"])
        self.assertEqual(status["error"], "OLLAMA_BINARY_NOT_FOUND")

    def test_shutdown_if_owned_never_kills_external_daemon(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        OllamaServiceManager._proc = fake_proc
        OllamaServiceManager._spawned_by_cookmate = False

        OllamaServiceManager.shutdown_if_owned()
        fake_proc.terminate.assert_not_called()

        OllamaServiceManager._proc = fake_proc
        OllamaServiceManager._spawned_by_cookmate = True
        OllamaServiceManager.shutdown_if_owned()
        fake_proc.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
