import unittest
from unittest.mock import patch

from app import create_app


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "SECRET_KEY": "unit-test-secret", "CORS_ALLOWED_ORIGINS": ()})
        self.client = self.app.test_client()

    def test_favorites_require_a_server_session(self):
        response = self.client.get("/api/favorites", headers={"X-User-Id": "23", "X-User-Role": "admin"})
        self.assertEqual(response.status_code, 401)

    def test_chatbot_rejects_client_supplied_api_keys(self):
        response = self.client.post("/api/chatbot", json={"apiKey": "should-not-be-used"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("server-managed", response.get_json()["error"])

    def test_chatbot_ai_service_failure_returns_error_status_and_safe_reply(self):
        session_id = "guest-session-for-error-test"
        with self.client.session_transaction() as session:
            session["guest_chat_sessions"] = [session_id]
        for error_code in (
            "AI_SERVICE_UNAVAILABLE", "AI_CONFIGURATION_ERROR", "AI_MISSING_API_KEY",
            "AI_INVALID_API_KEY", "AI_EXPIRED_REVOKED_API_KEY", "AI_PERMISSION_DENIED",
            "AI_OLLAMA_UNAVAILABLE",
        ):
            failed = {
                "success": False,
                "classification": "FOOD_RELATED",
                "reply": "Hiện tại trợ lý CookMate đang gặp sự cố. Vui lòng thử lại sau.",
                "recipes": [],
                "suggestions": [],
                "mode": "unavailable",
                "error_code": error_code,
            }
            with self.subTest(error_code=error_code), \
                 patch("backend.routes.api.repo.get_chat_session", return_value={"user_id": None, "context_recipe_id": None}), \
                 patch("backend.routes.api.repo.get_chat_history", return_value=[]), \
                 patch("backend.routes.api.repo.save_chat_messages") as save_history, \
                 patch("backend.routes.api.answer_message", return_value=failed):
                response = self.client.post("/api/chatbot", json={"message": "Món gà nấu sao?", "session_id": session_id})
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.get_json()["success"])
            self.assertIn("đang gặp sự cố", response.get_json()["reply"])
            save_history.assert_called_once()

    def test_chatbot_config_reports_shared_primary_and_fallback_key(self):
        validation = {
            "configured": True,
            "api_key_status": "FOUND",
            "api_key_validity": "UNKNOWN",
            "api_key_conflict": True,
            "errors": (),
        }
        with patch("backend.config.validate_gemini_configuration", return_value=validation):
            response = self.client.get("/api/chatbot/config")
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["configured"])
        self.assertTrue(payload["localConfigured"])
        self.assertEqual(payload["localModel"], "qwen3.5:4b")
        self.assertTrue(payload["fallbackConfigured"])
        self.assertEqual(payload["apiKeyValidity"], "UNKNOWN")
        self.assertTrue(payload["keyConflict"])

    def test_member_role_from_database_blocks_admin_api(self):
        member = {"id": 23, "name": "Member", "email": "member@example.test", "role": "member", "status": "active"}
        with self.client.session_transaction() as session:
            session["user_id"] = 23
            session["csrf_token"] = "csrf-test"
        with patch("backend.security.authentication.get_user_by_id", return_value=member):
            response = self.client.get("/api/admin/users", headers={"X-User-Role": "admin"})
        self.assertEqual(response.status_code, 403)

    def test_recipe_submission_uses_session_identity_and_forces_pending_member(self):
        member = {"id": 23, "name": "Member", "email": "member@example.test", "role": "member", "status": "active"}
        with self.client.session_transaction() as session:
            session["user_id"] = 23
            session["csrf_token"] = "csrf-test"
        body = {
            "title": "Canh rau",
            "ingredients": [{"name": "Rau"}],
            "steps": [{"description": "Nấu chín."}],
            "userId": 99,
            "role": "admin",
            "status": "APPROVED",
        }
        with patch("backend.security.authentication.get_user_by_id", return_value=member), \
             patch("backend.routes.api.repo.create_recipe", return_value={"id": 31, "status": "PENDING", "authorId": 23}) as create:
            response = self.client.post("/api/recipes", json=body, headers={"X-CSRF-Token": "csrf-test"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["recipe"]["status"], "PENDING")
        self.assertEqual(create.call_args.args[1], 23)

    def test_recipe_edit_and_delete_are_bound_to_the_session_user(self):
        member = {"id": 23, "name": "Member", "email": "member@example.test", "role": "member", "status": "active"}
        with self.client.session_transaction() as session:
            session["user_id"] = 23
            session["csrf_token"] = "csrf-test"
        headers = {"X-CSRF-Token": "csrf-test"}
        with patch("backend.security.authentication.get_user_by_id", return_value=member), \
             patch("backend.routes.api.repo.update_recipe", return_value={"id": 31, "status": "PENDING"}) as update, \
             patch("backend.routes.api.repo.delete_recipe", return_value=True) as delete:
            response = self.client.put("/api/recipes/31", json={"role": "admin", "createdBy": 88}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(update.call_args.args[:2], (31, 23))
            self.assertFalse(update.call_args.kwargs["admin"])
            response = self.client.delete("/api/recipes/31", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(delete.call_args.args[:2], (31, 23))
        self.assertFalse(delete.call_args.kwargs["admin"])

    def test_csrf_token_is_required_for_authenticated_writes(self):
        with self.client.session_transaction() as session:
            session["user_id"] = 23
            session["csrf_token"] = "expected-token"
        response = self.client.post("/api/recipes", json={})
        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.get_json()["error"])

    def test_public_recipe_filter_does_not_accept_client_status(self):
        with patch("backend.routes.api.repo.list_recipes", return_value=[]) as list_recipes:
            response = self.client.get("/api/recipes?status=PENDING&role=admin")
        self.assertEqual(response.status_code, 200)
        list_recipes.assert_called_once_with({})


if __name__ == "__main__":
    unittest.main()
