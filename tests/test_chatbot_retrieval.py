import unittest
from unittest.mock import patch

from backend.config import Config
from backend.gemini_manager import GeminiServiceUnavailable
from backend.ollama_manager import OllamaError
from backend.services.chatbot_service import (
    _build_database_context,
    _extract_catalog_ingredients,
    _ingredient_breakdown,
    _normalize_inventory_headings,
    _strip_model_source_labels,
    answer_message,
    render_grounded_mysql_recipe_response,
)


CATALOG = [
    {"id": 2, "name": "Thịt gà (ức)", "category": "Thịt"},
    {"id": 8, "name": "Cà chua", "category": "Rau củ"},
    {"id": 14, "name": "Dầu ăn", "category": "Dầu mỡ"},
    {"id": 16, "name": "Trứng gà", "category": "Trứng sữa"},
    {"id": 28, "name": "Hành lá", "category": "Rau"},
    {"id": 29, "name": "Tiêu", "category": "Gia vị"},
    {"id": 15, "name": "Đường", "category": "Gia vị"},
]


class ChatbotRetrievalTests(unittest.TestCase):
    def test_extracts_catalog_ingredients_and_queries_with_real_ids(self):
        selected, excluded = _extract_catalog_ingredients("Tôi có thịt gà và cà chua, nấu món gì?", CATALOG)
        self.assertEqual({item["id"] for item in selected}, {2, 8})
        self.assertEqual(excluded, [])
        with patch("backend.services.chatbot_service.list_ingredients", return_value=CATALOG), \
             patch("backend.services.chatbot_service.search_chatbot_recipes", return_value=[]) as search:
            context = _build_database_context("Tôi có thịt gà và cà chua, nấu món gì?")
        self.assertEqual({item["id"] for item in context["user_stated_ingredients"]}, {2, 8})
        self.assertEqual(set(search.call_args.args[0]), {2, 8})
        self.assertTrue(context["recipe_search_performed"])
        self.assertEqual({item["id"] for item in context["user_stated_ingredients"]}, {2, 8})

    def test_recipe_name_mentions_are_not_mistaken_for_pantry_inventory(self):
        with patch("backend.services.chatbot_service.list_ingredients", return_value=CATALOG), \
             patch("backend.services.chatbot_service.search_chatbot_recipes", return_value=[]):
            context = _build_database_context("Cách nấu canh gà cà chua?")
        self.assertEqual({item["name"] for item in context["ingredients_mentioned_in_question"]}, {"Thịt gà (ức)", "Cà chua"})
        self.assertEqual(context["user_stated_ingredients"], [])

    def test_generated_recipe_does_not_claim_unstated_ingredients_are_already_available(self):
        reply = (
            "Nguyên liệu người dùng đã có:\n- Thịt gà\n- Cà chua\n\n"
            "Nguyên liệu chính cần chuẩn bị:\n- Dầu ăn\n"
        )
        result = _normalize_inventory_headings(reply, [])
        self.assertNotIn("Nguyên liệu người dùng đã có", result)
        self.assertIn("Nguyên liệu chính cần chuẩn bị:\n- Thịt gà", result)
        self.assertIn("Nguyên liệu bổ sung cần chuẩn bị:\n- Dầu ăn", result)
        self.assertIn("Nguyên liệu bổ sung cần chuẩn bị:\n- Dầu ăn", result)
        self.assertEqual(_normalize_inventory_headings("Nguyên liệu người dùng đã có: Không có thông tin.\n\nCần chuẩn bị:\n- Thịt gà", []), "\nCần chuẩn bị:\n- Thịt gà")
        no_inventory = _normalize_inventory_headings("Nguyên liệu người dùng đã có:\nKhông có thông tin.\n\nCần chuẩn bị:\n- Thịt gà", [])
        self.assertNotIn("Nguyên liệu chính cần chuẩn bị", no_inventory)
        self.assertNotIn("Không có thông tin", no_inventory)
        self.assertEqual(_strip_model_source_labels("Gà sốt cà chua (Gợi ý tự nấu do trí tuệ nhân tạo đề xuất, chưa có trong CSDL CookMate)"), "Gà sốt cà chua")

    def test_grounded_mysql_renderer_formats_exact_db_quantities_and_macros(self):
        db_recipe = {
            "id": 134,
            "title": "Ức gà sốt cà chua đậm đà",
            "servings": 4,
            "prepTime": 15,
            "cookTime": 20,
            "totalTime": 35,
            "calories": 285,
            "nutrition": {"calories": 285, "protein": 31.2, "carbs": 9.4, "fat": 6.1, "fiber": 1.8},
            "ingredients": [
                {"id": 2, "name": "Thịt gà (ức)", "amount": "500", "unit": "g", "note": ""},
                {"id": 8, "name": "Cà chua", "amount": "350", "unit": "g", "note": ""},
                {"id": 13, "name": "Nước mắm", "amount": "25", "unit": "ml", "note": ""},
            ],
            "steps": [
                {"step": 1, "title": "Ướp ức gà", "description": "Ướp ức gà 15 phút.", "duration": 5},
                {"step": 2, "title": "Rim sốt cà chua", "description": "Rim ức gà cùng sốt cà chua.", "duration": 10},
            ],
        }
        ctx = {
            "user_stated_ingredients": [{"id": 2, "name": "Thịt gà (ức)"}, {"id": 8, "name": "Cà chua"}],
            "ingredient_groups": [
                {"key": "thit_ga", "label": "Thịt gà", "ids": {2}, "names": {"Thịt gà (ức)"}},
                {"key": "ca_chua", "label": "Cà chua", "ids": {8}, "names": {"Cà chua"}},
            ],
            "requested_servings": None,
            "funnel_tier": "full_group_intersection",
        }
        rendered = render_grounded_mysql_recipe_response([db_recipe], ctx, "Tôi có thịt gà và cà chua, nấu món gì?")
        self.assertIn("Ức gà sốt cà chua đậm đà", rendered)
        self.assertIn("285 kcal/khẩu phần", rendered)
        self.assertIn("500 g", rendered)
        self.assertIn("350 g", rendered)
        self.assertIn("Nguyên liệu bạn đã có", rendered)
        self.assertIn("Nguyên liệu & gia vị cần chuẩn bị thêm", rendered)
        self.assertNotIn("chưa có trong CSDL", rendered)
        self.assertNotIn("Gợi ý tự nấu", rendered)

    def test_negative_oil_is_marked_excluded_and_not_assumed_available(self):
        with patch("backend.services.chatbot_service.list_ingredients", return_value=CATALOG), \
             patch("backend.services.chatbot_service.search_chatbot_recipes", return_value=[]) as search:
            context = _build_database_context("Cho tôi công thức không cần dùng dầu ăn.")
        self.assertEqual(context["user_stated_ingredients"], [])
        self.assertEqual([item["name"] for item in context["excluded_ingredients"]], ["Dầu ăn"])
        self.assertEqual(search.call_args.kwargs["excluded_ingredient_ids"], [14])
        self.assertFalse(context["recipe_search_performed"])

    def test_recipe_ingredients_are_split_by_user_having_seasoning_and_optional_status(self):
        recipe = {"ingredients": [
            {"id": 8, "name": "Cà chua", "amount": 2, "unit": "quả", "dish_required": 1, "category": "Rau củ"},
            {"id": 29, "name": "Tiêu", "amount": 1, "unit": "g", "dish_required": 1, "category": "Gia vị"},
            {"id": 28, "name": "Hành lá", "amount": 5, "unit": "g", "dish_required": 0, "category": "Rau"},
        ]}
        result = _ingredient_breakdown(recipe, [{"id": 8, "name": "Cà chua"}])
        self.assertEqual([item["name"] for item in result["user_has_for_recipe"]], ["Cà chua"])
        self.assertEqual([item["name"] for item in result["seasonings_to_add"]], ["Tiêu"])
        self.assertEqual([item["name"] for item in result["optional_ingredients"]], ["Hành lá"])

    def test_pantry_staples_are_separated_from_core_stated_ingredients(self):
        candidate = {
            "id": 47, "title": "Canh cà chua trứng", "description": "", "servings": 4,
            "ingredients": [
                {"id": 16, "name": "Trứng gà", "amount": "3", "unit": "quả"},
                {"id": 8, "name": "Cà chua", "amount": "200", "unit": "g"},
            ],
            "steps": [{"step": 1, "title": "Nấu canh", "description": "Đun sôi nước và thả cà chua trứng."}],
            "nutrition": {"calories": 145, "protein": 9.2, "carbs": 6.4, "fat": 8.5, "fiber": 1.4},
            "calories": 145,
            "matched_ingredients": 2, "total_ingredients": 4,
        }
        with patch("backend.services.chatbot_service.list_ingredients", return_value=CATALOG), \
             patch("backend.services.chatbot_service.search_chatbot_recipes", return_value=[candidate]):
            context = _build_database_context("Tôi có trứng, cà chua và hành lá.")
        # Hành lá is a pantry staple, so core stated ingredients are Trứng gà + Cà chua, matching DB recipe #47!
        self.assertEqual({item["id"] for item in context["user_stated_ingredients"]}, {8, 16})
        self.assertEqual([r["id"] for r in context["database_recipes"]], [47])

    def test_ungrounded_model_reply_falls_back_to_deterministic_mysql_recipe(self):
        db_recipe = {
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
            ],
            "steps": [{"step": 1, "title": "Nấu canh", "description": "Nấu ức gà cùng cà chua chín."}],
        }
        context = {
            "db_status": "AVAILABLE", "recipe_search_performed": True,
            "requested_servings": 2,
            "user_stated_ingredients": [], "excluded_ingredients": [{"id": 14, "name": "Dầu ăn"}],
            "database_recipes": [db_recipe], "cookmate_ingredient_catalog": [c["name"] for c in CATALOG],
            "funnel_tier": "direct_title",
        }
        bad_reply = "Món tự chế không định lượng và thêm dầu ăn."
        with patch.multiple(Config, GEMINI_API_KEY="present", CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=True), \
             patch("backend.services.chatbot_service._build_database_context", return_value=context), \
             patch("backend.services.chatbot_service.generate_ai_response", return_value={
                 "response": bad_reply, "model_used": "gemini-2.5-flash", "fallback_used": False,
             }) as gemini, \
             patch("backend.services.chatbot_service.generate_ollama_response") as ollama:
            result = answer_message("Cách nấu canh gà nấu cà chua dứa cho 2 người?")
        self.assertTrue(result["success"])
        self.assertIn("Canh gà nấu cà chua dứa", result["reply"])
        self.assertIn("175 g", result["reply"])
        self.assertNotIn("dầu ăn", result["reply"].lower())
        self.assertNotIn("chưa có trong CSDL", result["reply"])
        self.assertEqual(len(result["recipes"]), 1)
        gemini.assert_called_once()
        ollama.assert_not_called()

    def test_valid_gemini_primary_reply_does_not_call_ollama_and_has_zero_non_db_disclaimer(self):
        context = {
            "db_status": "AVAILABLE", "recipe_search_performed": True,
            "user_stated_ingredients": [], "excluded_ingredients": [],
            "database_recipes": [],
        }
        with patch.multiple(Config, GEMINI_API_KEY="present", CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=True), \
             patch("backend.services.chatbot_service._build_database_context", return_value=context), \
             patch("backend.services.chatbot_service.generate_ai_response", return_value={
                 "response": "Luộc trứng trong 7 phút cho lòng đào.", "model_used": "gemini-2.5-flash", "fallback_used": False,
             }) as gemini, \
             patch("backend.services.chatbot_service.generate_ollama_response") as ollama:
            result = answer_message("Luộc trứng bao nhiêu phút?")
        self.assertTrue(result["success"])
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["aiDiagnostics"]["activeProvider"], "gemini")
        self.assertNotIn("Gợi ý tự nấu", result["reply"])
        self.assertNotIn("chưa có trong CSDL", result["reply"])
        gemini.assert_called_once()
        ollama.assert_not_called()

    def test_off_topic_tc08_never_calls_either_model(self):
        with patch("backend.services.chatbot_service.generate_ollama_response") as ollama, \
             patch("backend.services.chatbot_service.generate_ai_response") as gemini:
            result = answer_message("Giải phương trình bậc hai.")
        self.assertEqual(result["classification"], "OFF_TOPIC")
        ollama.assert_not_called()
        gemini.assert_not_called()

    def test_gemini_failure_calls_ollama_only_as_fallback(self):
        from backend.gemini_manager import GeminiServiceUnavailable
        context = {
            "db_status": "AVAILABLE", "recipe_search_performed": True,
            "user_stated_ingredients": [], "excluded_ingredients": [],
            "database_recipes": [], "custom_recipe_allowed": False,
        }
        with patch.multiple(Config, GEMINI_API_KEY="present", CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=True), \
             patch("backend.services.chatbot_service._build_database_context", return_value=context), \
             patch("backend.services.chatbot_service.generate_ai_response", side_effect=GeminiServiceUnavailable(429)) as gemini, \
             patch("backend.services.chatbot_service.generate_ollama_response", return_value={"response": "Dự phòng cục bộ.", "model_used": "ollama/qwen3.5:4b", "metrics": {}}) as ollama:
            result = answer_message("Cách nấu trứng?")
        self.assertTrue(result["fallback_used"])
        self.assertTrue(result["aiDiagnostics"]["geminiFailed"])
        self.assertEqual(result["aiDiagnostics"]["activeProvider"], "ollama")
        gemini.assert_called_once()
        ollama.assert_called_once()


if __name__ == "__main__":
    unittest.main()
