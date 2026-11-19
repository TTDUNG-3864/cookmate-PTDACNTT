"""Tier 1 isolated tests for F1 (DEMO_MODE & OTP config), F2 (password_reset_otps schema), and F3 (R1 CSRF)."""

from __future__ import annotations

import re

import pytest

from helpers.db_helper import DbHelper
from helpers.http_client import ApiClient
from helpers.server_harness import CookMateServerHarness


# ---------------------------------------------------------------------------
# F1: DEMO_MODE & OTP Policy Config (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f1_demo_mode_enabled_prints_otp_banner(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F1-01 (TC01): DEMO_MODE=true prints the OTP banner to Flask terminal output."""
    user = db.create_test_user(prefix="e2e_f1_01")
    mark = live_server.output_mark()

    resp = api_client.forgot_password(user["email"])
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    banner = live_server.wait_for_otp_banner(user["email"], since_mark=mark, timeout=5.0)
    assert "[COOKMATE DEMO MODE] Password Reset OTP" in banner["raw"]
    assert user["email"] in banner["email"].lower()


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f1_otp_format_is_strictly_six_digits(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F1-02 (TC01): Issued terminal OTPs are strictly 6 numeric digits."""
    u1 = db.create_test_user(prefix="e2e_f1_02a")
    u2 = db.create_test_user(prefix="e2e_f1_02b")

    mark1 = live_server.output_mark()
    assert api_client.forgot_password(u1["email"]).status_code == 200
    otp1 = live_server.wait_for_otp(u1["email"], since_mark=mark1, timeout=5.0)

    mark2 = live_server.output_mark()
    assert api_client.forgot_password(u2["email"]).status_code == 200
    otp2 = live_server.wait_for_otp(u2["email"], since_mark=mark2, timeout=5.0)

    assert re.fullmatch(r"\d{6}", otp1)
    assert re.fullmatch(r"\d{6}", otp2)


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f1_otp_expiry_window_is_five_minutes(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F1-03 (TC04): Banner states 5 minutes and DB expires_at - created_at == 300s in UTC."""
    user = db.create_test_user(prefix="e2e_f1_03")
    mark = live_server.output_mark()

    resp = api_client.forgot_password(user["email"])
    assert resp.status_code == 200
    banner = live_server.wait_for_otp_banner(user["email"], since_mark=mark, timeout=5.0)
    assert "5 minutes" in banner["expires"].lower()

    row = db.get_latest_otp_for_user(user["user_id"])
    assert row is not None
    assert 298 <= int(row["ttl_seconds"]) <= 302


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f1_temp_password_policy_min_16_chars(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F1-04 (TC02): Verified OTP returns a high-strength temporary password >= 16 chars."""
    user = db.create_test_user(prefix="e2e_f1_04")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    verify_resp = api_client.verify_otp(user["email"], otp)
    assert verify_resp.status_code == 200
    data = verify_resp.json()
    assert data.get("success") is True
    temp_pw = data.get("temporary_password", "")
    assert isinstance(temp_pw, str)
    assert len(temp_pw) >= 16
    assert not any(ch.isspace() for ch in temp_pw)
    char_classes = sum(
        [
            any(c.islower() for c in temp_pw),
            any(c.isupper() for c in temp_pw),
            any(c.isdigit() for c in temp_pw),
            any(not c.isalnum() for c in temp_pw),
        ]
    )
    assert char_classes >= 2


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f1_max_attempts_policy_is_five(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F1-05 (TC05): Wrong OTP attempts 1..4 return 400 and the 5th returns 429 lockout."""
    user = db.create_test_user(prefix="e2e_f1_05")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    wrong_otp = "000000" if otp != "000000" else "999999"

    for attempt_num in range(1, 5):
        r = api_client.verify_otp(user["email"], wrong_otp)
        assert r.status_code == 400, f"Attempt {attempt_num} expected 400, got {r.status_code}: {r.text}"

    r5 = api_client.verify_otp(user["email"], wrong_otp)
    assert r5.status_code == 429, f"5th wrong attempt expected 429, got {r5.status_code}: {r5.text}"


# ---------------------------------------------------------------------------
# F2: password_reset_otps Schema Migration & DB Integrity (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f2_password_reset_otps_table_exists(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T1-F2-01 (TC08): Table cookmate.password_reset_otps exists after server bootstrap."""
    assert db.table_exists("password_reset_otps") is True


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f2_password_reset_otps_required_columns(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T1-F2-02 (TC08): password_reset_otps has all 7 required columns with expected constraints."""
    cols = {c["COLUMN_NAME"]: c for c in db.get_table_columns("password_reset_otps")}
    expected = ("id", "user_id", "otp_hash", "expires_at", "attempts", "created_at", "used_at")
    for name in expected:
        assert name in cols, f"Missing column {name} in password_reset_otps"

    assert cols["id"]["COLUMN_KEY"] == "PRI"
    assert "auto_increment" in str(cols["id"]["EXTRA"]).lower()
    assert cols["user_id"]["IS_NULLABLE"] == "NO"
    assert cols["otp_hash"]["DATA_TYPE"] in {"varchar", "char", "text"}
    assert cols["expires_at"]["DATA_TYPE"] in {"datetime", "timestamp"}
    assert str(cols["attempts"]["COLUMN_DEFAULT"]) == "0"
    assert cols["used_at"]["IS_NULLABLE"] == "YES"


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f2_foreign_key_to_users_on_delete_cascade(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T1-F2-03 (TC08): password_reset_otps.user_id references users(user_id) ON DELETE CASCADE."""
    fks = db.get_foreign_keys("password_reset_otps")
    matching = [
        fk
        for fk in fks
        if fk["COLUMN_NAME"] == "user_id"
        and fk["REFERENCED_TABLE_NAME"] == "users"
        and fk["REFERENCED_COLUMN_NAME"] == "user_id"
    ]
    assert matching, f"Expected FK user_id -> users.user_id, got {fks}"
    assert matching[0]["DELETE_RULE"] == "CASCADE"


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f2_index_on_user_id_and_created_at(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T1-F2-04 (TC08): Composite index on (user_id, created_at) exists on password_reset_otps."""
    indexes = db.get_table_indexes("password_reset_otps")
    by_name: dict[str, list[str]] = {}
    for row in indexes:
        by_name.setdefault(row["INDEX_NAME"], []).append(row["COLUMN_NAME"])
    assert any(cols[:2] == ["user_id", "created_at"] for cols in by_name.values()), (
        f"Expected composite index on (user_id, created_at), got {by_name}"
    )


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f2_users_table_schema_untouched(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T1-F2-05 (TC08): users table retains its original columns plus must_change_password."""
    cols = [c["COLUMN_NAME"] for c in db.get_table_columns("users")]
    assert cols == [
        "user_id",
        "full_name",
        "email",
        "password_hash",
        "role",
        "status",
        "must_change_password",
        "avatar_url",
        "bio",
        "created_at",
    ]


# ---------------------------------------------------------------------------
# F3: Unauthenticated R1 CSRF Enforcement (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f3_csrf_endpoint_issues_token_and_session(
    live_server: CookMateServerHarness, api_client: ApiClient
) -> None:
    """T1-F3-01: GET /api/auth/csrf issues non-empty csrfToken and Flask session cookie."""
    resp = api_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json().get("csrfToken", "")
    assert isinstance(token, str) and len(token) >= 16
    assert "session" in api_client.session.cookies


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f3_forgot_password_requires_csrf_token(
    live_server: CookMateServerHarness, api_client: ApiClient
) -> None:
    """T1-F3-02: Unauthenticated POST /api/auth/forgot-password without X-CSRF-Token returns 403."""
    api_client.ensure_csrf()
    resp = api_client.post(
        "/api/auth/forgot-password",
        {"email": "nobody@cookmate.test"},
        include_csrf=False,
    )
    assert resp.status_code == 403
    assert resp.json().get("success") is False
    assert "csrf" in resp.json().get("error", "").lower()


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f3_verify_otp_requires_csrf_token(
    live_server: CookMateServerHarness, api_client: ApiClient
) -> None:
    """T1-F3-03: Unauthenticated POST /api/auth/verify-otp without X-CSRF-Token returns 403."""
    api_client.ensure_csrf()
    resp = api_client.post(
        "/api/auth/verify-otp",
        {"email": "nobody@cookmate.test", "otp": "123456"},
        include_csrf=False,
    )
    assert resp.status_code == 403
    assert resp.json().get("success") is False
    assert "csrf" in resp.json().get("error", "").lower()


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f3_resend_otp_requires_csrf_token(
    live_server: CookMateServerHarness, api_client: ApiClient
) -> None:
    """T1-F3-04: Unauthenticated POST /api/auth/resend-otp without X-CSRF-Token returns 403."""
    api_client.ensure_csrf()
    resp = api_client.post(
        "/api/auth/resend-otp",
        {"email": "nobody@cookmate.test"},
        include_csrf=False,
    )
    assert resp.status_code == 403
    assert resp.json().get("success") is False
    assert "csrf" in resp.json().get("error", "").lower()


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f3_guest_chatbot_still_accessible_without_auth(
    live_server: CookMateServerHarness, api_client: ApiClient
) -> None:
    """T1-F3-05: Guest /api/chatbot/sessions and /api/chatbot still work without CSRF/login."""
    sess_resp = api_client.post("/api/chatbot/sessions", {}, include_csrf=False)
    assert sess_resp.status_code == 201
    session_id = sess_resp.json().get("session_id")
    assert session_id

    chat_resp = api_client.post(
        "/api/chatbot",
        {"message": "Món phở nấu cần nguyên liệu gì?", "session_id": session_id},
        include_csrf=False,
        timeout=45.0,
    )
    assert chat_resp.status_code not in (401, 403), (
        f"Unexpected auth/CSRF rejection for guest chatbot: {chat_resp.status_code} {chat_resp.text}"
    )
    assert "csrf" not in chat_resp.json().get("error", "").lower()
