import types as py_types
import unittest
from unittest.mock import patch

from backend.config import Config
from backend.gemini_manager import GeminiConfigurationError
from backend.ollama_manager import OllamaError
from backend.services.chatbot_service import answer_message


class FakeHttpError(Exception):
    def __init__(self, status: int, status_name: str = "RESOURCE_EXHAUSTED"):
        super().__init__("sdk internal error")
        self.code = status
        self.details = {"error": {"status": status_name}}
        self.status = status_name
        self.response = py_types.SimpleNamespace(status_code=status, headers={})


class ChatbotProviderOrderTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "db_status": "AVAILABLE",
            "recipe_search_performed": True,
            "user_stated_ingredients": [],
            "excluded_ingredients": [],
            "database_recipes": [],
            "custom_recipe_allowed": False,
        }

    def test_gemini_primary_2_5_flash_called_first_without_calling_ollama(self):
        with patch.multiple(
            Config,
            GEMINI_API_KEY="configured-key",
            GEMINI_PRIMARY_MODEL="gemini-2.5-flash",
            GEMINI_FALLBACK_MODEL="gemini-2.5-flash-lite",
            CHATBOT_ENABLED=True,
            CHATBOT_RAG_ENABLED=False,
        ), patch("backend.services.chatbot_service._build_database_context", return_value=self.context), \
             patch("backend.gemini_manager._generate_once", return_value=py_types.SimpleNamespace(text="Mẹo luộc trứng lòng đào 6 phút.", candidates=[])) as gem_call, \
             patch("backend.services.chatbot_service.generate_ollama_response") as generate_ollama:
            result = answer_message("Cách luộc trứng lòng đào chuẩn thời gian?")

        self.assertTrue(result["success"])
        self.assertEqual(result["model_used"], "gemini-2.5-flash")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["aiDiagnostics"]["activeProvider"], "gemini")
        self.assertFalse(result["aiDiagnostics"]["geminiFailed"])
        self.assertEqual(gem_call.call_count, 1)
        self.assertEqual(gem_call.call_args.args[0], "gemini-2.5-flash")
        generate_ollama.assert_not_called()

    def test_gemini_primary_429_switches_to_gemini_2_5_flash_lite_before_ollama(self):
        with patch.multiple(
            Config,
            GEMINI_API_KEY="configured-key",
            GEMINI_PRIMARY_MODEL="gemini-2.5-flash",
            GEMINI_FALLBACK_MODEL="gemini-2.5-flash-lite",
            GEMINI_MAX_RETRIES=0,
            CHATBOT_ENABLED=True,
            CHATBOT_RAG_ENABLED=False,
        ), patch("backend.services.chatbot_service._build_database_context", return_value=self.context), \
             patch(
                 "backend.gemini_manager._generate_once",
                 side_effect=[FakeHttpError(429), py_types.SimpleNamespace(text="Trứng kho cà chua chín mềm.", candidates=[])],
             ) as gem_call, \
             patch("backend.services.chatbot_service.generate_ollama_response") as generate_ollama:
            result = answer_message("Cách nấu trứng mềm ngon?")

        self.assertTrue(result["success"])
        self.assertEqual([c.args[0] for c in gem_call.call_args_list], ["gemini-2.5-flash", "gemini-2.5-flash-lite"])
        self.assertEqual(result["model_used"], "gemini-2.5-flash-lite")
        self.assertEqual(result["aiDiagnostics"]["activeProvider"], "gemini")
        self.assertFalse(result["aiDiagnostics"]["geminiFailed"])
        generate_ollama.assert_not_called()

    def test_ollama_called_only_after_both_gemini_models_fail_with_full_vi_diagnostics(self):
        ollama_ok = {"response": "Cá kho mặn chữa bằng nước dừa tươi.", "model_used": "ollama/qwen3.5:4b", "metrics": {"duration_ms": 20, "eval_count": 10}}
        with patch.multiple(
            Config,
            GEMINI_API_KEY="configured-key",
            GEMINI_PRIMARY_MODEL="gemini-2.5-flash",
            GEMINI_FALLBACK_MODEL="gemini-2.5-flash-lite",
            GEMINI_MAX_RETRIES=0,
            CHATBOT_ENABLED=True,
            CHATBOT_RAG_ENABLED=False,
        ), patch("backend.services.chatbot_service._build_database_context", return_value=self.context), \
             patch("backend.gemini_manager._generate_once", side_effect=[FakeHttpError(429), FakeHttpError(429)]) as gem_call, \
             patch("backend.services.chatbot_service.generate_ollama_response", return_value=ollama_ok) as generate_ollama:
            result = answer_message("Cá kho bị mặn thì xử lý sao?")

        self.assertTrue(result["success"])
        self.assertEqual([c.args[0] for c in gem_call.call_args_list], ["gemini-2.5-flash", "gemini-2.5-flash-lite"])
        generate_ollama.assert_called_once()
        diag = result["aiDiagnostics"]
        self.assertEqual(diag["activeProvider"], "ollama")
        self.assertEqual(diag["modelUsed"], "ollama/qwen3.5:4b")
        self.assertTrue(diag["geminiFailed"])
        self.assertEqual(len(diag["attemptedModels"]), 2)
        self.assertEqual(diag["attemptedModels"][0]["httpCode"], 429)
        self.assertIn("Ollama", diag["userWarningVi"])
        self.assertNotIn("configured-key", str(diag))

    def test_missing_gemini_key_switches_to_ollama_with_clear_diagnostics(self):
        ollama = {"response": "Món trứng kho cà chua.", "model_used": "ollama/qwen3.5:4b", "metrics": {"duration_ms": 15, "eval_count": 8}}
        with patch.multiple(Config, GEMINI_API_KEY="", CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=False), \
             patch("backend.services.chatbot_service._build_database_context", return_value=self.context), \
             patch("backend.services.chatbot_service.generate_ollama_response", return_value=ollama) as generate_ollama:
            result = answer_message("Tôi có trứng, cà chua và hành lá.")
        self.assertTrue(result["success"])
        self.assertEqual(result["model_used"], "ollama/qwen3.5:4b")
        self.assertTrue(result["aiDiagnostics"]["geminiFailed"])
        self.assertIn("GEMINI_API_KEY", result["aiDiagnostics"]["userWarningVi"])
        generate_ollama.assert_called_once()

    def test_gemini_authentication_causes_reported_safely_when_ollama_also_unavailable(self):
        cases = (
            ("MISSING_API_KEY", "AI_MISSING_API_KEY", "chưa có Gemini API key"),
            ("INVALID_API_KEY", "AI_INVALID_API_KEY", "không hợp lệ"),
            ("EXPIRED_OR_REVOKED_API_KEY", "AI_EXPIRED_REVOKED_API_KEY", "hết hiệu lực hoặc bị thu hồi"),
            ("PERMISSION_DENIED", "AI_PERMISSION_DENIED", "chưa được cấp quyền"),
        )
        with patch.multiple(Config, GEMINI_API_KEY="configured", CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=False), \
             patch("backend.services.chatbot_service._build_database_context", return_value=self.context), \
             patch("backend.services.chatbot_service.generate_ollama_response", side_effect=OllamaError("MODEL_UNAVAILABLE")):
            for reason, error_code, message_fragment in cases:
                with self.subTest(reason=reason), patch(
                    "backend.services.chatbot_service.generate_ai_response",
                    side_effect=GeminiConfigurationError(reason=reason, source="UNIT_TEST"),
                ):
                    result = answer_message("Cách nấu trứng?")
                self.assertFalse(result["success"])
                self.assertTrue(result["fallback_used"])
                self.assertEqual(result["error_code"], error_code)
                self.assertIn(message_fragment, result["reply"])
                self.assertNotIn("UNIT_TEST", result["reply"])

    def test_nutrition_without_saved_values_is_not_estimated_by_a_model(self):
        context = dict(self.context, database_recipes=[])
        with patch.multiple(Config, CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=False), \
             patch("backend.services.chatbot_service._build_database_context", return_value=context), \
             patch("backend.services.chatbot_service.generate_ollama_response") as ollama, \
             patch("backend.services.chatbot_service.generate_ai_response") as gemini:
            result = answer_message("Ước tính dinh dưỡng cho món gà sốt cà chua.")
        self.assertTrue(result["success"])
        self.assertIn("không thể đưa ra con số", result["reply"])
        ollama.assert_not_called()
        gemini.assert_not_called()

    def test_common_no_soy_sauce_question_gets_a_grounded_substitution(self):
        with patch.multiple(Config, CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=False), \
             patch("backend.services.chatbot_service._build_database_context", return_value=self.context), \
             patch("backend.services.chatbot_service.generate_ollama_response") as ollama, \
             patch("backend.services.chatbot_service.generate_ai_response") as gemini:
            result = answer_message("Không có xì dầu thì thay bằng gì?")
        self.assertTrue(result["success"])
        self.assertIn("nước mắm pha loãng", result["reply"])
        self.assertIn("Đường không thay được xì dầu", result["reply"])
        ollama.assert_not_called()
        gemini.assert_not_called()

    def test_general_no_oil_request_never_suggests_oil_or_claims_pantry_inventory(self):
        oil_free_db_recipe = {
            "id": 145,
            "title": "Canh gà nấu cà chua dứa",
            "servings": 4,
            "prepTime": 15,
            "cookTime": 20,
            "totalTime": 35,
            "calories": 210,
            "nutrition": {"calories": 210, "protein": 24.0, "carbs": 11.0, "fat": 4.2, "fiber": 2.1},
            "ingredients": [
                {"id": 2, "name": "Thịt gà (ức)", "amount": "350", "unit": "g"},
                {"id": 8, "name": "Cà chua", "amount": "250", "unit": "g"},
                {"id": 49, "name": "Dứa", "amount": "150", "unit": "g"},
                {"id": 13, "name": "Nước mắm", "amount": "20", "unit": "ml"},
            ],
            "steps": [{"step": 1, "title": "Nấu canh", "description": "Đun sôi nước và thả ức gà cùng cà chua, dứa."}],
        }
        ctx = dict(
            self.context,
            excluded_ingredients=[{"id": 14, "name": "Dầu ăn"}],
            database_recipes=[oil_free_db_recipe],
        )
        with patch.multiple(Config, GEMINI_API_KEY="", CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=False), \
             patch("backend.services.chatbot_service._build_database_context", return_value=ctx), \
             patch("backend.services.chatbot_service.generate_ollama_response", side_effect=OllamaError("TIMEOUT")):
            result = answer_message("Cho tôi công thức không cần dùng dầu ăn.")
        self.assertTrue(result["success"])
        self.assertIn("Canh gà nấu cà chua dứa", result["reply"])
        self.assertIn("Nguyên liệu cần chuẩn bị", result["reply"])
        self.assertNotIn("- Dầu ăn", result["reply"])
        self.assertNotIn("dầu ăn:", result["reply"].lower())
        self.assertNotIn("nguyên liệu bạn đã có", result["reply"].lower())
        self.assertNotIn("chưa có trong csdl", result["reply"].lower())
        self.assertEqual(len(result["recipes"]), 1)


if __name__ == "__main__":
    unittest.main()
