import unittest
from unittest.mock import patch

from backend.database.repositories import match_dishes, match_dishes_detailed, score_recipe_search


class IngredientMatchTests(unittest.TestCase):
    def test_match_returns_score_missing_items_and_approved_recipe_link(self):
        rows = [
            {"id": 5, "recipeId": 17, "name": "Canh gà", "slug": "canh-ga", "image": "", "cookTime": 30,
             "difficulty": "Dễ", "categoryId": 1, "ingredientId": 2, "ingredientName": "Thịt gà", "isRequired": 1, "weightScore": 1},
            {"id": 5, "recipeId": 17, "name": "Canh gà", "slug": "canh-ga", "image": "", "cookTime": 30,
             "difficulty": "Dễ", "categoryId": 1, "ingredientId": 3, "ingredientName": "Cà rốt", "isRequired": 1, "weightScore": 1},
        ]
        with patch("backend.database.repositories.fetch_all", return_value=rows):
            result = match_dishes([2], [])
        self.assertEqual(result[0]["recipeId"], 17)
        self.assertEqual(result[0]["score"], 50)
        self.assertEqual(result[0]["matchedIngredients"], ["Thịt gà"])
        self.assertEqual(result[0]["missing"], ["Cà rốt"])

    def test_multi_ingredient_and_intersection_excludes_single_item_partial_dishes(self):
        rows = [
            # Dish 271: Cá basa + Bột bắp + Me vắt (combines BOTH selected ingredients!)
            {"id": 271, "recipeId": 271, "name": "Cá basa phi lê tẩm bột bắp chiên giòn sốt me", "slug": "ca-basa-sot-me",
             "image": "", "cookTime": 40, "difficulty": "Dễ", "categoryId": 4, "ingredientId": 6, "ingredientName": "Cá basa", "isRequired": 1, "weightScore": 5.0},
            {"id": 271, "recipeId": 271, "name": "Cá basa phi lê tẩm bột bắp chiên giòn sốt me", "slug": "ca-basa-sot-me",
             "image": "", "cookTime": 40, "difficulty": "Dễ", "categoryId": 4, "ingredientId": 3, "ingredientName": "Bột bắp", "isRequired": 1, "weightScore": 1.0},
            {"id": 271, "recipeId": 271, "name": "Cá basa phi lê tẩm bột bắp chiên giòn sốt me", "slug": "ca-basa-sot-me",
             "image": "", "cookTime": 40, "difficulty": "Dễ", "categoryId": 4, "ingredientId": 99, "ingredientName": "Me vắt", "isRequired": 1, "weightScore": 2.0},
            # Dish 88: Khoai tây chiên giòn (ONLY has Bột bắp — MUST be excluded!)
            {"id": 88, "recipeId": 88, "name": "Khoai tây chiên giòn", "slug": "khoai-tay-chien",
             "image": "", "cookTime": 20, "difficulty": "Dễ", "categoryId": 4, "ingredientId": 30, "ingredientName": "Khoai tây", "isRequired": 1, "weightScore": 5.0},
            {"id": 88, "recipeId": 88, "name": "Khoai tây chiên giòn", "slug": "khoai-tay-chien",
             "image": "", "cookTime": 20, "difficulty": "Dễ", "categoryId": 4, "ingredientId": 3, "ingredientName": "Bột bắp", "isRequired": 1, "weightScore": 1.0},
        ]
        with patch("backend.database.repositories.fetch_all", return_value=rows), \
             patch("backend.database.repositories.load_chatbot_synonyms", return_value={}):
            res = match_dishes_detailed([6, 3], ["Cá basa", "Bột bắp"])

        self.assertTrue(res["fullMatch"])
        self.assertEqual(res["selectedCount"], 2)
        self.assertEqual([m["id"] for m in res["matches"]], [271])
        self.assertEqual(res["matches"][0]["matchedUserCount"], 2)

    def test_incompatible_combo_weights_core_protein_5x_higher_than_starch(self):
        rows = [
            {"id": 5, "recipeId": 5, "name": "Canh chua cá basa", "slug": "canh-chua-ca-basa",
             "image": "", "cookTime": 35, "difficulty": "Dễ", "categoryId": 2, "ingredientId": 6, "ingredientName": "Cá basa", "isRequired": 1, "weightScore": 5.0},
            {"id": 88, "recipeId": 88, "name": "Khoai tây chiên giòn", "slug": "khoai-tay-chien",
             "image": "", "cookTime": 20, "difficulty": "Dễ", "categoryId": 4, "ingredientId": 3, "ingredientName": "Bột bắp", "isRequired": 1, "weightScore": 1.0},
        ]
        with patch("backend.database.repositories.fetch_all", return_value=rows), \
             patch("backend.database.repositories.load_chatbot_synonyms", return_value={}):
            res = match_dishes_detailed([], ["Cá basa", "Bột bắp"])

        self.assertFalse(res["fullMatch"])
        self.assertIn("Chưa có món đơn lẻ nào kết hợp đồng thời", res["notice"])
        self.assertEqual(res["matches"][0]["name"], "Canh chua cá basa")

    def test_regional_dish_synonyms_match_exact_titles(self):
        bun_cha = {"id": 2, "categoryId": 4, "categoryName": "Món nướng - Chiên", "title": "Bún chả Hà Nội nướng than hoa", "ingredients": [{"name": "Thịt ba chỉ"}], "tags": ["hà nội"]}
        thit_kho = {"id": 6, "categoryId": 1, "categoryName": "Món chính", "title": "Thịt kho tàu nước dừa miền Nam", "ingredients": [{"name": "Thịt ba chỉ"}], "tags": []}
        self.assertEqual(score_recipe_search(bun_cha, "bún chả quạt"), 100)
        self.assertEqual(score_recipe_search(thit_kho, "thịt kho hột vịt"), 100)


if __name__ == "__main__":
    unittest.main()
