"""Tier 3 cross-feature pair and multi-page / responsive integration tests (14 tests)."""

from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Page, expect

from helpers.browser_helper import (
    assert_element_within_viewport,
    check_horizontal_overflow,
    extract_step3_temp_password,
    fill_otp_step2,
    get_active_change_password_modal,
    get_change_password_inputs,
    get_computed_z_index,
    get_dropdown_change_password_item,
    hit_test_center,
    login_via_ui,
    measure_header_height,
    open_avatar_dropdown,
    open_change_password_modal,
    open_forgot_password_step1,
    submit_forgot_password_email,
    submit_verify_otp_step2,
    wait_for_app_ready,
    wait_for_login_page_ready,
)
from helpers.db_helper import DbHelper
from helpers.http_client import ApiClient
from helpers.server_harness import CookMateServerHarness


@pytest.mark.tier3
@pytest.mark.requires_m1
def test_t3_01_demo_mode_toggle_preserves_http_contract(
    server_factory, db: DbHelper
) -> None:
    """T3-01 (F1 x F4, TC01): DEMO_MODE=true and DEMO_MODE=false produce identical HTTP 200 JSON while toggling stdout."""
    u1 = db.create_test_user(prefix="e2e_t3_01a")
    u2 = db.create_test_user(prefix="e2e_t3_01b")

    srv_demo = server_factory({"APP_ENV": "testing", "DEMO_MODE": "true", "OTP_IP_RATE_LIMIT_MAX": "500"})
    m1 = srv_demo.output_mark()
    r1 = ApiClient(srv_demo.base_url).forgot_password(u1["email"])
    assert r1.status_code == 200
    assert len(srv_demo.wait_for_otp(u1["email"], since_mark=m1, timeout=5.0)) == 6

    srv_nodemo = server_factory({"APP_ENV": "testing", "DEMO_MODE": "false", "OTP_IP_RATE_LIMIT_MAX": "500"})
    m2 = srv_nodemo.output_mark()
    r2 = ApiClient(srv_nodemo.base_url).forgot_password(u2["email"])
    assert r2.status_code == 200
    assert r2.json() == r1.json()
    assert srv_nodemo.find_otp_banners(email=u2["email"], since_mark=m2) == []


@pytest.mark.tier3
@pytest.mark.requires_m1
def test_t3_02_otp_request_resend_mysql_lifecycle(
    server_factory, db: DbHelper
) -> None:
    """T3-02 (F2 x F4, TC01, TC08): Request -> MySQL row 1 -> Resend -> row 1 invalidated, row 2 active with +300s UTC TTL."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "1",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_t3_02")

    assert client.forgot_password(user["email"]).status_code == 200
    rows1 = db.get_otps_for_user(user["user_id"])
    assert len(rows1) == 1
    assert rows1[0]["used_at"] is None
    assert 298 <= int(rows1[0]["ttl_seconds"]) <= 302

    time.sleep(1.1)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)
    assert client.resend_otp(user["email"]).status_code == 200
    rows2 = db.get_otps_for_user(user["user_id"])
    assert len(rows2) == 2
    assert rows2[0]["used_at"] is not None
    assert rows2[1]["used_at"] is None
    assert 298 <= int(rows2[1]["ttl_seconds"]) <= 302


@pytest.mark.tier3
@pytest.mark.requires_m1
def test_t3_03_csrf_enforcement_across_r1_and_chatbot_regression(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T3-03 (F3 x F4): Cross-session CSRF fails 403 on R1 endpoints while valid CSRF passes and guest chatbot stays open."""
    user = db.create_test_user(prefix="e2e_t3_03")
    c_a = ApiClient(live_server.base_url)
    c_b = ApiClient(live_server.base_url)
    tok_a = c_a.ensure_csrf()
    c_b.ensure_csrf()

    assert c_b.forgot_password(user["email"], csrf_override=tok_a).status_code == 403
    assert c_b.resend_otp(user["email"], csrf_override=tok_a).status_code == 403
    assert c_a.forgot_password(user["email"]).status_code == 200

    guest = ApiClient(live_server.base_url)
    chat_sess = guest.post("/api/chatbot/sessions", {}, include_csrf=False)
    assert chat_sess.status_code == 201
    chat = guest.post(
        "/api/chatbot",
        {"message": "Gợi ý món canh chua", "session_id": chat_sess.json()["session_id"]},
        include_csrf=False,
        timeout=45.0,
    )
    assert chat.status_code not in (401, 403), (
        f"Unexpected auth/CSRF rejection for guest chatbot: {chat.status_code} {chat.text}"
    )


