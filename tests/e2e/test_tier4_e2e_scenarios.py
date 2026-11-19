"""Tier 4 full real-world browser E2E scenarios covering R1–R5 and TC01–TC16."""

from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect
from werkzeug.security import check_password_hash

from helpers.browser_helper import (
    assert_element_within_viewport,
    assert_step3_toggle_switches_visibility,
    check_horizontal_overflow,
    extract_step3_temp_password,
    fill_otp_step2,
    find_step3_copy_button,
    get_change_password_inputs,
    get_computed_z_index,
    get_dropdown_change_password_item,
    get_step2_scope,
    get_step3_scope,
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


@pytest.mark.tier4
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t4_01_e2e_forgot_password_happy_path_and_temp_login(
    live_server: CookMateServerHarness, db: DbHelper, context: BrowserContext
) -> None:
    """T4-01 (TC01, TC02, TC08, TC09): Complete Forgot Password UI flow -> terminal OTP -> temp password -> login -> MySQL check."""
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=live_server.base_url)
    page = context.new_page()
    user = db.create_test_user(prefix="e2e_t4_01", password="InitialSecret1!")

    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    mark = live_server.output_mark()
    submit_forgot_password_email(page, user["email"])

    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)
    step2 = get_step2_scope(page)
    expect(step2).to_contain_text(re.compile(r"\b[0-5]:[0-5]\d\b"))

    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    assert otp not in page.content()

    fill_otp_step2(page, otp)
    submit_verify_otp_step2(page)

    expect(page.get_by_text("Khôi phục mật khẩu thành công!", exact=False).first).to_be_visible(timeout=10000)
    expect(
        page.get_by_text(
            "Vui lòng lưu mật khẩu này. Mật khẩu chỉ được hiển thị một lần. Sau khi đăng nhập, bạn nên đổi sang mật khẩu riêng của mình.",
            exact=False,
        ).first
    ).to_be_visible()

    temp_pw = extract_step3_temp_password(page)
    assert len(temp_pw) >= 16
    assert temp_pw not in live_server.text_since(mark)

    step3 = get_step3_scope(page)
    assert_step3_toggle_switches_visibility(step3, temp_pw)

    find_step3_copy_button(step3).click()
    assert page.evaluate("() => navigator.clipboard.readText()") == temp_pw

    storage_dump = page.evaluate(
        "() => JSON.stringify({ ls: Object.assign({}, localStorage), ss: Object.assign({}, sessionStorage) })"
    )
    assert temp_pw not in storage_dump

    page.reload(wait_until="domcontentloaded")
    wait_for_login_page_ready(page)
    assert temp_pw not in page.content()

    page.locator("#loginEmail").fill(user["email"])
    page.locator("#loginPassword").fill(temp_pw)
    page.locator("#loginSubmitBtn").click()
    page.wait_for_url(re.compile(r"(index\.html|/)$"), timeout=15000)
    wait_for_app_ready(page, authenticated=True)

    otp_row = db.get_latest_otp_for_user(user["user_id"])
    user_row = db.get_user_by_id(user["user_id"])
    assert otp_row is not None and otp not in otp_row["otp_hash"] and otp_row["used_at"] is not None
    assert user_row is not None and temp_pw not in user_row["password_hash"]
    assert check_password_hash(user_row["password_hash"], temp_pw)


