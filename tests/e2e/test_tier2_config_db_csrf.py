"""Tier 2 functional, negative, edge, and security tests for F1 (config), F2 (DB integrity), and F3 (CSRF/Origin)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from werkzeug.security import check_password_hash

from helpers.db_helper import DbHelper
from helpers.http_client import ApiClient
from helpers.server_harness import CookMateServerHarness


# ---------------------------------------------------------------------------
# F1: DEMO_MODE & OTP Policy Config (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f1_demo_mode_false_suppresses_terminal_otp(
    server_factory, db: DbHelper
) -> None:
    """T2-F1-01 (TC01): APP_ENV=testing + DEMO_MODE=false suppresses terminal OTP while returning 200."""
    srv = server_factory({"APP_ENV": "testing", "DEMO_MODE": "false", "OTP_IP_RATE_LIMIT_MAX": "500"})
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_t2_f1_01")

    mark = srv.output_mark()
    resp = client.forgot_password(user["email"])
    assert resp.status_code == 200
    assert resp.json().get("success") is True
    assert srv.find_otp_banners(email=user["email"], since_mark=mark) == []
    assert "[COOKMATE DEMO MODE]" not in srv.text_since(mark)


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f1_temp_password_cryptographic_uniqueness(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F1-02 (TC02): Two independent OTP resets issue distinct high-entropy >= 16-char passwords."""
    u1 = db.create_test_user(prefix="e2e_t2_f1_02a")
    u2 = db.create_test_user(prefix="e2e_t2_f1_02b")

    m1 = live_server.output_mark()
    assert api_client.forgot_password(u1["email"]).status_code == 200
    otp1 = live_server.wait_for_otp(u1["email"], since_mark=m1, timeout=5.0)
    pw1 = api_client.verify_otp(u1["email"], otp1).json()["temporary_password"]

    m2 = live_server.output_mark()
    assert api_client.forgot_password(u2["email"]).status_code == 200
    otp2 = live_server.wait_for_otp(u2["email"], since_mark=m2, timeout=5.0)
    pw2 = api_client.verify_otp(u2["email"], otp2).json()["temporary_password"]

    assert pw1 != pw2
    assert len(pw1) >= 16 and len(pw2) >= 16
    assert len(set(pw1)) >= 8 and len(set(pw2)) >= 8


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f1_production_non_https_verify_otp_blocked_403(
    server_factory, db: DbHelper
) -> None:
    """T2-F1-03: In APP_ENV=production over plain HTTP, verify-otp rejects with 403 to protect temporary_password."""
    srv = server_factory({"APP_ENV": "production", "DEMO_MODE": "false"})
    client = ApiClient(srv.base_url, allow_insecure_cookies=True)
    user = db.create_test_user(prefix="e2e_t2_f1_03")

    client.ensure_csrf()
    resp = client.verify_otp(user["email"], "123456")
    assert resp.status_code == 403
    data = resp.json()
    assert data.get("success") is False
    assert "temporary_password" not in data
    assert "csrf" not in data.get("error", "").lower()


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f1_testing_env_demo_false_keeps_http_verify_functional(
    server_factory, db: DbHelper
) -> None:
    """T2-F1-04: APP_ENV=testing + DEMO_MODE=false suppresses terminal OTP while keeping HTTP verify-otp functional."""
    srv = server_factory({"APP_ENV": "testing", "DEMO_MODE": "false", "OTP_IP_RATE_LIMIT_MAX": "500"})
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_t2_f1_04")

    mark = srv.output_mark()
    f_resp = client.forgot_password(user["email"])
    assert f_resp.status_code == 200
    assert srv.find_otp_banners(email=user["email"], since_mark=mark) == []
    assert db.get_latest_otp_for_user(user["user_id"]) is not None

    v_resp = client.verify_otp(user["email"], "000000")
    assert v_resp.status_code in (200, 400)
    assert v_resp.status_code != 403


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f1_banner_format_contains_exact_labels(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F1-05 (TC01): Terminal OTP banner matches the exact required label lines."""
    user = db.create_test_user(prefix="e2e_t2_f1_05")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200

    banner = live_server.wait_for_otp_banner(user["email"], since_mark=mark, timeout=5.0)
    lines = [ln.strip() for ln in banner["raw"].splitlines() if ln.strip()]
    assert lines[0].startswith("=" * 10)
    assert lines[1] == "[COOKMATE DEMO MODE] Password Reset OTP"
    assert lines[2].lower() == f"email: {user['email']}"
    assert lines[3] == f"OTP: {banner['otp']}"
    assert lines[4] == "Expires in: 5 minutes"
    assert lines[5].startswith("=" * 10)


# ---------------------------------------------------------------------------
# F2: password_reset_otps Schema & DB Integrity (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f2_otp_hash_never_plaintext_in_mysql(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F2-01 (TC08): password_reset_otps.otp_hash never contains raw 6-digit OTP."""
    user = db.create_test_user(prefix="e2e_t2_f2_01")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    row = db.get_latest_otp_for_user(user["user_id"])
    assert row is not None
    stored_hash = str(row["otp_hash"])
    assert otp not in stored_hash
    assert len(stored_hash) >= 32


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f2_user_password_hash_is_werkzeug_scrypt_never_plaintext(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F2-02 (TC08, TC11): Updated users.password_hash uses Werkzeug hash format and never stores plaintext."""
    user = db.create_test_user(prefix="e2e_t2_f2_02")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    temp_pw = api_client.verify_otp(user["email"], otp).json()["temporary_password"]
    row_after_otp = db.get_user_by_id(user["user_id"])
    assert row_after_otp is not None
    h1 = str(row_after_otp["password_hash"])
    assert temp_pw not in h1
    assert h1.startswith(("scrypt:", "pbkdf2:"))
    assert check_password_hash(h1, temp_pw)

    c = ApiClient(live_server.base_url)
    assert c.login(user["email"], temp_pw).status_code == 200
    new_pw = "PersonalSecret99!"
    assert c.change_password(temp_pw, new_pw, new_pw).status_code == 200

    row_after_change = db.get_user_by_id(user["user_id"])
    h2 = str(row_after_change["password_hash"])
    assert new_pw not in h2
    assert h2.startswith(("scrypt:", "pbkdf2:"))
    assert check_password_hash(h2, new_pw)


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f2_cascade_delete_removes_user_otp_rows(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F2-03 (TC08): Deleting a user from users cascades and removes its password_reset_otps rows."""
    user = db.create_test_user(prefix="e2e_t2_f2_03")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    assert len(db.get_otps_for_user(user["user_id"])) == 1

    deleted = db.delete_user_by_id(user["user_id"])
    assert deleted == 1
    assert db.get_otps_for_user(user["user_id"]) == []


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f2_utc_timestamps_consistent_on_insert_and_use(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F2-04 (TC04): created_at, expires_at (+5m), and used_at align with MySQL UTC_TIMESTAMP()."""
    user = db.create_test_user(prefix="e2e_t2_f2_04")
    before_utc = db.get_utc_now()
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    after_utc = db.get_utc_now()

    row = db.get_latest_otp_for_user(user["user_id"])
    assert row is not None
    assert before_utc - timedelta(seconds=5) <= row["created_at"] <= after_utc + timedelta(seconds=5)
    assert 298 <= int(row["ttl_seconds"]) <= 302
    assert row["used_at"] is None

    assert api_client.verify_otp(user["email"], otp).status_code == 200
    after_verify_utc = db.get_utc_now()
    used_row = db.get_latest_otp_for_user(user["user_id"])
    assert used_row is not None and used_row["used_at"] is not None
    assert used_row["created_at"] <= used_row["used_at"] <= after_verify_utc + timedelta(seconds=5)


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f2_bootstrap_schema_migration_is_idempotent(
    server_factory, db: DbHelper
) -> None:
    """T2-F2-05 (TC08): Booting a second server against migrated DB is idempotent and preserves rows."""
    srv1 = server_factory({"APP_ENV": "testing", "DEMO_MODE": "true", "OTP_IP_RATE_LIMIT_MAX": "500"})
    c1 = ApiClient(srv1.base_url)
    user = db.create_test_user(prefix="e2e_t2_f2_05")
    mark = srv1.output_mark()
    assert c1.forgot_password(user["email"]).status_code == 200
    srv1.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    rows_before = db.get_otps_for_user(user["user_id"])
    assert len(rows_before) == 1

    srv2 = server_factory({"APP_ENV": "testing", "DEMO_MODE": "true", "OTP_IP_RATE_LIMIT_MAX": "500"})
    assert ApiClient(srv2.base_url).get("/api/health").status_code == 200
    rows_after = db.get_otps_for_user(user["user_id"])
    assert len(rows_after) == 1
    assert rows_after[0]["id"] == rows_before[0]["id"]


# ---------------------------------------------------------------------------
# F3: Unauthenticated R1 CSRF & Origin Enforcement (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f3_forged_csrf_token_rejected_403(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F3-01: Forged X-CSRF-Token returns 403 on all R1 and R4 endpoints."""
    user = db.create_test_user(prefix="e2e_t2_f3_01", password="CurrentPass1!")
    api_client.ensure_csrf()

    for path, body in (
        ("/api/auth/forgot-password", {"email": user["email"]}),
        ("/api/auth/verify-otp", {"email": user["email"], "otp": "123456"}),
        ("/api/auth/resend-otp", {"email": user["email"]}),
    ):
        r = api_client.post(path, body, csrf_override="forged-invalid-csrf-token")
        assert r.status_code == 403, f"{path} returned {r.status_code}"

    assert api_client.login(user["email"], "CurrentPass1!").status_code == 200
    r_cp = api_client.change_password(
        "CurrentPass1!", "NewStrongPass2!", "NewStrongPass2!", csrf_override="forged-token"
    )
    assert r_cp.status_code == 403


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f3_cross_session_csrf_token_rejected_403(
    live_server: CookMateServerHarness, api_client: ApiClient
) -> None:
    """T2-F3-02: Session A's CSRF token paired with Session B's cookie returns 403."""
    client_a = ApiClient(live_server.base_url)
    client_b = ApiClient(live_server.base_url)
    token_a = client_a.ensure_csrf()
    client_b.ensure_csrf()
    assert token_a != client_b.csrf_token

    for path, body in (
        ("/api/auth/forgot-password", {"email": "someone@cookmate.test"}),
        ("/api/auth/verify-otp", {"email": "someone@cookmate.test", "otp": "123456"}),
        ("/api/auth/resend-otp", {"email": "someone@cookmate.test"}),
    ):
        resp = client_b.post(path, body, csrf_override=token_a)
        assert resp.status_code == 403


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f3_disallowed_origin_header_rejected_403(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F3-03: Requests with disallowed Origin header return 403 Origin is not allowed."""
    user = db.create_test_user(prefix="e2e_t2_f3_03", password="CurrentPass1!")
    api_client.ensure_csrf()

    r_fp = api_client.forgot_password(user["email"], origin_override="https://evil.example")
    assert r_fp.status_code == 403
    assert "origin" in r_fp.json().get("error", "").lower()

    assert api_client.login(user["email"], "CurrentPass1!").status_code == 200
    r_cp = api_client.change_password(
        "CurrentPass1!", "NewStrongPass2!", "NewStrongPass2!", origin_override="https://evil.example"
    )
    assert r_cp.status_code == 403


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f3_same_origin_header_allowed(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F3-04: Matching Origin + valid X-CSRF-Token succeeds with 200."""
    user = db.create_test_user(prefix="e2e_t2_f3_04")
    api_client.ensure_csrf()
    resp = api_client.forgot_password(user["email"], origin_override=live_server.base_url)
    assert resp.status_code == 200
    assert resp.json().get("success") is True


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f3_change_password_without_csrf_rejected_403(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F3-05: Authenticated POST /api/auth/change-password missing X-CSRF-Token returns 403."""
    user = db.create_test_user(prefix="e2e_t2_f3_05", password="CurrentPass1!")
    assert api_client.login(user["email"], "CurrentPass1!").status_code == 200
    resp = api_client.change_password(
        "CurrentPass1!", "NewStrongPass2!", "NewStrongPass2!", include_csrf=False
    )
    assert resp.status_code == 403
    assert "csrf" in resp.json().get("error", "").lower()