@pytest.mark.tier3
@pytest.mark.requires_m1
def test_t3_04_bad_csrf_on_verify_does_not_mutate_otp_attempts(
    live_server: CookMateServerHarness, db: DbHelper, api_client: ApiClient
) -> None:
    """T3-04 (F3 x F5, TC03): verify-otp with valid OTP but bad CSRF returns 403 and does not touch attempts/used_at."""
    user = db.create_test_user(prefix="e2e_t3_04")
    mark = live_server.output_mark()
    assert api_client.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    bad = api_client.verify_otp(user["email"], otp, csrf_override="wrong-csrf-token")
    assert bad.status_code == 403

    row = db.get_latest_otp_for_user(user["user_id"])
    assert row is not None
    assert int(row["attempts"]) == 0
    assert row["used_at"] is None


@pytest.mark.tier3
@pytest.mark.requires_m1
def test_t3_05_wrong_attempts_then_resend_then_verify_new_otp(
    server_factory, db: DbHelper
) -> None:
    """T3-05 (F4 x F5, TC02, TC03): 2 wrong attempts on OTP1 -> resend issues OTP2 -> OTP1 rejected -> OTP2 succeeds."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "1",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    client = ApiClient(srv.base_url)
    user = db.create_test_user(prefix="e2e_t3_05")

    m1 = srv.output_mark()
    assert client.forgot_password(user["email"]).status_code == 200
    otp1 = srv.wait_for_otp(user["email"], since_mark=m1, timeout=5.0)
    wrong = "000000" if otp1 != "000000" else "999999"

    assert client.verify_otp(user["email"], wrong).status_code == 400
    assert client.verify_otp(user["email"], wrong).status_code == 400

    time.sleep(1.1)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)
    m2 = srv.output_mark()
    assert client.resend_otp(user["email"]).status_code == 200
    otp2 = srv.wait_for_otp(user["email"], since_mark=m2, timeout=5.0)

    if otp1 != otp2:
        assert client.verify_otp(user["email"], otp1).status_code == 400
    ok = client.verify_otp(user["email"], otp2)
    assert ok.status_code == 200
    assert len(ok.json()["temporary_password"]) >= 16


@pytest.mark.tier3
@pytest.mark.requires_m1
def test_t3_06_atomic_verify_isolates_other_users_otps_and_updates_scrypt(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T3-06 (F5 x F2, TC06, TC08): Verifying User A's OTP updates only User A and leaves User B's active OTP intact."""
    user_a = db.create_test_user(prefix="e2e_t3_06a")
    user_b = db.create_test_user(prefix="e2e_t3_06b")
    c_a = ApiClient(live_server.base_url)
    c_b = ApiClient(live_server.base_url)

    m_a = live_server.output_mark()
    assert c_a.forgot_password(user_a["email"]).status_code == 200
    otp_a = live_server.wait_for_otp(user_a["email"], since_mark=m_a, timeout=5.0)

    m_b = live_server.output_mark()
    assert c_b.forgot_password(user_b["email"]).status_code == 200
    otp_b = live_server.wait_for_otp(user_b["email"], since_mark=m_b, timeout=5.0)

    assert c_a.verify_otp(user_a["email"], otp_a).status_code == 200
    row_b = db.get_latest_otp_for_user(user_b["user_id"])
    assert row_b is not None and row_b["used_at"] is None
    assert c_b.verify_otp(user_b["email"], otp_b).status_code == 200


