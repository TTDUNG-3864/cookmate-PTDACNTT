import unittest
from unittest.mock import patch

from backend.config import (
    Config,
    apply_environment_defaults,
    resolve_demo_mode,
    resolve_gemini_api_key,
    resolve_trust_proxy_headers,
    validate_gemini_configuration,
)


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

    def test_demo_mode_production_ignores_dotenv_true_unless_in_process_env(self):
        self.assertFalse(resolve_demo_mode({"DEMO_MODE": ""}, {"DEMO_MODE": "true"}, development=False))
        self.assertTrue(resolve_demo_mode({"DEMO_MODE": "true"}, {"DEMO_MODE": "false"}, development=False))
        self.assertTrue(resolve_demo_mode({"DEMO_MODE": "false"}, {"DEMO_MODE": "true"}, development=True))
        self.assertFalse(resolve_demo_mode({}, {}, development=True))

    def test_trust_proxy_headers_defaults_false_and_ignores_dotenv_in_production(self):
        self.assertFalse(resolve_trust_proxy_headers({}, {}, development=True))
        self.assertFalse(resolve_trust_proxy_headers({"TRUST_PROXY_HEADERS": ""}, {"TRUST_PROXY_HEADERS": "true"}, development=False))
        self.assertTrue(resolve_trust_proxy_headers({"TRUST_PROXY_HEADERS": "true"}, {"TRUST_PROXY_HEADERS": "false"}, development=False))

    def test_apply_environment_defaults_enforces_production_flags_unless_overridden(self):
        cfg = {
            "APP_ENV": "production",
            "DEMO_MODE": True,
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "TRUST_PROXY_HEADERS": True,
        }
        apply_environment_defaults(cfg, {"APP_ENV": "production"})
        self.assertFalse(cfg["DEMO_MODE"])
        self.assertTrue(cfg["SESSION_COOKIE_SECURE"])
        self.assertEqual(cfg["SESSION_COOKIE_SAMESITE"], "None")
        self.assertFalse(cfg["TRUST_PROXY_HEADERS"])

        explicit = {
            "APP_ENV": "production",
            "DEMO_MODE": True,
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "TRUST_PROXY_HEADERS": True,
        }
        apply_environment_defaults(explicit, dict(explicit))
        self.assertTrue(explicit["DEMO_MODE"])
        self.assertFalse(explicit["SESSION_COOKIE_SECURE"])
        self.assertEqual(explicit["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertTrue(explicit["TRUST_PROXY_HEADERS"])

    def test_apply_environment_defaults_non_development_override_consistent(self):
        with patch("backend.config._PROCESS_ENV", {"DEMO_MODE": "", "TRUST_PROXY_HEADERS": ""}), patch(
            "backend.config._DOTENV", {"DEMO_MODE": "true", "TRUST_PROXY_HEADERS": "true"}
        ):
            staging_cfg = {"APP_ENV": "staging"}
            apply_environment_defaults(staging_cfg, {"APP_ENV": "staging"})
            self.assertEqual(staging_cfg["APP_ENV"], "staging")
            self.assertFalse(staging_cfg["DEMO_MODE"])
            self.assertFalse(staging_cfg["TRUST_PROXY_HEADERS"])
            self.assertFalse(staging_cfg["SESSION_COOKIE_SECURE"])
            self.assertEqual(staging_cfg["SESSION_COOKIE_SAMESITE"], "Lax")

            dev_cfg = {"APP_ENV": "development"}
            apply_environment_defaults(dev_cfg, {"APP_ENV": "development"})
            self.assertTrue(dev_cfg["DEMO_MODE"])
            self.assertTrue(dev_cfg["TRUST_PROXY_HEADERS"])


if __name__ == "__main__":
    unittest.main()
