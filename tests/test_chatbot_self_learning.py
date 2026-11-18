# -*- coding: utf-8 -*-
"""Tests for SQL-grounded RAG knowledge base, synonym normalization, and feedback memory."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app import create_app
from backend.database import repositories as repo
from backend.services.chatbot_service import answer_message


class ChatbotSelfLearningTests(unittest.TestCase):
    def test_chatbot_feedback_endpoint_validates_rating_and_updates_score(self):
        app = create_app({"TESTING": True})
        client = app.test_client()

        bad_res = client.post("/api/chatbot/feedback", json={"qa_id": 1, "rating": 99})
        self.assertEqual(bad_res.status_code, 400)

        with patch("backend.routes.api.repo.record_chatbot_feedback", return_value={
            "qaId": 7, "qualityScore": 1.15, "isVerified": True, "usageCount": 3
        }) as rec:
            ok_res = client.post("/api/chatbot/feedback", json={"qa_id": 7, "rating": 1})

        self.assertEqual(ok_res.status_code, 200)
        payload = ok_res.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["feedback"]["qualityScore"], 1.15)
        self.assertTrue(payload["feedback"]["isVerified"])
        rec.assert_called_once_with(7, 1)

    def test_verified_memory_fast_path_returns_qa_id_without_calling_models(self):
        context = {
            "db_status": "AVAILABLE",
            "recipe_search_performed": False,
            "requested_servings": None,
            "ingredients_mentioned_in_question": [],
            "cookmate_ingredient_catalog": [],
            "user_stated_ingredients": [],
            "excluded_ingredients": [],
            "database_recipes": [],
            "custom_recipe_allowed": True,
            "kb_entries": [],
            "learned_qa": {
                "exact": {
                    "qa_id": 12,
                    "question": "Thịt gà bị hôi rửa bằng gì?",
                    "answer": "Dùng muối hạt và gừng đập dập chà nhẹ 3 phút rồi xả sạch.",
                    "quality_score": 1.25,
                    "is_verified": True,
                    "source_type": "CURATED",
                },
                "similar": [],
                "few_shots": [],
            },
        }
        with patch("backend.services.chatbot_service._build_database_context", return_value=context), \
             patch("backend.services.chatbot_service.save_or_update_learned_qa", return_value=12), \
             patch("backend.services.chatbot_service.generate_ollama_response") as ollama, \
             patch("backend.services.chatbot_service.generate_ai_response") as gemini:
            result = answer_message("Thịt gà bị hôi rửa bằng gì?")

        ollama.assert_not_called()
        gemini.assert_not_called()
        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "memory_verified")
        self.assertEqual(result["qa_id"], 12)
        self.assertIn("gừng", result["reply"].lower())

    def test_search_knowledge_base_scores_matching_entries(self):
        rows = [
            {
                "kb_id": 1, "topic": "su_co_man", "category": "troubleshooting",
                "title": "Xử lý món kho bị mặn",
                "keywords_text": "ca kho bi man,kho man",
                "content": "Chắt bớt nước kho và thêm nước dừa tươi.",
                "substitution_json": None, "priority": 20,
            },
            {
                "kb_id": 2, "topic": "luoc_ga", "category": "technique",
                "title": "Luộc gà da vàng",
                "keywords_text": "luoc ga",
                "content": "Cho vào nước lạnh.",
                "substitution_json": None, "priority": 10,
            },
        ]
        with patch("backend.database.repositories.fetch_all", return_value=rows):
            hits = repo.search_knowledge_base("ca kho bi man xu ly sao", ["ca", "kho", "man"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["title"], "Xử lý món kho bị mặn")


if __name__ == "__main__":
    unittest.main()