@pytest.mark.tier4
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t4_02_e2e_forgot_password_wrong_expired_lockout_and_resend(
    server_factory, db: DbHelper, page: Page
) -> None:
    """T4-02 (TC03, TC04, TC05, TC06, TC07): Wrong OTP -> 5x lockout -> cooldown -> expired OTP -> resend -> verify -> reuse rejected."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "6",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    user = db.create_test_user(prefix="e2e_t4_02")

    page.goto(f"{srv.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    m1 = srv.output_mark()
    submit_forgot_password_email(page, user["email"])
    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)
    otp1 = srv.wait_for_otp(user["email"], since_mark=m1, timeout=5.0)
    wrong = "000000" if otp1 != "000000" else "999999"

    for _ in range(4):
        fill_otp_step2(page, wrong)
        with page.expect_response(lambda r: r.url.endswith("/api/auth/verify-otp"), timeout=10000) as resp_info:
            submit_verify_otp_step2(page)
        assert resp_info.value.status == 400
        expect(page.get_by_text(re.compile(r"không đúng", re.I)).first).to_be_visible(timeout=5000)

    fill_otp_step2(page, wrong)
    with page.expect_response(lambda r: r.url.endswith("/api/auth/verify-otp"), timeout=10000) as resp_info:
        submit_verify_otp_step2(page)
    assert resp_info.value.status == 429
    expect(page.get_by_text(re.compile(r"quá 5 lần|vô hiệu hóa", re.I)).first).to_be_visible(timeout=5000)

    # Rapid resend triggers cooldown error
    resend_btn = page.get_by_role("button", name="Gửi lại mã")
    resend_btn.click()
    expect(page.get_by_text(re.compile(r"quá nhanh|thử lại", re.I)).first).to_be_visible(timeout=5000)

    # Wait past cooldown -> resend -> expire OTP2 -> verify expired error
    time.sleep(6.2)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)
    m2 = srv.output_mark()
    resend_btn.click()
    otp2 = srv.wait_for_otp(user["email"], since_mark=m2, timeout=5.0)

    db.backdate_latest_otp_expiry(user["user_id"], minutes_ago=10)
    fill_otp_step2(page, otp2)
    submit_verify_otp_step2(page)
    expect(page.get_by_text(re.compile(r"hết hạn", re.I)).first).to_be_visible(timeout=5000)

    # Wait past cooldown -> resend OTP3 -> verify succeeds -> reusing OTP3 via API rejected
    time.sleep(6.2)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)
    m3 = srv.output_mark()
    resend_btn.click()
    otp3 = srv.wait_for_otp(user["email"], since_mark=m3, timeout=5.0)

    fill_otp_step2(page, otp3)
    submit_verify_otp_step2(page)
    expect(page.get_by_text("Khôi phục mật khẩu thành công!", exact=False).first).to_be_visible(timeout=10000)
    assert len(extract_step3_temp_password(page)) >= 16

    reuse = ApiClient(srv.base_url).verify_otp(user["email"], otp3)
    assert reuse.status_code == 400


@pytest.mark.tier4
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t4_03_e2e_change_password_dropdown_validation_and_relogin(
    live_server: CookMateServerHarness, db: DbHelper, browser: Browser
) -> None:
    """T4-03 (TC10–TC15): Avatar dropdown -> validation (<8, mismatch, wrong current) -> update -> multi-page -> relogin."""
    user = db.create_test_user(prefix="e2e_t4_03", password="OldPassword1!")
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        page = ctx.new_page()
        login_via_ui(page, live_server.base_url, user["email"], "OldPassword1!")

        base_h = measure_header_height(page)
        dropdown = open_avatar_dropdown(page)
        assert_element_within_viewport(page, dropdown, label="#userDropdown")
        cp_item = get_dropdown_change_password_item(dropdown)
        expect(cp_item).to_be_visible()
        expect(cp_item.locator("i.fa-lock, svg").first).to_be_visible()
        assert abs(measure_header_height(page) - base_h) < 1.0

        modal = open_change_password_modal(page)
        cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
        save_btn = modal.get_by_role("button", name="Cập nhật mật khẩu")

        # < 8 chars & mismatch & wrong current
        for cur_v, new_v, conf_v in (
            ("OldPassword1!", "short7", "short7"),
            ("OldPassword1!", "ValidNewPass2!", "OtherPass3!"),
            ("WrongCurrent9!", "ValidNewPass2!", "ValidNewPass2!"),
        ):
            cur_inp.fill(cur_v)
            new_inp.fill(new_v)
            conf_inp.fill(conf_v)
            save_btn.click()
            expect(modal).to_be_visible()

        # Valid change
        cur_inp.fill("OldPassword1!")
        new_inp.fill("ValidNewPass2!")
        conf_inp.fill("ValidNewPass2!")
        save_btn.click()
        expect(modal).to_be_hidden(timeout=10000)
        expect(page.locator(".toast:visible").first).to_be_visible(timeout=5000)

        # Session stays active on other pages
        for rel_path in ("/pages/recipes.html", "/pages/account/profile.html"):
            page.goto(f"{live_server.base_url}{rel_path}", wait_until="domcontentloaded")
            wait_for_app_ready(page, authenticated=True)

        # Logout via dropdown and verify guest state
        with page.expect_response(lambda r: r.url.endswith("/api/auth/logout"), timeout=10000):
            open_avatar_dropdown(page).locator(".user-menu__item--logout").click()
        page.wait_for_url(re.compile(r"(index\.html|/)$"), timeout=15000)
        wait_for_app_ready(page, authenticated=False)
    finally:
        ctx.close()

    ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        p2 = ctx2.new_page()
        p2.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
        wait_for_login_page_ready(p2)
        p2.locator("#loginEmail").fill(user["email"])
        p2.locator("#loginPassword").fill("OldPassword1!")
        p2.locator("#loginSubmitBtn").click()
        expect(p2.locator("#loginPasswordError")).to_be_visible(timeout=5000)

        p2.locator("#loginPassword").fill("ValidNewPass2!")
        p2.locator("#loginSubmitBtn").click()
        p2.wait_for_url(re.compile(r"(index\.html|/)$"), timeout=15000)
        wait_for_app_ready(p2, authenticated=True)
    finally:
        ctx2.close()

    row = db.get_user_by_id(user["user_id"])
    assert row is not None and check_password_hash(row["password_hash"], "ValidNewPass2!")


@pytest.mark.tier4
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t4_04_e2e_full_recovery_then_immediate_change_password(
    live_server: CookMateServerHarness, db: DbHelper, browser: Browser
) -> None:
    """T4-04 (TC01, TC02, TC09, TC10, TC11, TC15): Reset via OTP -> login with temp password -> change to personal -> relogin."""
    user = db.create_test_user(prefix="e2e_t4_04", password="ForgottenPass1!")
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        page = ctx.new_page()
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
        temp_pw = extract_step3_temp_password(page)
        assert len(temp_pw) >= 16

        page.get_by_role("button", name="Về trang đăng nhập").or_(
            page.get_by_role("link", name="Về trang đăng nhập")
        ).first.click()
        wait_for_login_page_ready(page)

        page.locator("#loginEmail").fill(user["email"])
        page.locator("#loginPassword").fill(temp_pw)
        p_btn = page.locator("#loginSubmitBtn")
        p_btn.click()
        page.wait_for_url(re.compile(r"(index\.html|/)$"), timeout=15000)
        wait_for_app_ready(page, authenticated=True)

        modal = open_change_password_modal(page)
        cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
        personal_pw = "FinalPersonalPw#9"
        cur_inp.fill(temp_pw)
        new_inp.fill(personal_pw)
        conf_inp.fill(personal_pw)
        modal.get_by_role("button", name="Cập nhật mật khẩu").click()
        expect(modal).to_be_hidden(timeout=10000)
        expect(page.locator(".toast:visible").first).to_be_visible(timeout=5000)
    finally:
        ctx.close()

    assert ApiClient(live_server.base_url).login(user["email"], temp_pw).status_code == 401
    assert ApiClient(live_server.base_url).login(user["email"], "FinalPersonalPw#9").status_code == 200


@pytest.mark.tier4
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t4_05_e2e_multi_context_cross_account_isolation(
    live_server: CookMateServerHarness, db: DbHelper, browser: Browser
) -> None:
    """T4-05 (TC10, TC16): Two logged-in BrowserContexts (User A & User B); User A cannot modify User B's password."""
    user_a = db.create_test_user(prefix="e2e_t4_05a", password="AccountAPass1!")
    user_b = db.create_test_user(prefix="e2e_t4_05b", password="AccountBPass1!")
    hash_b_before = db.get_user_by_id(user_b["user_id"])["password_hash"]

    ctx_a = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx_b = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        page_a = ctx_a.new_page()
        page_b = ctx_b.new_page()
        login_via_ui(page_a, live_server.base_url, user_a["email"], "AccountAPass1!")
        login_via_ui(page_b, live_server.base_url, user_b["email"], "AccountBPass1!")

        attack_status = page_a.evaluate(
            """async ([targetId, targetEmail]) => {
                const csrfRes = await fetch('/api/auth/csrf', { credentials: 'include' });
                const csrfData = await csrfRes.json();
                const res = await fetch('/api/auth/change-password', {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': csrfData.csrfToken || ''
                    },
                    body: JSON.stringify({
                        user_id: targetId,
                        email: targetEmail,
                        current_password: 'AccountBPass1!',
                        new_password: 'HackedPassword9!',
                        confirm_password: 'HackedPassword9!'
                    })
                });
                return res.status;
            }""",
            [user_b["user_id"], user_b["email"]],
        )
        assert attack_status == 400

        page_b.reload(wait_until="domcontentloaded")
        wait_for_app_ready(page_b, authenticated=True)
        assert db.get_user_by_id(user_b["user_id"])["password_hash"] == hash_b_before
        assert ApiClient(live_server.base_url).login(user_b["email"], "AccountBPass1!").status_code == 200
    finally:
        ctx_a.close()
        ctx_b.close()


