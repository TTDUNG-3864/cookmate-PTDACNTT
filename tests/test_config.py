import unittest
from unittest.mock import patch

from backend.config import Config, resolve_gemini_api_key, validate_gemini_configuration


class GeminiConfigurationTests(unittest.TestCase):
    def test_development_prefers_project_dotenv_and_detects_conflict(self):
        selected, source, conflict, sources = resolve_gemini_api_key(
            {"GEMINI_API_KEY": "process-one", "GOOGLE_API_KEY": ""},
            {"GEMINI_API_KEY": "dotenv-two", "GOOGLE_API_KEY": ""},
            development=True,
        )
        self.assertEqual(selected, "dotenv-two")
        self.assertEqual(source, "PROJECT_DOTENV:GEMINI_API_KEY")
        self.assertTrue(conflict)
        self.assertEqual(len(sources), 2)

    def test_development_uses_process_when_dotenv_key_is_missing(self):
        selected, source, conflict, _ = resolve_gemini_api_key(
            {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": "process-google"},
            {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""},
            development=True,
        )
        self.assertEqual(selected, "process-google")
        self.assertEqual(source, "PROCESS_ENV:GOOGLE_API_KEY")
        self.assertFalse(conflict)

    def test_production_prefers_system_environment_and_google_alias(self):
        selected, source, conflict, _ = resolve_gemini_api_key(
            {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": "production-google"},
            {"GEMINI_API_KEY": "dotenv-gemini", "GOOGLE_API_KEY": ""},
            development=False,
        )
        self.assertEqual(selected, "production-google")
        self.assertEqual(source, "PROCESS_ENV:GOOGLE_API_KEY")
        self.assertTrue(conflict)

    def test_identical_keys_in_multiple_sources_are_not_a_conflict(self):
        _, _, conflict, _ = resolve_gemini_api_key(
            {"GEMINI_API_KEY": "same-key", "GOOGLE_API_KEY": ""},
            {"GEMINI_API_KEY": "same-key", "GOOGLE_API_KEY": ""},
            development=True,
        )
        self.assertFalse(conflict)

    def test_validation_reports_presence_without_claiming_validity(self):
        with patch.multiple(
            Config,
            GEMINI_API_KEY="not-validated-live",
            GEMINI_API_KEY_SOURCE="UNIT_TEST",
            GEMINI_API_KEY_CONFLICT=False,
            GEMINI_KEY_SOURCES=("UNIT_TEST",),
            GEMINI_PRIMARY_MODEL="gemini-3.6-flash",
            GEMINI_FALLBACK_MODEL="gemini-4-hydrogen",
        ), patch("backend.config.package_version", return_value="3.3.0"):
            result = validate_gemini_configuration()
        self.assertTrue(result["configured"])
        self.assertEqual(result["api_key_status"], "FOUND")
        self.assertEqual(result["api_key_validity"], "UNKNOWN")
        self.assertEqual(result["sdk_status"], "READY")

    def test_validation_distinguishes_missing_key_and_invalid_model(self):
        with patch.multiple(
            Config,
            GEMINI_API_KEY="",
            GEMINI_PRIMARY_MODEL="bad model id",
            GEMINI_FALLBACK_MODEL="gemini-4-hydrogen",
        ), patch("backend.config.package_version", return_value="3.3.0"):
            result = validate_gemini_configuration()
        self.assertFalse(result["configured"])
        self.assertEqual(result["api_key_validity"], "UNKNOWN")
        self.assertIn("MISSING_API_KEY", result["errors"])
        self.assertIn("INVALID_MODEL_ID", result["errors"])


if __name__ == "__main__":
    unittest.main()
