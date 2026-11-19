from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MySqlSchemaTests(unittest.TestCase):
    def test_single_unified_sql_file_in_database_directory(self):
        sql_files = [p.name for p in (ROOT / "database").glob("*.sql")]
        self.assertEqual(sql_files, ["cookmate_full_database.sql"])

    def test_full_schema_defines_all_17_entities_view_and_constraints(self):
        sql = (ROOT / "database" / "cookmate_full_database.sql").read_text(encoding="utf-8")
        tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+`?(\w+)`?", sql, re.I))
        expected = {
            "users", "categories", "ingredients", "dishes", "dish_ingredients", "recipes",
            "recipe_ingredients", "recipe_steps", "recipe_sources", "ai_search_cache", "favorites",
            "comments", "chat_sessions", "chat_messages", "chatbot_knowledge_base",
            "chatbot_synonyms", "chatbot_learned_qa",
        }
        self.assertEqual(tables, expected)
        self.assertIn("CREATE DATABASE IF NOT EXISTS `cookmate`", sql)
        self.assertIn("USE `cookmate`;", sql)
        self.assertIn("CREATE OR REPLACE VIEW `v_danh_sach_300_mon_an`", sql)
        self.assertIn("DEFAULT CHARSET=utf8mb4", sql)
        self.assertIn("FOREIGN KEY", sql)
        self.assertIn("UNIQUE KEY", sql)
        self.assertNotRegex(sql, r"(?im)^\s*DROP\s+(DATABASE|TABLE)")


if __name__ == "__main__":
    unittest.main()
