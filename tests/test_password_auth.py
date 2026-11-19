"""Integration and security tests for Forgot Password (Terminal OTP) & Change Password."""

from __future__ import annotations

import contextlib
import io
import logging
import re
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from app import create_app
from backend.database.connection import check_database, fetch_all, fetch_one, transaction
from backend.database.repositories import register_user
from backend.database.schema_upgrade import ensure_runtime_schema
from backend.security.rate_limit import OTPRateLimiter, _hash_rate_key, reset_otp_rate_limits


class PasswordAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            check_database()
        except Exception as exc:
            raise unittest.SkipTest(f"MySQL unavailable for password auth tests: {exc}")
        ensure_runtime_schema()

    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-password-auth-secret-key",
            "DEMO_MODE": True,
            "APP_ENV": "development",
            "CORS_ALLOWED_ORIGINS": (),
        })
        self.client = self.app.test_client()
        self._created_user_ids: list[int] = []

    def tearDown(self):
        reset_otp_rate_limits(self.app)
        if self._created_user_ids:
            placeholders = ",".join(["%s"] * len(self._created_user_ids))
            with transaction() as (_, cur):
                cur.execute(f"DELETE FROM users WHERE user_id IN ({placeholders})", tuple(self._created_user_ids))

    def _create_user(self, password: str = "InitialPass#123") -> dict:
        email = f"otp_test_{uuid.uuid4().hex[:12]}@example.test"
        user = register_user("Test User", email, password)
        self._created_user_ids.append(int(user["id"]))
        return user

    def _csrf_headers(self, client=None, *, base_url: str = "http://localhost") -> dict[str, str]:
        target = client or self.client
        resp = target.get("/api/auth/csrf", base_url=base_url)
        self.assertEqual(resp.status_code, 200)
        token = resp.get_json()["csrfToken"]
        return {"X-CSRF-Token": token}

    def _request_otp_and_capture_banner(
        self,
        email: str,
        *,
        app=None,
        client=None,
        endpoint: str = "/api/auth/forgot-password",
    ) -> tuple[object, str]:
        target_client = client or self.client
        headers = self._csrf_headers(target_client)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            resp = target_client.post(endpoint, json={"email": email}, headers=headers)
        return resp, buf.getvalue()

    @staticmethod
    def _extract_otp(stdout_text: str) -> str:
        match = re.search(r"OTP:\s*(\d{6})", stdout_text)
        if not match:
            raise AssertionError(f"Expected 6-digit OTP in stdout banner, got:\n{stdout_text}")
        return match.group(1)

    def test_tc01_forgot_password_demo_mode_banner_non_disclosing_and_csrf(self):
        user = self._create_user()

        # Missing CSRF -> 403
        for path in ("/api/auth/forgot-password", "/api/auth/resend-otp", "/api/auth/verify-otp"):
            resp = self.client.post(path, json={"email": user["email"], "otp": "123456"})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(resp.get_json()["error"], "CSRF validation failed.")

        # Invalid email -> 400
        headers = self._csrf_headers()
        bad_resp = self.client.post("/api/auth/forgot-password", json={"email": "not-an-email"}, headers=headers)
        self.assertEqual(bad_resp.status_code, 400)
        self.assertEqual(bad_resp.get_json()["error"], "Email không hợp lệ.")

        # Registered email -> 200 generic response + exact terminal banner
        reg_resp, reg_out = self._request_otp_and_capture_banner(user["email"])
        self.assertEqual(reg_resp.status_code, 200)
        reg_json = reg_resp.get_json()
        self.assertTrue(reg_json["success"])
        self.assertEqual(reg_json["message"], "Nếu email tồn tại trong hệ thống, mã xác minh đã được cấp.")
        self.assertNotIn("otp", reg_json)
        self.assertIn("[COOKMATE DEMO MODE] Password Reset OTP", reg_out)
        self.assertIn(f"Email: {user['email']}", reg_out)
        self.assertIn("Expires in: 5 minutes", reg_out)
        otp = self._extract_otp(reg_out)
        self.assertNotIn(otp, reg_resp.get_data(as_text=True))

        # Unregistered email -> identical 200 response + empty stdout
        missing_email = f"missing_{uuid.uuid4().hex[:10]}@example.test"
        miss_resp, miss_out = self._request_otp_and_capture_banner(missing_email)
        self.assertEqual(miss_resp.status_code, 200)
        self.assertEqual(miss_resp.get_json(), reg_json)
        self.assertEqual(miss_out, "")

        # DEMO_MODE=False -> prints nothing to terminal even for registered user
        prod_like_app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-password-auth-secret-key",
            "DEMO_MODE": False,
            "CORS_ALLOWED_ORIGINS": (),
        })
        self.addCleanup(reset_otp_rate_limits, prod_like_app)
        prod_client = prod_like_app.test_client()
        user2 = self._create_user()
        off_resp, off_out = self._request_otp_and_capture_banner(user2["email"], client=prod_client)
        self.assertEqual(off_resp.status_code, 200)
        self.assertEqual(off_out, "")

    def test_tc02_tc08_tc09_verify_otp_generates_strong_temp_password_hashed_in_db_and_logs_in(self):
        old_password = "OldUserPass#123"
        user = self._create_user(old_password)
        req_resp, req_out = self._request_otp_and_capture_banner(user["email"])
        self.assertEqual(req_resp.status_code, 200)
        otp = self._extract_otp(req_out)

        # TC08: otp_hash in DB is HMAC-SHA256, never plaintext
        otp_row = fetch_one(
            "SELECT otp_hash, attempts, used_at FROM password_reset_otps WHERE user_id=%s ORDER BY id DESC LIMIT 1",
            (user["id"],),
        )
        self.assertIsNotNone(otp_row)
        self.assertTrue(otp_row["otp_hash"].startswith("hmac-sha256$"))
        self.assertNotIn(otp, otp_row["otp_hash"])

        headers = self._csrf_headers()
        verify_resp = self.client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "otp": otp},
            headers=headers,
        )
        self.assertEqual(verify_resp.status_code, 200)
        payload = verify_resp.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["message"], "Khôi phục mật khẩu thành công")
        temp_pw = payload["temporary_password"]
        self.assertGreaterEqual(len(temp_pw), 16)
        self.assertTrue(any(c.isupper() for c in temp_pw))
        self.assertTrue(any(c.islower() for c in temp_pw))
        self.assertTrue(any(c.isdigit() for c in temp_pw))
        self.assertTrue(any(c in "!@#$%^&*-_=+" for c in temp_pw))

        # TC08: users.password_hash is Werkzeug scrypt hash, never plaintext
        user_row = fetch_one("SELECT password_hash FROM users WHERE user_id=%s", (user["id"],))
        self.assertTrue(user_row["password_hash"].startswith("scrypt:"))
        self.assertNotEqual(user_row["password_hash"], temp_pw)

        # TC09: login with temporary password succeeds, old password fails
        fail_login = self.client.post("/api/auth/login", json={"email": user["email"], "password": old_password})
        self.assertEqual(fail_login.status_code, 401)
        ok_login = self.client.post("/api/auth/login", json={"email": user["email"], "password": temp_pw})
        self.assertEqual(ok_login.status_code, 200)
        self.assertTrue(ok_login.get_json()["success"])

    def test_tc03_wrong_otp_rejected_and_increments_attempts(self):
        user = self._create_user()
        _, out = self._request_otp_and_capture_banner(user["email"])
        otp = self._extract_otp(out)
        wrong_otp = "000000" if otp != "000000" else "999999"

        headers = self._csrf_headers()
        for expected_attempts in (1, 2):
            resp = self.client.post(
                "/api/auth/verify-otp",
                json={"email": user["email"], "otp": wrong_otp},
                headers=headers,
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.get_json()["error"], "Mã xác minh không đúng.")
            row = fetch_one(
                "SELECT attempts, used_at FROM password_reset_otps WHERE user_id=%s ORDER BY id DESC LIMIT 1",
                (user["id"],),
            )
            self.assertEqual(row["attempts"], expected_attempts)
            self.assertIsNone(row["used_at"])

    def test_tc04_expired_otp_is_rejected(self):
        user = self._create_user()
        _, out = self._request_otp_and_capture_banner(user["email"])
        otp = self._extract_otp(out)

        with transaction() as (_, cur):
            cur.execute(
                "UPDATE password_reset_otps SET expires_at = DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 SECOND) WHERE user_id=%s",
                (user["id"],),
            )

        headers = self._csrf_headers()
        resp = self.client.post("/api/auth/verify-otp", json={"email": user["email"], "otp": otp}, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "Mã xác minh đã hết hạn. Vui lòng gửi lại mã.")

    def test_tc05_exceeding_5_wrong_attempts_locks_otp(self):
        user = self._create_user()
        _, out = self._request_otp_and_capture_banner(user["email"])
        otp = self._extract_otp(out)
        wrong_otp = "000000" if otp != "000000" else "999999"

        headers = self._csrf_headers()
        for idx in range(1, 6):
            resp = self.client.post(
                "/api/auth/verify-otp",
                json={"email": user["email"], "otp": wrong_otp},
                headers=headers,
            )
            if idx < 5:
                self.assertEqual(resp.status_code, 400)
            else:
                self.assertEqual(resp.status_code, 429)
                self.assertEqual(resp.get_json()["error"], "Bạn đã nhập sai quá 5 lần. Mã xác minh đã bị vô hiệu hóa.")

        row = fetch_one(
            "SELECT attempts, used_at FROM password_reset_otps WHERE user_id=%s ORDER BY id DESC LIMIT 1",
            (user["id"],),
        )
        self.assertEqual(row["attempts"], 5)
        self.assertIsNotNone(row["used_at"])

        # Even submitting the real OTP afterwards is locked out
        sixth = self.client.post("/api/auth/verify-otp", json={"email": user["email"], "otp": otp}, headers=headers)
        self.assertEqual(sixth.status_code, 429)

    def test_tc06_reusing_verified_otp_sequential_and_concurrent(self):
        # (a) Sequential reuse
        user1 = self._create_user()
        _, out1 = self._request_otp_and_capture_banner(user1["email"])
        otp1 = self._extract_otp(out1)
        headers1 = self._csrf_headers()
        first = self.client.post("/api/auth/verify-otp", json={"email": user1["email"], "otp": otp1}, headers=headers1)
        self.assertEqual(first.status_code, 200)
        second = self.client.post("/api/auth/verify-otp", json={"email": user1["email"], "otp": otp1}, headers=headers1)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.get_json()["error"], "Mã xác minh không hợp lệ hoặc đã được sử dụng.")

        # (b) Concurrent barrier verification (5 threads <= MYSQL_POOL_SIZE=5)
        user2 = self._create_user()
        _, out2 = self._request_otp_and_capture_banner(user2["email"])
        otp2 = self._extract_otp(out2)

        thread_count = 5
        barrier = threading.Barrier(thread_count)
        results: list[tuple[int, dict]] = []
        results_lock = threading.Lock()

        def worker():
            worker_client = self.app.test_client()
            w_headers = self._csrf_headers(worker_client)
            barrier.wait(timeout=10)
            resp = worker_client.post(
                "/api/auth/verify-otp",
                json={"email": user2["email"], "otp": otp2},
                headers=w_headers,
            )
            with results_lock:
                results.append((resp.status_code, resp.get_json()))

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        statuses = [code for code, _ in results]
        self.assertEqual(len(statuses), thread_count)
        self.assertEqual(statuses.count(200), 1)
        self.assertEqual(statuses.count(400), thread_count - 1)
        winning_payload = next(payload for code, payload in results if code == 200)
        login_resp = self.client.post(
            "/api/auth/login",
            json={"email": user2["email"], "password": winning_payload["temporary_password"]},
        )
        self.assertEqual(login_resp.status_code, 200)

        # (c) Resend invalidates prior OTP
        no_cooldown_app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-password-auth-secret-key",
            "DEMO_MODE": True,
            "OTP_RESEND_COOLDOWN_SECONDS": 0,
            "CORS_ALLOWED_ORIGINS": (),
        })
        self.addCleanup(reset_otp_rate_limits, no_cooldown_app)
        nc_client = no_cooldown_app.test_client()
        user3 = self._create_user()
        _, old_out = self._request_otp_and_capture_banner(user3["email"], client=nc_client)
        old_otp = self._extract_otp(old_out)
        _, new_out = self._request_otp_and_capture_banner(
            user3["email"], client=nc_client, endpoint="/api/auth/resend-otp"
        )
        new_otp = self._extract_otp(new_out)

        nc_headers = self._csrf_headers(nc_client)
        old_try = nc_client.post("/api/auth/verify-otp", json={"email": user3["email"], "otp": old_otp}, headers=nc_headers)
        if old_otp != new_otp:
            self.assertEqual(old_try.status_code, 400)
            new_try = nc_client.post("/api/auth/verify-otp", json={"email": user3["email"], "otp": new_otp}, headers=nc_headers)
            self.assertEqual(new_try.status_code, 200)

    def test_tc07_rate_limiting_blocks_rapid_requests_without_disclosing_email(self):
        user = self._create_user()
        missing_email = f"missing_rl_{uuid.uuid4().hex[:10]}@example.test"

        # Registered email: 1st succeeds, immediate 2nd returns 429
        r1, _ = self._request_otp_and_capture_banner(user["email"])
        self.assertEqual(r1.status_code, 200)
        r2, out2 = self._request_otp_and_capture_banner(user["email"], endpoint="/api/auth/resend-otp")
        self.assertEqual(r2.status_code, 429)
        self.assertEqual(r2.get_json()["error"], "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút.")
        self.assertEqual(out2, "")

        # Unregistered email: identical behavior (1st -> 200, 2nd -> 429)
        m1, _ = self._request_otp_and_capture_banner(missing_email)
        self.assertEqual(m1.status_code, 200)
        m2, _ = self._request_otp_and_capture_banner(missing_email, endpoint="/api/auth/resend-otp")
        self.assertEqual(m2.status_code, 429)
        self.assertEqual(m2.get_json()["error"], "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút.")

    def test_production_security_defaults_and_proxy_header_spoofing_protection(self):
        user = self._create_user()
        _, out = self._request_otp_and_capture_banner(user["email"])
        otp = self._extract_otp(out)

        # 1. Default create_app({"APP_ENV": "production"}) enforces strict security defaults
        default_prod_app = create_app({
            "TESTING": True,
            "APP_ENV": "production",
            "SECRET_KEY": "test-password-auth-secret-key",
            "CORS_ALLOWED_ORIGINS": (),
        })
        self.addCleanup(reset_otp_rate_limits, default_prod_app)
        self.assertIs(default_prod_app.config["DEMO_MODE"], False)
        self.assertIs(default_prod_app.config["SESSION_COOKIE_SECURE"], True)
        self.assertEqual(default_prod_app.config["SESSION_COOKIE_SAMESITE"], "None")
        self.assertIs(default_prod_app.config["TRUST_PROXY_HEADERS"], False)

        default_client = default_prod_app.test_client()
        # DEMO_MODE=False in production prints nothing to terminal
        https_csrf = self._csrf_headers(default_client, base_url="https://localhost")
        user2 = self._create_user()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            forgot_resp = default_client.post(
                "/api/auth/forgot-password",
                json={"email": user2["email"]},
                headers=https_csrf,
                base_url="https://localhost",
            )
        self.assertEqual(forgot_resp.status_code, 200)
        self.assertEqual(buf.getvalue(), "")

        # Plain HTTP request on default production app is rejected even with forged X-Forwarded-* headers
        with default_client.session_transaction() as sess:
            sess["csrf_token"] = "plain-http-csrf"
        spoofed_http_resp = default_client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "otp": otp},
            headers={
                "X-CSRF-Token": "plain-http-csrf",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "evil.com",
            },
        )
        self.assertEqual(spoofed_http_resp.status_code, 403)
        self.assertIn("HTTPS", spoofed_http_resp.get_json()["error"])

        # Cross-origin request with forged X-Forwarded-Host is rejected
        spoofed_origin_resp = default_client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "otp": otp},
            headers={
                "X-CSRF-Token": "plain-http-csrf",
                "Origin": "https://evil.com",
                "X-Forwarded-Host": "evil.com",
                "X-Forwarded-Proto": "https",
            },
        )
        self.assertEqual(spoofed_origin_resp.status_code, 403)
        self.assertEqual(spoofed_origin_resp.get_json()["error"], "Origin is not allowed.")

        # 2. Explicit TRUST_PROXY_HEADERS=True honors X-Forwarded-Proto but NEVER X-Forwarded-Host
        proxied_prod_app = create_app({
            "TESTING": True,
            "APP_ENV": "production",
            "SECRET_KEY": "test-password-auth-secret-key",
            "TRUST_PROXY_HEADERS": True,
            "SESSION_COOKIE_SECURE": False,
            "CORS_ALLOWED_ORIGINS": (),
        })
        self.addCleanup(reset_otp_rate_limits, proxied_prod_app)
        proxied_client = proxied_prod_app.test_client()
        proxied_headers = self._csrf_headers(proxied_client)

        # Plain HTTP still rejected
        http_resp = proxied_client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "otp": otp},
            headers=proxied_headers,
        )
        self.assertEqual(http_resp.status_code, 403)
        self.assertIn("HTTPS", http_resp.get_json()["error"])

        # Forged X-Forwarded-Host + evil Origin still rejected even when TRUST_PROXY_HEADERS=True
        evil_proxy_resp = proxied_client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "otp": otp},
            headers={
                **proxied_headers,
                "Origin": "https://evil.com",
                "X-Forwarded-Host": "evil.com",
                "X-Forwarded-Proto": "https",
            },
        )
        self.assertEqual(evil_proxy_resp.status_code, 403)
        self.assertEqual(evil_proxy_resp.get_json()["error"], "Origin is not allowed.")

        # Valid X-Forwarded-Proto=https succeeds
        https_resp = proxied_client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "otp": otp},
            headers={**proxied_headers, "X-Forwarded-Proto": "https"},
        )
        self.assertEqual(https_resp.status_code, 200)

    def test_non_ascii_otp_digits_rejected_without_incrementing_attempts(self):
        user = self._create_user()
        _, out = self._request_otp_and_capture_banner(user["email"])
        self._extract_otp(out)
        headers = self._csrf_headers()

        for non_ascii_otp in ("١٢٣٤٥٦", "１２３４٥٦", "１２３４５６"):
            resp = self.client.post(
                "/api/auth/verify-otp",
                json={"email": user["email"], "otp": non_ascii_otp},
                headers=headers,
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.get_json()["error"], "Mã xác minh phải gồm đúng 6 chữ số.")

        row = fetch_one(
            "SELECT attempts, used_at FROM password_reset_otps WHERE user_id=%s ORDER BY id DESC LIMIT 1",
            (user["id"],),
        )
        self.assertEqual(row["attempts"], 0)
        self.assertIsNone(row["used_at"])

    def test_verify_otp_rejects_control_characters_without_incrementing_attempts(self):
        user = self._create_user()
        _, out = self._request_otp_and_capture_banner(user["email"])
        otp = self._extract_otp(out)
        headers = self._csrf_headers()

        for bad_otp in (f"{otp}\n", f"\n{otp}", f"{otp}\r", f"{otp}\t", f"{otp}\x00", f"{otp}\x7f", "123456\n"):
            resp = self.client.post(
                "/api/auth/verify-otp",
                json={"email": user["email"], "otp": bad_otp},
                headers=headers,
            )
            self.assertEqual(resp.status_code, 400, f"Unexpected status for {bad_otp!r}")
            self.assertEqual(resp.get_json()["error"], "Mã xác minh phải gồm đúng 6 chữ số.")

        row = fetch_one(
            "SELECT attempts, used_at FROM password_reset_otps WHERE user_id=%s ORDER BY id DESC LIMIT 1",
            (user["id"],),
        )
        self.assertEqual(row["attempts"], 0)
        self.assertIsNone(row["used_at"])

        # Valid OTP still works after rejected control-char attempts
        ok_resp = self.client.post(
            "/api/auth/verify-otp",
            json={"email": user["email"], "otp": otp},
            headers=headers,
        )
        self.assertEqual(ok_resp.status_code, 200)

    def test_concurrent_forgot_password_db_rate_limiter_enforces_cooldown_without_fallback(self):
        user = self._create_user()
        test_ip = f"198.51.100.{int(uuid.uuid4().hex[:2], 16) % 200 + 10}"

        def run_five_threads():
            barrier = threading.Barrier(5)
            statuses: list[int] = []
            lock = threading.Lock()

            def worker():
                client = self.app.test_client()
                headers = self._csrf_headers(client)
                barrier.wait(timeout=10)
                resp = client.post(
                    "/api/auth/forgot-password",
                    json={"email": user["email"]},
                    headers=headers,
                    environ_base={"REMOTE_ADDR": test_ip},
                )
                with lock:
                    statuses.append(resp.status_code)

            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
            return statuses

        with self.assertNoLogs("backend.security.rate_limit", level=logging.WARNING):
            # Cold path: 5 concurrent requests for brand new email/IP
            cold_buf = io.StringIO()
            with contextlib.redirect_stdout(cold_buf):
                cold_statuses = run_five_threads()
            self.assertEqual(len(cold_statuses), 5)
            self.assertEqual(cold_statuses.count(200), 1)
            self.assertEqual(cold_statuses.count(429), 4)
            self.assertEqual(cold_buf.getvalue().count("[COOKMATE DEMO MODE] Password Reset OTP"), 1)

            otp_count = fetch_one(
                "SELECT COUNT(*) AS cnt FROM password_reset_otps WHERE user_id=%s",
                (user["id"],),
            )["cnt"]
            self.assertEqual(otp_count, 1)

            # Warm path: 5 more concurrent requests inside cooldown
            warm_buf = io.StringIO()
            with contextlib.redirect_stdout(warm_buf):
                warm_statuses = run_five_threads()
            self.assertEqual(warm_statuses, [429, 429, 429, 429, 429])
            self.assertEqual(warm_buf.getvalue(), "")

    def test_concurrent_otp_rate_limiter_db_max_requests_without_fallback(self):
        limiter = OTPRateLimiter(secret_key="test-password-auth-secret-key", use_db=True)
        self.addCleanup(limiter.reset)
        email = f"rl_conc_{uuid.uuid4().hex[:12]}@example.test"
        test_ip = f"198.51.100.{int(uuid.uuid4().hex[:2], 16) % 200 + 10}"
        barrier = threading.Barrier(5)
        results: list[bool] = []
        lock = threading.Lock()

        def worker():
            barrier.wait(timeout=10)
            allowed = limiter.check_and_record(
                email,
                test_ip,
                cooldown_seconds=0,
                max_requests=2,
                window_seconds=900,
                ip_max_requests=30,
                ip_window_seconds=300,
            )
            with lock:
                results.append(allowed)

        with self.assertNoLogs("backend.security.rate_limit", level=logging.WARNING):
            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

        self.assertEqual(len(results), 5)
        self.assertEqual(results.count(True), 2)
        self.assertEqual(results.count(False), 3)

    def test_concurrent_forgot_password_distinct_emails_same_warm_ip_succeeds(self):
        warmup_user = self._create_user()
        users = [self._create_user() for _ in range(5)]
        test_ip = f"198.51.100.{int(uuid.uuid4().hex[:2], 16) % 200 + 10}"

        # Warm the IP row first
        warm_headers = self._csrf_headers()
        with contextlib.redirect_stdout(io.StringIO()):
            warm_resp = self.client.post(
                "/api/auth/forgot-password",
                json={"email": warmup_user["email"]},
                headers=warm_headers,
                environ_base={"REMOTE_ADDR": test_ip},
            )
        self.assertEqual(warm_resp.status_code, 200)

        barrier = threading.Barrier(5)
        statuses: list[int] = []
        lock = threading.Lock()

        def worker(email: str):
            client = self.app.test_client()
            headers = self._csrf_headers(client)
            barrier.wait(timeout=10)
            resp = client.post(
                "/api/auth/forgot-password",
                json={"email": email},
                headers=headers,
                environ_base={"REMOTE_ADDR": test_ip},
            )
            with lock:
                statuses.append(resp.status_code)

        race_buf = io.StringIO()
        with self.assertNoLogs("backend.security.rate_limit", level=logging.WARNING), contextlib.redirect_stdout(
            race_buf
        ):
            threads = [threading.Thread(target=worker, args=(u["email"],)) for u in users]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

        self.assertEqual(statuses, [200, 200, 200, 200, 200])
        self.assertEqual(race_buf.getvalue().count("[COOKMATE DEMO MODE] Password Reset OTP"), 5)
        ip_hash = _hash_rate_key("ip", test_ip, str(self.app.config["SECRET_KEY"]))
        ip_row = fetch_one(
            "SELECT hit_count FROM otp_rate_limits WHERE scope='ip' AND key_hash=%s",
            (ip_hash,),
        )
        self.assertIsNotNone(ip_row)
        self.assertEqual(ip_row["hit_count"], 6)

    def test_db_rate_limiter_contention_exhaustion_fails_closed_without_memory_fallback(self):
        limiter = OTPRateLimiter(secret_key="test-password-auth-secret-key", use_db=True)

        class DeadlockError(Exception):
            errno = 1213

        select_calls = 0
        delete_calls = 0

        class FailingCursor:
            def execute(self, sql, *args, **kwargs):
                nonlocal select_calls, delete_calls
                if "DELETE FROM otp_rate_limits" in sql:
                    delete_calls += 1
                else:
                    select_calls += 1
                raise DeadlockError("1213 (40001): Deadlock found when trying to get lock")

            def fetchall(self):
                return []

        @contextlib.contextmanager
        def fake_transaction():
            yield None, FailingCursor()

        with patch("backend.security.rate_limit.transaction", side_effect=fake_transaction), patch(
            "backend.security.rate_limit.time.sleep"
        ):
            with self.assertLogs("backend.security.rate_limit", level=logging.ERROR) as log_ctx:
                allowed = limiter.check_and_record("deadlock@example.test", "127.0.0.1")

        self.assertFalse(allowed)
        self.assertEqual(delete_calls, 1)
        self.assertEqual(select_calls, 6)
        self.assertEqual(len(limiter._email_hits), 0)
        self.assertTrue(any("failing closed" in msg for msg in log_ctx.output))

    def test_valid_email_rejects_non_string_and_control_chars(self):
        headers = self._csrf_headers()
        bad_emails = [
            ["a@b.com"],
            12345,
            {"email": "a@b.com"},
            "a\x00@b.com",
            "a\nb@c.com",
            "a@b.com\r",
            "['a@b.com']",
            "a..b@c.com",
            ".a@b.com",
            "a.@b.com",
        ]
        for bad in bad_emails:
            r1 = self.client.post("/api/auth/forgot-password", json={"email": bad}, headers=headers)
            self.assertEqual(r1.status_code, 400, f"forgot-password accepted {bad!r}")
            self.assertEqual(r1.get_json()["error"], "Email không hợp lệ.")

            r2 = self.client.post("/api/auth/verify-otp", json={"email": bad, "otp": "123456"}, headers=headers)
            self.assertEqual(r2.status_code, 400, f"verify-otp accepted {bad!r}")
            self.assertEqual(r2.get_json()["error"], "Email không hợp lệ.")

            r3 = self.client.post(
                "/api/auth/register",
                json={"name": "Bad Email User", "email": bad, "password": "ValidPass#123"},
            )
            self.assertEqual(r3.status_code, 400, f"register accepted {bad!r}")

        # Whitespace-padded valid email still normalizes cleanly
        user = self._create_user()
        padded_resp, padded_out = self._request_otp_and_capture_banner(f"  {user['email'].upper()}  ")
        self.assertEqual(padded_resp.status_code, 200)
        self._extract_otp(padded_out)

    def test_multi_worker_rate_limit_consistent_for_registered_and_unregistered(self):
        user = self._create_user()
        missing_email = f"missing_mw_{uuid.uuid4().hex[:10]}@example.test"

        app1 = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-password-auth-secret-key",
            "DEMO_MODE": True,
            "APP_ENV": "development",
            "CORS_ALLOWED_ORIGINS": (),
        })
        app2 = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-password-auth-secret-key",
            "DEMO_MODE": True,
            "APP_ENV": "development",
            "CORS_ALLOWED_ORIGINS": (),
        })
        self.addCleanup(reset_otp_rate_limits, app1)
        self.addCleanup(reset_otp_rate_limits, app2)

        client1 = app1.test_client()
        client2 = app2.test_client()

        # Worker 1 accepts first request for both registered & unregistered emails
        r1, _ = self._request_otp_and_capture_banner(user["email"], client=client1)
        m1, _ = self._request_otp_and_capture_banner(missing_email, client=client1)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(m1.status_code, 200)

        # Verify otp_rate_limits stores only 64-char hex hashes (no plaintext email/IP)
        rows = fetch_all("SELECT scope, key_hash FROM otp_rate_limits")
        self.assertGreaterEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row["key_hash"]), 64)
            self.assertNotIn(user["email"], row["key_hash"])
            self.assertNotIn(missing_email, row["key_hash"])

        # Worker 2 (fresh OTPRateLimiter instance) enforces identical 429 for BOTH
        r2, out2 = self._request_otp_and_capture_banner(
            user["email"], client=client2, endpoint="/api/auth/resend-otp"
        )
        m2, _ = self._request_otp_and_capture_banner(
            missing_email, client=client2, endpoint="/api/auth/resend-otp"
        )
        self.assertEqual(r2.status_code, 429)
        self.assertEqual(m2.status_code, 429)
        self.assertEqual(r2.get_json(), m2.get_json())
        self.assertEqual(out2, "")

    def test_otp_rate_limiter_evicts_expired_keys(self):
        limiter = OTPRateLimiter(use_db=False, sweep_interval=0.2)
        for idx in range(50):
            allowed = limiter.check_and_record(
                f"evict_{idx}@example.test",
                f"10.0.0.{idx % 20}",
                cooldown_seconds=0,
                max_requests=5,
                window_seconds=1,
                ip_max_requests=100,
                ip_window_seconds=1,
            )
            self.assertTrue(allowed)
        self.assertEqual(len(limiter._email_hits), 50)
        self.assertEqual(len(limiter._ip_hits), 20)

        time.sleep(1.15)
        self.assertTrue(
            limiter.check_and_record(
                "fresh@example.test",
                "10.0.0.99",
                cooldown_seconds=0,
                max_requests=5,
                window_seconds=1,
                ip_max_requests=100,
                ip_window_seconds=1,
            )
        )
        self.assertEqual(len(limiter._email_hits), 1)
        self.assertEqual(len(limiter._ip_hits), 1)

    def test_tc11_to_tc15_change_password_flows_and_validation(self):
        initial_pw = "CurrentPass#123"
        new_pw = "UpdatedPass#456"
        user = self._create_user(initial_pw)

        login_resp = self.client.post("/api/auth/login", json={"email": user["email"], "password": initial_pw})
        self.assertEqual(login_resp.status_code, 200)
        csrf = login_resp.get_json()["csrfToken"]
        headers = {"X-CSRF-Token": csrf}

        # TC12: wrong current password -> 400
        wrong_curr = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "WrongPass#999", "new_password": new_pw, "confirm_password": new_pw},
            headers=headers,
        )
        self.assertEqual(wrong_curr.status_code, 400)
        self.assertEqual(wrong_curr.get_json()["error"], "Mật khẩu hiện tại không đúng.")

        # TC13: mismatched confirmation -> 400
        mismatch = self.client.post(
            "/api/auth/change-password",
            json={"current_password": initial_pw, "new_password": new_pw, "confirm_password": "Different#456"},
            headers=headers,
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(mismatch.get_json()["error"], "Mật khẩu xác nhận không khớp.")

        # TC14: short new password (<8 chars) -> 400
        too_short = self.client.post(
            "/api/auth/change-password",
            json={"current_password": initial_pw, "new_password": "short", "confirm_password": "short"},
            headers=headers,
        )
        self.assertEqual(too_short.status_code, 400)
        self.assertEqual(too_short.get_json()["error"], "Mật khẩu mới phải có ít nhất 8 ký tự.")

        # Same as current -> 400
        same_pw = self.client.post(
            "/api/auth/change-password",
            json={"current_password": initial_pw, "new_password": initial_pw, "confirm_password": initial_pw},
            headers=headers,
        )
        self.assertEqual(same_pw.status_code, 400)

        # TC11: valid change password -> 200, keeps session active, updates DB hash
        before_hash = fetch_one("SELECT password_hash FROM users WHERE user_id=%s", (user["id"],))["password_hash"]
        ok_resp = self.client.post(
            "/api/auth/change-password",
            json={"current_password": initial_pw, "new_password": new_pw, "confirm_password": new_pw},
            headers=headers,
        )
        self.assertEqual(ok_resp.status_code, 200)
        self.assertEqual(ok_resp.get_json(), {"success": True, "message": "Đổi mật khẩu thành công."})
        after_hash = fetch_one("SELECT password_hash FROM users WHERE user_id=%s", (user["id"],))["password_hash"]
        self.assertNotEqual(before_hash, after_hash)
        self.assertTrue(after_hash.startswith("scrypt:"))

        me_resp = self.client.get("/api/auth/me")
        self.assertTrue(me_resp.get_json()["authenticated"])

        # TC15: login with new password succeeds, old password fails
        other_client = self.app.test_client()
        self.assertEqual(
            other_client.post("/api/auth/login", json={"email": user["email"], "password": initial_pw}).status_code,
            401,
        )
        self.assertEqual(
            other_client.post("/api/auth/login", json={"email": user["email"], "password": new_pw}).status_code,
            200,
        )

    def test_tc16_change_password_strictly_bound_to_session_and_csrf_and_no_secret_logs(self):
        pw_a = "UserAPass#123"
        pw_b = "UserBPass#123"
        new_pw_a = "UserANewPass#999"
        user_a = self._create_user(pw_a)
        user_b = self._create_user(pw_b)

        # Unauthenticated -> 401
        unauth = self.client.post(
            "/api/auth/change-password",
            json={"current_password": pw_a, "new_password": new_pw_a, "confirm_password": new_pw_a},
        )
        self.assertEqual(unauth.status_code, 401)

        # Login as User A
        login_a = self.client.post("/api/auth/login", json={"email": user_a["email"], "password": pw_a})
        self.assertEqual(login_a.status_code, 200)
        csrf_a = login_a.get_json()["csrfToken"]

        # Authenticated without CSRF -> 403
        no_csrf = self.client.post(
            "/api/auth/change-password",
            json={"current_password": pw_a, "new_password": new_pw_a, "confirm_password": new_pw_a},
        )
        self.assertEqual(no_csrf.status_code, 403)

        # Attempt to target User B via payload user_id/userId/email while logged in as User A
        b_hash_before = fetch_one("SELECT password_hash FROM users WHERE user_id=%s", (user_b["id"],))["password_hash"]
        with self.assertNoLogs(self.app.logger, level=logging.INFO):
            resp = self.client.post(
                "/api/auth/change-password",
                json={
                    "user_id": user_b["id"],
                    "userId": user_b["id"],
                    "email": user_b["email"],
                    "current_password": pw_a,
                    "new_password": new_pw_a,
                    "confirm_password": new_pw_a,
                },
                headers={"X-CSRF-Token": csrf_a},
            )
        self.assertEqual(resp.status_code, 200)
        b_hash_after = fetch_one("SELECT password_hash FROM users WHERE user_id=%s", (user_b["id"],))["password_hash"]
        self.assertEqual(b_hash_before, b_hash_after)

        # User B can still log in with original password; User A uses new password
        b_client = self.app.test_client()
        self.assertEqual(
            b_client.post("/api/auth/login", json={"email": user_b["email"], "password": pw_b}).status_code,
            200,
        )
        a_client = self.app.test_client()
        self.assertEqual(
            a_client.post("/api/auth/login", json={"email": user_a["email"], "password": new_pw_a}).status_code,
            200,
        )


if __name__ == "__main__":
    unittest.main()