@pytest.mark.tier4
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t4_06_e2e_responsive_desktop_and_mobile_layout_integrity(
    live_server: CookMateServerHarness, db: DbHelper, browser: Browser
) -> None:
    """T4-06 (TC10, R5): Responsive desktop (1280x800) & mobile (375x812) check: 0px overflow, header height, z-index & hit-test."""
    user = db.create_test_user(prefix="e2e_t4_06", password="LayoutPass1!")

    for width, height in ((1280, 800), (375, 812)):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        try:
            page = ctx.new_page()
            page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
            wait_for_login_page_ready(page)
            open_forgot_password_step1(page)
            sw_l, iw_l = check_horizontal_overflow(page)
            assert sw_l <= iw_l, f"Login forgot-step1 overflow at {width}x{height}: {sw_l} > {iw_l}"

            login_via_ui(page, live_server.base_url, user["email"], "LayoutPass1!")
            header_before = measure_header_height(page)
            dropdown = open_avatar_dropdown(page)
            assert_element_within_viewport(page, dropdown, label=f"#userDropdown@{width}x{height}")
            assert abs(measure_header_height(page) - header_before) < 1.0

            modal = open_change_password_modal(page)
            launcher = page.locator("#cmChefBotLauncher")
            expect(launcher).to_be_visible(timeout=10000)
            launcher_z = get_computed_z_index(launcher)
            modal_z = get_computed_z_index(modal)
            assert modal_z > launcher_z and modal_z > 9999

            save_btn = modal.get_by_role("button", name="Cập nhật mật khẩu")
            cancel_btn = modal.get_by_role("button", name="Hủy")
            assert hit_test_center(page, save_btn)["sameOrDescendant"] is True
            assert hit_test_center(page, cancel_btn)["sameOrDescendant"] is True
            cancel_btn.click()
            expect(modal).to_be_hidden(timeout=5000)

            sw_h, iw_h = check_horizontal_overflow(page)
            assert sw_h <= iw_h, f"Header/modal overflow at {width}x{height}: {sw_h} > {iw_h}"
        finally:
            ctx.close()
