# -*- coding: utf-8 -*-
"""Static verification of 200-recipe phpMyAdmin SQL & server-enforced RBAC lifecycle."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from backend.config import BASE_DIR
from backend.database import repositories as repo
from backend.database.connection import check_database, fetch_one, transaction


SQL_FILE = BASE_DIR / "database" / "cookmate_full_database.sql"


class PhpMyAdminSqlAndRbacTests(unittest.TestCase):
    def test_phpmyadmin_sql_structure_has_17_tables_no_forbidden_syntax(self):
        self.assertTrue(SQL_FILE.exists(), f"Missing {SQL_FILE}")
        content = SQL_FILE.read_text(encoding="utf-8")
        upper = content.upper()

        for bad in ("DELIMITER ", "CREATE TRIGGER", "CREATE PROCEDURE", "CREATE FUNCTION", "DEFINER="):
            self.assertNotIn(bad, upper)

        tables = re.findall(r"CREATE TABLE IF NOT EXISTS `([a-z0-9_]+)`", content)
        self.assertEqual(len(tables), 17)
        for required in ("users", "categories", "ingredients", "recipes", "recipe_ingredients",
                         "recipe_steps", "chatbot_knowledge_base", "chatbot_synonyms", "chatbot_learned_qa"):
            self.assertIn(required, tables)

        self.assertIn("-- 5. RECIPES (300 APPROVED recipes", content)
        self.assertIn("CREATE OR REPLACE VIEW `v_danh_sach_300_mon_an`", content)
        self.assertIn("ON DUPLICATE KEY UPDATE", content)

    def test_member_vs_admin_rbac_and_rejection_reason_roundtrip(self):
        try:
            check_database()
        except Exception as exc:
            self.skipTest(f"MySQL not available for RBAC test: {exc}")

        admin_row = fetch_one("SELECT user_id FROM users WHERE role='admin' LIMIT 1")
        member_row = fetch_one("SELECT user_id FROM users WHERE role='member' LIMIT 1")
        if not admin_row or not member_row:
            self.skipTest("Seeded admin/member accounts not present.")

        admin_id = int(admin_row["user_id"])
        member_id = int(member_row["user_id"])
        created_ids: list[int] = []

        sample_payload = {
            "title": "Canh thử nghiệm RBAC tạm",
            "description": "Công thức kiểm thử quy trình kiểm duyệt.",
            "categoryId": 2,
            "servings": 2,
            "prepTime": 5,
            "cookTime": 10,
            "difficulty": "Dễ",
            "ingredients": [{"name": "Cà chua", "amount": "150", "unit": "g"}],
            "steps": [{"description": "Rửa sạch và nấu sôi 5 phút."}],
            "nutrition": {"calories": 120, "protein": 4, "carbs": 12, "fat": 2, "fiber": 2},
        }

        try:
            # 1. Admin creates recipe -> published directly as APPROVED
            admin_recipe = repo.create_recipe(sample_payload, admin_id, admin=True)
            created_ids.append(admin_recipe["id"])
            self.assertEqual(admin_recipe["status"], "approved")
            self.assertEqual(admin_recipe["sourceType"], "DB")

            # 2. Member submits recipe -> forced to PENDING even if trying to spoof status
            member_recipe = repo.create_recipe({**sample_payload, "status": "approved"}, member_id, admin=False)
            created_ids.append(member_recipe["id"])
            self.assertEqual(member_recipe["status"], "pending")
            self.assertEqual(member_recipe["sourceType"], "USER")

            # 3. Admin rejects with reason -> REJECTED + rejectionReason persisted
            rejected = repo.moderate_recipe(member_recipe["id"], admin_id, "REJECTED", reason="Thiếu định lượng gia vị.")
            self.assertIsNotNone(rejected)
            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(rejected["rejectionReason"], "Thiếu định lượng gia vị.")

            # 4. Member updates -> resets back to PENDING and clears old rejection_reason
            resubmitted = repo.update_recipe(member_recipe["id"], member_id, {**sample_payload, "title": "Canh kiểm thử sửa lại"}, admin=False)
            self.assertEqual(resubmitted["status"], "pending")
            self.assertEqual(resubmitted["rejectionReason"], "")

            # 5. Admin approves -> APPROVED
            approved = repo.moderate_recipe(member_recipe["id"], admin_id, "APPROVED")
            self.assertEqual(approved["status"], "approved")
        finally:
            if created_ids:
                with transaction() as (_, cur):
                    placeholders = ",".join(["%s"] * len(created_ids))
                    cur.execute(f"DELETE FROM recipes WHERE recipe_id IN ({placeholders})", tuple(created_ids))
                    cur.execute(
                        "UPDATE categories c SET recipe_count=("
                        "SELECT COUNT(*) FROM recipes r WHERE r.category_id=c.category_id AND r.status='APPROVED')"
                    )


if __name__ == "__main__":
    unittest.main()
