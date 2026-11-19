import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from recipes_100_data import RECIPES
from seed_100_recipes import EXPECTED_CATEGORY_COUNTS, parse_ingredients, slugify, validate_collection


class SeedRecipeCatalogTests(unittest.TestCase):
    def test_exact_recipe_count_and_category_distribution(self):
        validate_collection()
        self.assertEqual(len(RECIPES), 100)
        self.assertEqual(Counter(item["category"] for item in RECIPES), EXPECTED_CATEGORY_COUNTS)
        self.assertEqual(len({slugify(item["name"]) for item in RECIPES}), 100)

    def test_every_recipe_has_complete_ingredients_and_steps(self):
        for item in RECIPES:
            with self.subTest(recipe=item["name"]):
                ingredients = parse_ingredients(item["ingredients"])
                self.assertGreaterEqual(len(ingredients), 5)
                self.assertLessEqual(len(ingredients), 10)
                self.assertGreaterEqual(sum(part["core"] for part in ingredients), 3)
                self.assertLessEqual(sum(part["core"] for part in ingredients), 7)
                self.assertGreaterEqual(len(item["steps"]), 4)
                self.assertLessEqual(len(item["steps"]), 7)
                self.assertTrue(all("|" in step and step.split("|", 1)[1].strip() for step in item["steps"]))


if __name__ == "__main__":
    unittest.main()