@pytest.mark.tier3
@pytest.mark.requires_m1
def test_t3_07_temp_password_login_then_change_password_then_relogin(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T3-07 (F5 x F6, TC09, TC11, TC15): Temp password logs in, change-password replaces it, old temp fails, personal logs in."""
    user = db.create_test_user(prefix="e2e_t3_07")
    c = ApiClient(live_server.base_url)
    mark = live_server.output_mark()
    assert c.forgot_password(user["email"]).status_code == 200
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    temp_pw = c.verify_otp(user["email"], otp).json()["temporary_password"]
    assert c.login(user["email"], temp_pw).status_code == 200

    personal_pw = "MyPersonalPw#2026"
    assert c.change_password(temp_pw, personal_pw, personal_pw).status_code == 200
    assert c.logout().status_code == 200

    fresh = ApiClient(live_server.base_url)
    assert fresh.login(user["email"], temp_pw).status_code == 401
    assert fresh.login(user["email"], personal_pw).status_code == 200


@pytest.mark.tier3
@pytest.mark.requires_m1
def test_t3_08_change_password_csrf_plus_cross_account_isolation(
    live_server: CookMateServerHarness, db: DbHelper
) -> None:
    """T3-08 (F6 x F3, TC16): User B with valid Session B CSRF and forged User A fields cannot modify User A."""
    user_a = db.create_test_user(prefix="e2e_t3_08a", password="AlphaPass1!")
    user_b = db.create_test_user(prefix="e2e_t3_08b", password="BetaPass1!")
    hash_a = db.get_user_by_id(user_a["user_id"])["password_hash"]

    c_b = ApiClient(live_server.base_url)
    assert c_b.login(user_b["email"], "BetaPass1!").status_code == 200
    resp = c_b.change_password(
        "BetaPass1!",
        "BetaNewPass2!",
        "BetaNewPass2!",
        extra_payload={"user_id": user_a["user_id"], "email": user_a["email"]},
    )
    assert resp.status_code == 200
    assert db.get_user_by_id(user_a["user_id"])["password_hash"] == hash_a
    assert ApiClient(live_server.base_url).login(user_a["email"], "AlphaPass1!").status_code == 200
    assert ApiClient(live_server.base_url).login(user_b["email"], "BetaNewPass2!").status_code == 200


@pytest.mark.tier3
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t3_09_cookmate_ui_toast_layering_during_forgot_password_flow(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T3-09 (F7 x F9): Toasts during forgot-password flow render visibly above modals without clipping."""
    user = db.create_test_user(prefix="e2e_t3_09")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    mark = live_server.output_mark()
    submit_forgot_password_email(page, user["email"])
    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    wrong = "000000" if otp != "000000" else "999999"

    fill_otp_step2(page, wrong)
    submit_verify_otp_step2(page)
    expect(page.get_by_text(re.compile(r"không đúng", re.I)).first).to_be_visible(timeout=5000)

    visible_toast = page.locator(".toast:visible").first
    expect(visible_toast).to_be_visible(timeout=5000)
    assert_element_within_viewport(page, visible_toast, label="ForgotToast")
    toast_container = page.locator(".toast-container").filter(has=page.locator(".toast:visible")).last
    expect(toast_container).to_be_visible(timeout=5000)
    assert get_computed_z_index(toast_container) > 9999


@pytest.mark.tier3
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t3_10_storage_wrappers_drive_forgot_password_3_step_ui(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T3-10 (F8 x F9, TC01, TC02): UI 3-step forgot password sends real X-CSRF-Token XHRs via CookMateStorage."""
    user = db.create_test_user(prefix="e2e_t3_10")
    api_calls: list[tuple[str, int, str]] = []

    def _on_response(resp) -> None:
        if "/api/auth/" in resp.url:
            csrf_hdr = resp.request.headers.get("x-csrf-token", "")
            api_calls.append((resp.url, resp.status, csrf_hdr))

    page.on("response", _on_response)
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    mark = live_server.output_mark()
    submit_forgot_password_email(page, user["email"])
    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    fill_otp_step2(page, otp)
    submit_verify_otp_step2(page)
    expect(page.get_by_text("Khôi phục mật khẩu thành công!", exact=False).first).to_be_visible(timeout=10000)
    assert len(extract_step3_temp_password(page)) >= 16

    forgot_calls = [c for c in api_calls if c[0].endswith("/api/auth/forgot-password")]
    verify_calls = [c for c in api_calls if c[0].endswith("/api/auth/verify-otp")]
    assert forgot_calls and forgot_calls[-1][1] == 200 and len(forgot_calls[-1][2]) >= 16
    assert verify_calls and verify_calls[-1][1] == 200 and len(verify_calls[-1][2]) >= 16


@pytest.mark.tier3
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t3_11_cookmate_ui_modal_from_avatar_dropdown_above_chefbot(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T3-11 (F7 x F10, TC10): Change Password modal sits above #cmChefBotLauncher and buttons pass elementFromPoint at 375x812."""
    user = db.create_test_user(prefix="e2e_t3_11", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    page.set_viewport_size({"width": 375, "height": 812})
    launcher = page.locator("#cmChefBotLauncher")
    expect(launcher).to_be_visible(timeout=10000)
    launcher_z = get_computed_z_index(launcher)

    modal = open_change_password_modal(page)
    modal_z = get_computed_z_index(modal)
    assert modal_z > launcher_z and modal_z > 9999

    submit_btn = modal.get_by_role("button", name="Cập nhật mật khẩu")
    cancel_btn = modal.get_by_role("button", name="Hủy")
    assert hit_test_center(page, submit_btn)["sameOrDescendant"] is True
    assert hit_test_center(page, cancel_btn)["sameOrDescendant"] is True
    cancel_btn.click()
    expect(modal).to_be_hidden(timeout=5000)


@pytest.mark.tier3
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t3_12_storage_change_password_from_header_modal_preserves_session(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T3-12 (F8 x F10, TC11): Submitting Change Password modal triggers API update, shows toast, and keeps user logged in."""
    user = db.create_test_user(prefix="e2e_t3_12", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    modal = open_change_password_modal(page)
    cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
    cur_inp.fill("UserPass1!")
    new_inp.fill("UpdatedPass9!")
    conf_inp.fill("UpdatedPass9!")
    modal.get_by_role("button", name="Cập nhật mật khẩu").click()

    expect(modal).to_be_hidden(timeout=10000)
    expect(page.locator(".toast:visible").first).to_be_visible(timeout=5000)
    expect(page.locator("#userMenuTrigger")).to_be_visible()
    assert ApiClient(live_server.base_url).login(user["email"], "UpdatedPass9!").status_code == 200


@pytest.mark.tier3
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t3_13_multipage_navigation_dropdown_and_change_password_modal(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T3-13 (Multi-page F10): #userDropdown, lock icon, Change Password modal & .toast:visible work across index, recipes, and profile."""
    user = db.create_test_user(prefix="e2e_t3_13", password="MultiPage1!")
    login_via_ui(page, live_server.base_url, user["email"], "MultiPage1!")

    for rel_path in ("/index.html", "/pages/recipes.html", "/pages/account/profile.html"):
        page.goto(f"{live_server.base_url}{rel_path}", wait_until="domcontentloaded")
        wait_for_app_ready(page, authenticated=True)
        dropdown = open_avatar_dropdown(page)
        item = get_dropdown_change_password_item(dropdown)
        expect(item).to_be_visible()
        expect(item.locator("i.fa-lock, svg").first).to_be_visible()

        modal = open_change_password_modal(page)
        expect(modal).to_contain_text("Đổi mật khẩu")
        if rel_path.endswith("profile.html"):
            cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
            cur_inp.fill("MultiPage1!")
            new_inp.fill("MultiPageNew2!")
            conf_inp.fill("MultiPageNew2!")
            modal.get_by_role("button", name="Cập nhật mật khẩu").click()
            expect(modal).to_be_hidden(timeout=10000)
            expect(page.locator(".toast:visible").first).to_be_visible(timeout=5000)
        else:
            modal.get_by_role("button", name="Hủy").click()
            expect(modal).to_be_hidden(timeout=5000)

    assert ApiClient(live_server.base_url).login(user["email"], "MultiPageNew2!").status_code == 200


@pytest.mark.tier3
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t3_14_mobile_drawer_and_desktop_header_viewport_transitions(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T3-14 (Responsive F10 x F7): Transitioning 375x812 mobile drawer -> 1280x800 desktop header keeps dropdown/modal usable."""
    user = db.create_test_user(prefix="e2e_t3_14", password="ViewportPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "ViewportPass1!")

    page.set_viewport_size({"width": 375, "height": 812})
    mobile_h = measure_header_height(page)
    page.locator("#menuToggle").click()
    mobile_nav = page.locator("#mobileNav")
    expect(mobile_nav).to_be_visible(timeout=5000)
    mobile_cp = page.locator("#mobileAuthArea").get_by_role("button", name="Đổi mật khẩu").or_(
        page.locator("#mobileAuthArea").get_by_role("link", name="Đổi mật khẩu")
    ).first
    expect(mobile_cp).to_be_visible()
    mobile_cp.click()
    expect(
        page.locator(
            '.modal.active:visible, .modal.modal-show:visible, #cookmate-modal:visible, [role="dialog"]:visible'
        )
        .filter(has_text="Đổi mật khẩu")
        .first
    ).to_be_visible(timeout=5000)
    modal = get_active_change_password_modal(page)
    expect(modal).to_be_visible(timeout=5000)
    modal.get_by_role("button", name="Hủy").click()
    expect(modal).to_be_hidden(timeout=5000)

    sw_m, iw_m = check_horizontal_overflow(page)
    assert sw_m <= iw_m

    page.set_viewport_size({"width": 1280, "height": 800})
    desktop_h = measure_header_height(page)
    assert 70.0 <= desktop_h <= 75.0
    assert 68.0 <= mobile_h <= 76.0
    dropdown = open_avatar_dropdown(page)
    assert_element_within_viewport(page, dropdown, label="#userDropdown@1280x800")
    sw_d, iw_d = check_horizontal_overflow(page)
    assert sw_d <= iw_d
