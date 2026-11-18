# -*- coding: utf-8 -*-
"""Unit tests for Exact Ingredient/Phrase Search & 100% Database-Only ChefBot OR-Grouping."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.config import Config
from backend.database.repositories import score_recipe_search
from backend.services.chatbot_service import _extract_ingredient_groups, answer_message


RICH_CATALOG = [
    {"id": 2, "name": "Thịt gà (ức)", "category": "Thịt"},
    {"id": 51, "name": "Thịt gà (đùi)", "category": "Thịt"},
    {"id": 62, "name": "Cánh gà", "category": "Thịt"},
    {"id": 16, "name": "Trứng gà", "category": "Trứng & Sữa"},
    {"id": 84, "name": "Nấm đùi gà", "category": "Rau củ"},
    {"id": 199, "name": "Nước dùng gà", "category": "Gia vị"},
    {"id": 8, "name": "Cà chua", "category": "Rau củ"},
    {"id": 71, "name": "Cá lóc", "category": "Hải sản"},
    {"id": 6, "name": "Đậu hũ", "category": "Đồ chay"},
    {"id": 13, "name": "Nước mắm", "category": "Gia vị"},
    {"id": 14, "name": "Dầu ăn", "category": "Dầu mỡ"},
    {"id": 28, "name": "Hành lá", "category": "Rau"},
]


class ExactRecipeSearchTests(unittest.TestCase):
    def setUp(self):
        self.uc_ga_title = {
            "id": 134,
            "categoryId": 1,
            "categoryName": "Món chính",
            "title": "Ức gà sốt cà chua đậm đà",
            "description": "Ức gà áp chảo mềm mọng sốt cà chua.",
            "ingredients": [{"name": "Thịt gà (ức)"}, {"name": "Cà chua"}],
            "tags": ["ức gà", "eat clean"],
        }
        self.uc_ga_ing_only = {
            "id": 145,
            "categoryId": 2,
            "categoryName": "Món canh - Súp",
            "title": "Canh gà nấu cà chua dứa",
            "description": "Tô canh thanh ngọt.",
            "ingredients": [{"name": "Thịt gà (ức)"}, {"name": "Cà chua"}, {"name": "Dứa"}],
            "tags": ["món canh"],
        }
        self.dui_ga_recipe = {
            "id": 135,
            "categoryId": 2,
            "categoryName": "Món canh - Súp",
            "title": "Phở gà ta lá chanh Hà Nội",
            "description": "Phở gà nước trong.",
            "ingredients": [{"name": "Thịt gà (đùi)"}, {"name": "Bánh phở tươi"}],
            "tags": ["phở"],
        }
        self.vegan_nam_dui_ga = {
            "id": 170,
            "categoryId": 5,
            "categoryName": "Món chay",
            "title": "Nấm đùi gà nướng sả ớt chay",
            "description": "Món thuần thực vật đậm vị sả ớt.",
            "ingredients": [{"name": "Nấm đùi gà"}, {"name": "Sả"}],
            "tags": ["món chay"],
        }
        self.vegan_lau_nam = {
            "id": 169,
            "categoryId": 5,
            "categoryName": "Món chay",
            "title": "Lẩu nấm chay thập cẩm thanh ngọt",
            "description": "Thực đơn thuần thực vật thanh mát mức calo thấp.",
            "ingredients": [{"name": "Nấm hương"}, {"name": "Đậu hũ"}],
            "tags": ["món chay", "lẩu"],
        }
        self.vegan_bun_bo = {
            "id": 168,
            "categoryId": 5,
            "categoryName": "Món chay",
            "title": "Bún bò Huế chay đậm đà",
            "description": "Nước dùng rau củ thuần thực vật.",
            "ingredients": [{"name": "Bún tươi"}, {"name": "Nấm đùi gà"}, {"name": "Đậu hũ"}],
            "tags": ["món chay"],
        }
        self.savory_bun_bo = {
            "id": 11,
            "categoryId": 2,
            "categoryName": "Món canh - Súp",
            "title": "Bún bò Huế cay nồng chuẩn vị Cố đô",
            "description": "Bắp bò giò heo đậm vị ruốc Huế.",
            "ingredients": [{"name": "Bắp bò"}, {"name": "Giò heo"}, {"name": "Bún tươi"}],
            "tags": ["huế", "bún"],
        }

    def test_uc_ga_with_and_without_diacritics_excludes_vegan_and_non_breast_cuts(self):
        for q in ("Ức Gà", "ức gà", "uc ga"):
            with self.subTest(query=q):
                self.assertEqual(score_recipe_search(self.uc_ga_title, q), 100)
                self.assertEqual(score_recipe_search(self.uc_ga_ing_only, q), 85)
                self.assertEqual(score_recipe_search(self.dui_ga_recipe, q), 0)
                self.assertEqual(score_recipe_search(self.vegan_nam_dui_ga, q), 0)
                self.assertEqual(score_recipe_search(self.vegan_lau_nam, q), 0)
                self.assertEqual(score_recipe_search(self.vegan_bun_bo, q), 0)

    def test_bun_bo_excludes_vegan_unless_chay_is_in_query(self):
        self.assertEqual(score_recipe_search(self.savory_bun_bo, "Bún bò"), 100)
        self.assertEqual(score_recipe_search(self.vegan_bun_bo, "Bún bò"), 0)
        self.assertGreater(score_recipe_search(self.vegan_bun_bo, "Bún bò chay"), 0)

    def test_diacritics_distinguish_ca_vs_ca_chua_and_bo_vs_bo_avocado(self):
        sinh_to_bo = {
            "id": 99,
            "categoryId": 7,
            "categoryName": "Đồ uống",
            "title": "Sinh tố bơ sầu riêng béo mịn",
            "ingredients": [{"name": "Bơ sáp"}, {"name": "Sữa đặc"}],
            "tags": ["sinh tố"],
        }
        self.assertEqual(score_recipe_search(sinh_to_bo, "Thịt bò"), 0)
        self.assertEqual(score_recipe_search(sinh_to_bo, "Bò"), 0)
        self.assertEqual(score_recipe_search(self.uc_ga_title, "Cá"), 0)


class ChefBotOrGroupingAndDbOnlyTests(unittest.TestCase):
    def test_chicken_and_tomato_forms_two_or_groups_and_excludes_eggs_and_king_oyster_mushroom(self):
        selected, excluded, groups = _extract_ingredient_groups(
            "Tôi có thịt gà và cà chua, nấu món gì?",
            RICH_CATALOG,
        )
        self.assertEqual(excluded, [])
        self.assertEqual([g["key"] for g in groups], ["ca_chua", "thit_ga"])
        ga_group = next(g for g in groups if g["key"] == "thit_ga")
        # Chicken breast (2), thigh (51), and wing (62) are grouped into ONE OR-group; egg (16), mushroom (84), broth (199) excluded!
        self.assertEqual(ga_group["ids"], {2, 51, 62})
        self.assertNotIn(16, ga_group["ids"])
        self.assertNotIn(84, ga_group["ids"])
        self.assertNotIn(199, ga_group["ids"])
        # "cà chua" never triggers fish ("ca")!
        self.assertNotIn("ca", [g["key"] for g in groups])

    def test_longest_span_masks_nam_dui_ga_and_trung_ga_from_triggering_chicken_meat(self):
        _, _, groups = _extract_ingredient_groups(
            "Tôi có nấm đùi gà và trứng gà thì nấu món gì?",
            RICH_CATALOG,
        )
        keys = [g["key"] for g in groups]
        self.assertEqual(set(keys), {"nam_dui_ga", "trung"})
        self.assertNotIn("thit_ga", keys)
        self.assertNotIn("dui_ga", keys)

    def test_foreign_dish_not_in_db_returns_polite_message_and_top3_mysql_dishes(self):
        top3 = [
            {
                "id": 19, "title": "Gỏi cuốn tôm thịt Sài Gòn", "servings": 4,
                "prepTime": 20, "cookTime": 15, "totalTime": 35, "calories": 240,
                "nutrition": {"calories": 240, "protein": 18.0, "carbs": 28.0, "fat": 5.0, "fiber": 2.4},
                "ingredients": [{"id": 5, "name": "Tôm tươi", "amount": "250", "unit": "g"}],
                "steps": [{"step": 1, "title": "Cuốn gỏi", "description": "Trải bánh tráng cuốn tôm thịt rau sống."}],
            },
            {"id": 111, "title": "Phở cuốn thịt bò Hà Nội", "servings": 4, "calories": 265, "ingredients": [], "steps": []},
            {"id": 91, "title": "Gỏi cuốn chay", "servings": 4, "calories": 190, "ingredients": [], "steps": []},
        ]
        ctx = {
            "db_status": "AVAILABLE",
            "recipe_search_performed": True,
            "requested_servings": None,
            "user_stated_ingredients": [],
            "ingredient_groups": [],
            "excluded_ingredients": [],
            "database_recipes": top3,
            "funnel_tier": "top_category_fallback",
            "foreign_dish_requested": "Sushi Nhật Bản",
            "kb_entries": [],
            "learned_qa": {"exact": None, "similar": [], "few_shots": []},
        }
        with patch.multiple(Config, CHATBOT_ENABLED=True, CHATBOT_RAG_ENABLED=True), \
             patch("backend.services.chatbot_service._build_database_context", return_value=ctx), \
             patch("backend.services.chatbot_service.save_or_update_learned_qa", return_value=77), \
             patch("backend.services.chatbot_service.generate_ollama_response") as ollama:
            res = answer_message("Hướng dẫn làm món sushi cá hồi?")
        ollama.assert_not_called()
        self.assertTrue(res["success"])
        self.assertIn("Sushi Nhật Bản", res["reply"])
        self.assertIn("Top 3 món ăn thật gần gũi nhất trong CSDL CookMate", res["reply"])
        self.assertIn("Gỏi cuốn tôm thịt Sài Gòn", res["reply"])
        self.assertEqual(len(res["recipes"]), 3)
        self.assertNotIn("Gợi ý tự nấu", res["reply"])


if __name__ == "__main__":
    unittest.main()
