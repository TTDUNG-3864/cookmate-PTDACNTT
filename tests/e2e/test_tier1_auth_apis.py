"""Tier 1 isolated tests for F4 (OTP request/resend), F5 (OTP verify/temp password), and F6 (change password API)."""

from __future__ import annotations

import time

import pytest

from helpers.db_helper import DbHelper
from helpers.http_client import ApiClient
from helpers.server_harness import CookMateServerHarness


# ---------------------------------------------------------------------------
# F4: OTP Request & Resend Backend (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f4_forgot_password_valid_email_returns_generic_200(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F4-01 (TC01): Registered email returns generic 200 without leaking OTP in JSON."""
    user = db.create_test_user(prefix="e2e_f4_01")
    mark = live_server.output_mark()

    resp = api_client.forgot_password(user["email"])
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    assert "otp" not in body
    assert "temporary_password" not in body
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    assert otp not in resp.text


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f4_forgot_password_unknown_email_non_disclosing(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F4-02 (TC01): Unregistered email returns identical 200 payload and emits no OTP banner."""
    reg_user = db.create_test_user(prefix="e2e_f4_02")
    reg_resp = api_client.forgot_password(reg_user["email"])
    assert reg_resp.status_code == 200

    unknown_email = "nonexistent_e2e_99999@cookmate.test"
    mark = live_server.output_mark()
    unk_resp = ApiClient(live_server.base_url).forgot_password(unknown_email)
    assert unk_resp.status_code == 200
    assert unk_resp.json().get("success") is True
    assert unk_resp.json().get("message") == reg_resp.json().get("message")
    assert live_server.find_otp_banners(email=unknown_email, since_mark=mark) == []


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f4_forgot_password_invalid_email_returns_400(
    live_server: CookMateServerHarness, api_client: ApiClient
) -> None:
    """T1-F4-03: Malformed or empty email returns 400 validation error."""
    for bad in ("", "not-an-email", "missing@domain", "@cookmate.test"):
        resp = api_client.forgot_password(bad)
        assert resp.status_code == 400, f"Expected 400 for email={bad!r}, got {resp.status_code}"
        assert resp.json().get("success") is False


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f4_resend_otp_valid_email_after_cooldown_200(
    server_factory, db: DbHelper
) -> None:
    """T1-F4-04 (TC01): POST /api/auth/resend-otp after cooldown returns 200 and prints new OTP."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "1",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_f4_04")

    mark1 = srv.output_mark()
    assert client.forgot_password(user["email"]).status_code == 200
    srv.wait_for_otp(user["email"], since_mark=mark1, timeout=5.0)

    time.sleep(1.1)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)

    mark2 = srv.output_mark()
    resend_resp = client.resend_otp(user["email"])
    assert resend_resp.status_code == 200
    assert resend_resp.json().get("success") is True
    otp2 = srv.wait_for_otp(user["email"], since_mark=mark2, timeout=5.0)
    assert len(otp2) == 6 and otp2.isdigit()


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f4_rapid_forgot_password_triggers_429(
    server_factory, db: DbHelper
) -> None:
    """T1-F4-05 (TC07): Rapid repeated forgot-password request returns 429 rate-limit error."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_f4_05")

    r1 = client.forgot_password(user["email"])
    assert r1.status_code == 200

    r2 = client.forgot_password(user["email"])
    assert r2.status_code == 429
    assert r2.json().get("success") is False


# ---------------------------------------------------------------------------
# F5: Atomic OTP Verification & Temp Password (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f5_verify_otp_success_returns_temp_password_once(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F5-01 (TC02, TC09): Valid OTP returns temporary_password >= 16 chars that logs in."""
    user = db.create_test_user(prefix="e2e_f5_01", password="InitialPassword1!")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    vresp = api_client.verify_otp(user["email"], otp)
    assert vresp.status_code == 200
    vjson = vresp.json()
    assert vjson.get("success") is True
    temp_pw = vjson.get("temporary_password", "")
    assert len(temp_pw) >= 16

    login_client = ApiClient(live_server.base_url)
    lresp = login_client.login(user["email"], temp_pw)
    assert lresp.status_code == 200
    assert lresp.json().get("success") is True
    assert login_client.login(user["email"], "InitialPassword1!").status_code == 401


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f5_temp_password_never_logged_to_stdout(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F5-02 (TC02): Temporary password is never printed to Flask stdout or stderr."""
    user = db.create_test_user(prefix="e2e_f5_02")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    mark_verify = live_server.output_mark()
    vresp = api_client.verify_otp(user["email"], otp)
    assert vresp.status_code == 200
    temp_pw = vresp.json()["temporary_password"]

    time.sleep(0.15)
    output = live_server.text_since(mark_verify)
    assert temp_pw not in output


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f5_wrong_otp_returns_400_and_increments_attempts(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F5-03 (TC03): Wrong OTP returns 400 and increments attempts from 0 to 1 in MySQL."""
    user = db.create_test_user(prefix="e2e_f5_03")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    before = db.get_latest_otp_for_user(user["user_id"])
    assert before is not None and int(before["attempts"]) == 0

    wrong = "111111" if otp != "111111" else "222222"
    vresp = api_client.verify_otp(user["email"], wrong)
    assert vresp.status_code == 400
    assert vresp.json().get("success") is False

    after = db.get_latest_otp_for_user(user["user_id"])
    assert after is not None and int(after["attempts"]) == 1


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f5_five_wrong_attempts_locks_otp_429(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F5-04 (TC05): 5th wrong OTP returns 429 and sets used_at non-null in MySQL."""
    user = db.create_test_user(prefix="e2e_f5_04")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    wrong = "333333" if otp != "333333" else "444444"

    for _ in range(4):
        assert api_client.verify_otp(user["email"], wrong).status_code == 400
    r5 = api_client.verify_otp(user["email"], wrong)
    assert r5.status_code == 429

    row = db.get_latest_otp_for_user(user["user_id"])
    assert row is not None
    assert int(row["attempts"]) >= 5
    assert row["used_at"] is not None


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f5_reuse_verified_otp_rejected_400(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F5-05 (TC06): Reusing an already-verified OTP is rejected with 400."""
    user = db.create_test_user(prefix="e2e_f5_05")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    r1 = api_client.verify_otp(user["email"], otp)
    assert r1.status_code == 200
    assert r1.json().get("temporary_password")

    r2 = api_client.verify_otp(user["email"], otp)
    assert r2.status_code == 400
    assert r2.json().get("success") is False
    assert "temporary_password" not in r2.json()


# ---------------------------------------------------------------------------
# F6: Change Password Backend (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f6_change_password_success_200(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F6-01 (TC11): Authenticated user with valid current/new/confirm updates password_hash."""
    user = db.create_test_user(prefix="e2e_f6_01", password="CurrentPass1!")
    old_hash = db.get_user_by_id(user["user_id"])["password_hash"]

    assert api_client.login(user["email"], "CurrentPass1!").status_code == 200
    resp = api_client.change_password("CurrentPass1!", "NewStrongPass2!", "NewStrongPass2!")
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    new_hash = db.get_user_by_id(user["user_id"])["password_hash"]
    assert new_hash != old_hash
    assert new_hash != "NewStrongPass2!"


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f6_change_password_requires_authentication_401(
    live_server: CookMateServerHarness, api_client: ApiClient
) -> None:
    """T1-F6-02 (TC16): Unauthenticated POST /api/auth/change-password returns 401."""
    resp = api_client.change_password("Anything1!", "NewStrongPass2!", "NewStrongPass2!")
    assert resp.status_code == 401
    assert resp.json().get("success") is False


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f6_change_password_wrong_current_rejected_400(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F6-03 (TC12): Wrong current_password returns 400 and leaves password_hash unchanged."""
    user = db.create_test_user(prefix="e2e_f6_03", password="CurrentPass1!")
    old_hash = db.get_user_by_id(user["user_id"])["password_hash"]

    assert api_client.login(user["email"], "CurrentPass1!").status_code == 200
    resp = api_client.change_password("WrongCurrent9!", "NewStrongPass2!", "NewStrongPass2!")
    assert resp.status_code == 400
    assert resp.json().get("success") is False
    assert db.get_user_by_id(user["user_id"])["password_hash"] == old_hash


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f6_change_password_short_new_rejected_400(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F6-04 (TC14): new_password shorter than 8 characters is rejected with 400."""
    user = db.create_test_user(prefix="e2e_f6_04", password="CurrentPass1!")
    assert api_client.login(user["email"], "CurrentPass1!").status_code == 200

    resp = api_client.change_password("CurrentPass1!", "short7!", "short7!")
    assert resp.status_code == 400
    assert resp.json().get("success") is False


@pytest.mark.tier1
@pytest.mark.requires_m1
def test_t1_f6_change_password_mismatch_confirm_rejected_400(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T1-F6-05 (TC13): Mismatched new_password and confirm_password returns 400."""
    user = db.create_test_user(prefix="e2e_f6_05", password="CurrentPass1!")
    assert api_client.login(user["email"], "CurrentPass1!").status_code == 200

    resp = api_client.change_password("CurrentPass1!", "NewStrongPass2!", "DifferentPass3!")
    assert resp.status_code == 400
    assert resp.json().get("success") is False
