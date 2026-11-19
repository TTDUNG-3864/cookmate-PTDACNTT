"""Tier 2 functional, negative, boundary, and concurrency tests for F4 (OTP request/resend), F5 (OTP verify), and F6 (change password)."""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from helpers.db_helper import DbHelper
from helpers.http_client import ApiClient
from helpers.server_harness import CookMateServerHarness


# ---------------------------------------------------------------------------
# F4: OTP Request & Resend Backend (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f4_forgot_password_email_case_and_whitespace_normalized(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F4-01 (TC01): Leading/trailing spaces and uppercase email normalize to registered user."""
    user = db.create_test_user(prefix="e2e_t2_f4_01")
    mixed = f"  {user['email'].upper()}  "

    mark = live_server.output_mark()
    resp = api_client.forgot_password(mixed)
    assert resp.status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    assert len(otp) == 6


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f4_inactive_or_locked_user_non_disclosing_no_otp(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F4-02 (TC01): Inactive user returns generic 200 without issuing or printing an OTP."""
    user = db.create_test_user(prefix="e2e_t2_f4_02", status="inactive")
    mark = live_server.output_mark()

    resp = api_client.forgot_password(user["email"])
    assert resp.status_code == 200
    assert resp.json().get("success") is True
    assert live_server.find_otp_banners(email=user["email"], since_mark=mark) == []
    assert db.get_otps_for_user(user["user_id"]) == []


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f4_resend_invalidates_previous_unused_otps(
    server_factory, db: DbHelper
) -> None:
    """T2-F4-03 (TC01, TC06): Resending OTP marks prior unused OTP row used_at and rejects old OTP."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "1",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_t2_f4_03")

    m1 = srv.output_mark()
    assert client.forgot_password(user["email"]).status_code == 200
    otp1 = srv.wait_for_otp(user["email"], since_mark=m1, timeout=5.0)

    time.sleep(1.1)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)

    m2 = srv.output_mark()
    assert client.resend_otp(user["email"]).status_code == 200
    otp2 = srv.wait_for_otp(user["email"], since_mark=m2, timeout=5.0)

    rows = db.get_otps_for_user(user["user_id"])
    assert len(rows) == 2
    assert rows[0]["used_at"] is not None
    assert rows[1]["used_at"] is None

    if otp1 != otp2:
        assert client.verify_otp(user["email"], otp1).status_code == 400
    assert client.verify_otp(user["email"], otp2).status_code == 200


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f4_rate_limit_applies_consistently_for_unknown_email(
    server_factory, db: DbHelper
) -> None:
    """T2-F4-04 (TC07): Rapid repeated requests for unknown email also return 429 (non-disclosing)."""
    srv = server_factory({"APP_ENV": "testing", "DEMO_MODE": "true", "OTP_IP_RATE_LIMIT_MAX": "500"})
    client = ApiClient(srv.base_url)
    unknown = f"unknown_ratelimit_{uuid.uuid4().hex[:8]}@cookmate.test"
    db.track_rate_limit_email(unknown)

    r1 = client.forgot_password(unknown)
    assert r1.status_code == 200

    saw_429 = False
    for _ in range(5):
        r = client.forgot_password(unknown)
        if r.status_code == 429:
            saw_429 = True
            break
    assert saw_429 is True


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f4_rate_limit_recovers_after_cooldown_window(
    server_factory, db: DbHelper
) -> None:
    """T2-F4-05 (TC07): After cooldown passes, resend-otp succeeds with 200."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "2",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_t2_f4_05")

    assert client.forgot_password(user["email"]).status_code == 200
    assert client.resend_otp(user["email"]).status_code == 429

    time.sleep(2.1)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)
    mark = srv.output_mark()
    r_ok = client.resend_otp(user["email"])
    assert r_ok.status_code == 200
    assert len(srv.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)) == 6


# ---------------------------------------------------------------------------
# F5: Atomic OTP Verification & Temp Password (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f5_verify_otp_invalidates_older_otps_and_updates_hash(
    server_factory, db: DbHelper
) -> None:
    """T2-F5-01 (TC02, TC08): Successful verify-otp marks all OTPs for user used and rotates password_hash."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "1",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_t2_f5_01")
    old_hash = db.get_user_by_id(user["user_id"])["password_hash"]

    assert client.forgot_password(user["email"]).status_code == 200
    time.sleep(1.1)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)
    m2 = srv.output_mark()
    assert client.resend_otp(user["email"]).status_code == 200
    otp2 = srv.wait_for_otp(user["email"], since_mark=m2, timeout=5.0)

    vresp = client.verify_otp(user["email"], otp2)
    assert vresp.status_code == 200
    rows = db.get_otps_for_user(user["user_id"])
    assert len(rows) == 2
    assert all(r["used_at"] is not None for r in rows)
    assert db.get_user_by_id(user["user_id"])["password_hash"] != old_hash


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f5_non_six_digit_otp_formats_rejected_400(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F5-02 (TC03): Non-6-digit OTP payloads ('', '12345', '1234567', 'abcdef') return 400."""
    user = db.create_test_user(prefix="e2e_t2_f5_02")
    api_client.ensure_csrf()
    for bad_otp in ("", "12345", "1234567", "abcdef", "12 345"):
        resp = api_client.verify_otp(user["email"], bad_otp)
        assert resp.status_code == 400, f"Expected 400 for otp={bad_otp!r}, got {resp.status_code}"
        assert resp.json().get("success") is False


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f5_expired_otp_past_5_minutes_rejected_400(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F5-03 (TC04): Backdating expires_at past 5 minutes in UTC causes verify-otp to reject 400."""
    user = db.create_test_user(prefix="e2e_t2_f5_03")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    assert db.backdate_latest_otp_expiry(user["user_id"], minutes_ago=10) == 1
    resp = api_client.verify_otp(user["email"], otp)
    assert resp.status_code == 400
    assert resp.json().get("success") is False
    assert "hết hạn" in resp.json().get("error", "").lower()


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f5_locked_otp_rejects_even_correct_code(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F5-04 (TC05): Once locked at 5 wrong attempts, even the true 6-digit OTP is rejected."""
    user = db.create_test_user(prefix="e2e_t2_f5_04")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    wrong = "555555" if otp != "555555" else "666666"

    for _ in range(4):
        assert api_client.verify_otp(user["email"], wrong).status_code == 400
    assert api_client.verify_otp(user["email"], wrong).status_code == 429

    after_lock = api_client.verify_otp(user["email"], otp)
    assert after_lock.status_code in (400, 429)
    assert after_lock.json().get("success") is False
    assert "temporary_password" not in after_lock.json()


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f5_concurrent_verify_otp_strictly_one_wins(
    server_factory, db: DbHelper
) -> None:
    """T2-F5-05 (TC06): 6 concurrent verify-otp requests yield strictly 1 success (200) and 5 rejections."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "MYSQL_POOL_SIZE": "10",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    user = db.create_test_user(prefix="e2e_t2_f5_05")
    setup_client = ApiClient(srv.base_url)
    mark = srv.output_mark()
    assert setup_client.forgot_password(user["email"]).status_code == 200
    otp = srv.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    clients = [ApiClient(srv.base_url) for _ in range(6)]
    for c in clients:
        c.ensure_csrf()

    def _attempt(c: ApiClient):
        return c.verify_otp(user["email"], otp)

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(_attempt, clients))

    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == 1, f"Expected strictly 1 winner (200), got statuses={statuses}"
    assert statuses.count(400) == 5, f"Expected 5 rejections (400), got statuses={statuses}"

    winner = next(r for r in responses if r.status_code == 200)
    temp_pw = winner.json()["temporary_password"]
    assert ApiClient(srv.base_url).login(user["email"], temp_pw).status_code == 200


# ---------------------------------------------------------------------------
# F6: Change Password Backend (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f6_change_password_keeps_session_active_and_relogin_works(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F6-01 (TC11, TC15): Current session stays active; new login requires new password."""
    user = db.create_test_user(prefix="e2e_t2_f6_01", password="OldPassword1!")
    assert api_client.login(user["email"], "OldPassword1!").status_code == 200

    resp = api_client.change_password("OldPassword1!", "NewPassword2!", "NewPassword2!")
    assert resp.status_code == 200

    me = api_client.me().json()
    assert me.get("authenticated") is True
    assert me.get("user", {}).get("email") == user["email"]

    fresh = ApiClient(live_server.base_url)
    assert fresh.login(user["email"], "OldPassword1!").status_code == 401
    assert fresh.login(user["email"], "NewPassword2!").status_code == 200


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f6_change_password_wrong_current_keeps_old_password_valid(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F6-02 (TC12): Wrong current password fails 400 and leaves original password working."""
    user = db.create_test_user(prefix="e2e_t2_f6_02", password="OldPassword1!")
    assert api_client.login(user["email"], "OldPassword1!").status_code == 200

    resp = api_client.change_password("Incorrect1!", "NewPassword2!", "NewPassword2!")
    assert resp.status_code == 400

    assert ApiClient(live_server.base_url).login(user["email"], "OldPassword1!").status_code == 200


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f6_change_password_same_as_current_rejected_400(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F6-03: Setting new_password identical to current_password is rejected with 400."""
    user = db.create_test_user(prefix="e2e_t2_f6_03", password="SamePassword1!")
    assert api_client.login(user["email"], "SamePassword1!").status_code == 200

    resp = api_client.change_password("SamePassword1!", "SamePassword1!", "SamePassword1!")
    assert resp.status_code == 400
    assert resp.json().get("success") is False


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f6_change_password_missing_or_whitespace_fields_rejected_400(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T2-F6-04 (TC13, TC14): Empty/missing fields in change-password payload return 400."""
    user = db.create_test_user(prefix="e2e_t2_f6_04", password="OldPassword1!")
    assert api_client.login(user["email"], "OldPassword1!").status_code == 200

    for payload in (
        {"current_password": "", "new_password": "NewPassword2!", "confirm_password": "NewPassword2!"},
        {"current_password": "OldPassword1!", "new_password": "", "confirm_password": ""},
        {"current_password": "OldPassword1!", "new_password": "NewPassword2!", "confirm_password": ""},
        {"current_password": "OldPassword1!", "new_password": "        ", "confirm_password": "        "},
    ):
        r = api_client.post("/api/auth/change-password", payload)
        assert r.status_code == 400, f"Expected 400 for {payload}, got {r.status_code}"


@pytest.mark.tier2
@pytest.mark.requires_m1
def test_t2_f6_change_password_ignores_forged_target_user_id_or_email(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T2-F6-05 (TC16): User B cannot alter User A's password by injecting user_id/email into payload."""
    user_a = db.create_test_user(prefix="e2e_t2_f6_05a", password="UserAPass1!")
    user_b = db.create_test_user(prefix="e2e_t2_f6_05b", password="UserBPass1!")
    hash_a_before = db.get_user_by_id(user_a["user_id"])["password_hash"]

    client_b = ApiClient(live_server.base_url)
    assert client_b.login(user_b["email"], "UserBPass1!").status_code == 200

    r_attack = client_b.change_password(
        "UserAPass1!",
        "HijackedPass9!",
        "HijackedPass9!",
        extra_payload={"user_id": user_a["user_id"], "userId": user_a["user_id"], "email": user_a["email"]},
    )
    assert r_attack.status_code == 400

    assert db.get_user_by_id(user_a["user_id"])["password_hash"] == hash_a_before
    assert ApiClient(live_server.base_url).login(user_a["email"], "UserAPass1!").status_code == 200
