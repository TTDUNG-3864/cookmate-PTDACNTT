"""Tier 2 functional, negative, edge, and responsive UI tests for F7–F10."""

from __future__ import annotations

import json
import re
import time

import pytest
from playwright.sync_api import BrowserContext, Page, expect

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
    get_step1_scope,
    get_step2_scope,
    get_step3_scope,
    get_toggle_button_for_input,
    login_via_ui,
    open_avatar_dropdown,
    open_change_password_modal,
    open_forgot_password_step1,
    submit_forgot_password_email,
    submit_verify_otp_step2,
    wait_for_app_ready,
    wait_for_login_page_ready,
)
from helpers.db_helper import DbHelper
from helpers.server_harness import CookMateServerHarness


# ---------------------------------------------------------------------------
# F7: Shared Modal & Toast Alignment (CookMateUI) (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f7_modal_closes_on_backdrop_click_and_escape(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T2-F7-01: Modal closes cleanly via backdrop click and Escape key."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    page.evaluate("() => CookMateUI.showModal({ title: 'BackdropTest', content: '<p>Body</p>' })")
    modal = page.locator("#cookmate-modal")
    expect(modal).to_be_visible(timeout=5000)
    modal.locator(".modal__backdrop, .modal-backdrop").first.click(position={"x": 5, "y": 5})
    expect(modal).to_have_count(0, timeout=5000)

    page.evaluate("() => CookMateUI.showModal({ title: 'EscapeTest', content: '<p>Body</p>' })")
    expect(modal).to_be_visible(timeout=5000)
    page.keyboard.press("Escape")
    expect(modal).to_have_count(0, timeout=5000)


@pytest.mark.tier2
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f7_consecutive_modals_replace_cleanly_without_orphan(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T2-F7-02: Opening a second CookMateUI.showModal replaces the previous modal without DOM duplicates."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    page.evaluate("() => CookMateUI.showModal({ title: 'Modal One', content: '<p>First</p>' })")
    page.evaluate("() => CookMateUI.showModal({ title: 'Modal Two', content: '<p>Second</p>' })")

    modals = page.locator("#cookmate-modal")
    expect(modals).to_have_count(1)
    expect(modals.first).to_contain_text("Modal Two")
    expect(modals.first).not_to_contain_text("Modal One")


@pytest.mark.tier2
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f7_toast_xss_escaping_and_manual_close(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T2-F7-03: CookMateUI.showToast HTML-escapes XSS payloads and removes toast on close button click."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    page.evaluate(
        "() => { window.__xssTriggered = false; CookMateUI.showToast('<img src=x onerror=\"window.__xssTriggered=true\">SafeText', 'warning', 10000); }"
    )
    toast = page.locator(".toast:visible").filter(has_text="SafeText").first
    expect(toast).to_be_visible(timeout=5000)
    assert page.evaluate("() => window.__xssTriggered") is False
    expect(toast).to_contain_text("<img")

    toast.locator("button").first.click()
    expect(toast).to_have_count(0, timeout=5000)


@pytest.mark.tier2
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f7_toast_renders_above_active_modal(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T2-F7-04: Toast container z-index is >= modal z-index so toasts remain visible over open modals."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    page.evaluate("() => { CookMateUI.showModal({ title: 'Layered', content: '<p>Modal</p>' }); CookMateUI.showToast('Top Toast', 'error', 8000); }")
    modal = page.locator(".modal.active:visible, .modal.modal-show:visible, #cookmate-modal:visible").first
    toast = page.locator(".toast:visible").filter(has_text="Top Toast").first
    expect(modal).to_be_visible(timeout=5000)
    expect(toast).to_be_visible(timeout=5000)

    modal_z = get_computed_z_index(modal)
    toast_container = page.locator(".toast-container").filter(has=page.locator(".toast:visible")).last
    expect(toast_container).to_be_visible(timeout=5000)
    toast_container_z = get_computed_z_index(toast_container)
    assert toast_container_z >= modal_z, (
        f"Expected .toast-container z-index ({toast_container_z}) >= modal z-index ({modal_z})"
    )


@pytest.mark.tier2
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f7_modal_scrolls_internally_on_short_viewport(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T2-F7-05: On a compact 375x600 viewport, tall modal content stays within viewport without horizontal overflow."""
    page.set_viewport_size({"width": 375, "height": 600})
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    tall_html = "".join(f"<p>Dòng nội dung dài số {i}</p>" for i in range(40))
    page.evaluate("html => CookMateUI.showModal({ title: 'TallModal', content: html })", tall_html)
    content = page.locator("#cookmate-modal .modal__content, #cookmate-modal .modal-dialog").first
    expect(content).to_be_visible(timeout=5000)

    box = content.bounding_box()
    assert box is not None
    assert box["height"] <= 600.5
    sw, iw = check_horizontal_overflow(page)
    assert sw <= iw


# ---------------------------------------------------------------------------
# F8: Client Storage API Wrappers (CookMateStorage) (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f8_storage_request_otp_propagates_400_and_429_errors(
    server_factory, db: DbHelper, page: Page
) -> None:
    """T2-F8-01 (TC07): CookMateStorage.requestPasswordResetOtp rejects with server messages on 400 and 429."""
    srv = server_factory({"APP_ENV": "testing", "DEMO_MODE": "true", "OTP_IP_RATE_LIMIT_MAX": "500"})
    user = db.create_test_user(prefix="e2e_t2_f8_01")
    page.goto(f"{srv.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    bad_err = page.evaluate(
        "() => CookMateStorage.requestPasswordResetOtp('invalid-email').then(() => null).catch(e => e.message)"
    )
    assert bad_err and "email" in bad_err.lower()

    assert page.evaluate("e => CookMateStorage.requestPasswordResetOtp(e)", user["email"]).get("success") is True
    rate_err = page.evaluate(
        "e => CookMateStorage.requestPasswordResetOtp(e).then(() => null).catch(e => e.message)",
        user["email"],
    )
    assert rate_err and ("quá nhanh" in rate_err.lower() or "thử lại" in rate_err.lower())


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f8_storage_verify_otp_rejects_wrong_otp_error(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F8-02 (TC03): CookMateStorage.verifyPasswordResetOtp rejects with error message on wrong OTP."""
    user = db.create_test_user(prefix="e2e_t2_f8_02")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    mark = live_server.output_mark()
    assert page.evaluate("e => CookMateStorage.requestPasswordResetOtp(e)", user["email"]).get("success") is True
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    wrong = "000000" if otp != "000000" else "999999"

    err_msg = page.evaluate(
        "([e, o]) => CookMateStorage.verifyPasswordResetOtp(e, o).then(() => null).catch(err => err.message)",
        [user["email"], wrong],
    )
    assert err_msg and "không đúng" in err_msg.lower()


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f8_storage_change_password_rejects_unauthenticated(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T2-F8-03 (TC16): CookMateStorage.changePassword rejects cleanly when user is logged out."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page, authenticated=False)

    err_msg = page.evaluate(
        "() => CookMateStorage.changePassword('OldPass1!', 'NewPass2!', 'NewPass2!').then(() => null).catch(e => e.message)"
    )
    assert isinstance(err_msg, str) and len(err_msg) > 0


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f8_storage_never_writes_passwords_to_browser_storage(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F8-04 (TC02): OTP reset and changePassword never write OTP or passwords into localStorage/sessionStorage."""
    user = db.create_test_user(prefix="e2e_t2_f8_04")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    mark = live_server.output_mark()
    assert page.evaluate("e => CookMateStorage.requestPasswordResetOtp(e)", user["email"]).get("success") is True
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    verify_res = page.evaluate("([e, o]) => CookMateStorage.verifyPasswordResetOtp(e, o)", [user["email"], otp])
    temp_pw = verify_res["temporary_password"]

    assert page.evaluate("([e, p]) => CookMateStorage.login(e, p)", [user["email"], temp_pw]).get("success") is True
    new_pw = "FreshSafePass88!"
    assert page.evaluate("([c, n]) => CookMateStorage.changePassword(c, n, n)", [temp_pw, new_pw]).get("success") is True

    storage_dump = page.evaluate(
        "() => JSON.stringify({ ls: Object.assign({}, localStorage), ss: Object.assign({}, sessionStorage) })"
    )
    assert otp not in storage_dump
    assert temp_pw not in storage_dump
    assert new_pw not in storage_dump


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f8_storage_csrf_refresh_on_login_and_change_password(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F8-05: Consecutive CookMateStorage.login then changePassword synchronizes rotated CSRF token without 403."""
    user = db.create_test_user(prefix="e2e_t2_f8_05", password="StartPass1!")
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page, authenticated=False)

    login_res = page.evaluate("([e, p]) => CookMateStorage.login(e, p)", [user["email"], "StartPass1!"])
    assert login_res.get("success") is True
    change_res = page.evaluate("() => CookMateStorage.changePassword('StartPass1!', 'RotatedPass2!', 'RotatedPass2!')")
    assert change_res.get("success") is True


# ---------------------------------------------------------------------------
# F9: Forgot Password 3-Step UI (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f9_step1_client_validation_and_loading_state(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T2-F9-01: Empty/malformed email stays on Step 1 with visible error; valid submit shows loading state then Step 2."""
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    step1 = open_forgot_password_step1(page)
    step1_err = (
        step1.locator(
            '.auth-error-msg:visible, .form-error:visible, .error-message:visible, '
            '.field-error:visible, .invalid-feedback:visible, [role="alert"]:visible, [id*="Error" i]:visible'
        )
        .or_(page.locator(".toast:visible"))
        .or_(step1.get_by_text(re.compile(r"không hợp lệ|vui lòng nhập|chưa nhập|sai định dạng", re.I)))
    )

    for invalid_email in ("", "not-an-email"):
        submit_forgot_password_email(page, invalid_email)
        expect(page.get_by_text("Khôi phục mật khẩu", exact=False).first).to_be_visible()
        expect(page.get_by_text("Xác minh tài khoản", exact=False)).to_have_count(0)
        expect(step1_err.first).to_be_visible(timeout=5000)

    held_routes = []

    def _hold_forgot(route) -> None:
        held_routes.append(route)

    page.route("**/api/auth/forgot-password", _hold_forgot)
    submit_btn = step1.locator("button").filter(
        has_text=re.compile(r"Gửi mã xác minh|Đang gửi|Đang xử lý", re.I)
    ).first
    submit_forgot_password_email(page, "valid_loading@cookmate.test")
    expect(submit_btn).to_be_disabled(timeout=5000)
    assert len(held_routes) == 1, "Expected forgot-password XHR to be in-flight while button is in loading state"
    held_routes[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"success": True, "message": "Nếu email tồn tại trong hệ thống, mã xác minh đã được cấp."}),
    )
    page.unroute("**/api/auth/forgot-password", _hold_forgot)
    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=5000)


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f9_step2_displays_specific_wrong_and_locked_errors(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F9-02 (TC03, TC05): Step 2 renders specific error for wrong OTP and lockout on 5th wrong attempt."""
    user = db.create_test_user(prefix="e2e_t2_f9_02")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    mark = live_server.output_mark()
    submit_forgot_password_email(page, user["email"])
    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    wrong = "000000" if otp != "000000" else "999999"

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


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f9_step2_displays_expired_otp_error(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F9-03 (TC04): Backdated expired OTP renders specific expiration message in Step 2."""
    user = db.create_test_user(prefix="e2e_t2_f9_03")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    mark = live_server.output_mark()
    submit_forgot_password_email(page, user["email"])
    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    db.backdate_latest_otp_expiry(user["user_id"], minutes_ago=10)
    fill_otp_step2(page, otp)
    submit_verify_otp_step2(page)
    expect(page.get_by_text(re.compile(r"hết hạn", re.I)).first).to_be_visible(timeout=5000)


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f9_step2_resend_button_and_cooldown_error(
    server_factory, db: DbHelper, page: Page
) -> None:
    """T2-F9-04 (TC07): Clicking 'Gửi lại mã' handles 429 cooldown and succeeds after cooldown."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "3",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    user = db.create_test_user(prefix="e2e_t2_f9_04")
    page.goto(f"{srv.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    m1 = srv.output_mark()
    submit_forgot_password_email(page, user["email"])
    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)
    srv.wait_for_otp(user["email"], since_mark=m1, timeout=5.0)

    resend_btn = page.get_by_role("button", name="Gửi lại mã")
    resend_btn.click()
    expect(page.get_by_text(re.compile(r"quá nhanh|chờ|thử lại", re.I)).first).to_be_visible(timeout=5000)

    time.sleep(3.2)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)
    m2 = srv.output_mark()
    resend_btn.click()
    otp2 = srv.wait_for_otp(user["email"], since_mark=m2, timeout=5.0)
    fill_otp_step2(page, otp2)
    submit_verify_otp_step2(page)
    expect(page.get_by_text("Khôi phục mật khẩu thành công!", exact=False).first).to_be_visible(timeout=10000)


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f9_step3_toggle_copy_and_reload_clears_temp_password(
    live_server: CookMateServerHarness, db: DbHelper, context: BrowserContext
) -> None:
    """T2-F9-05 (TC02): Toggle switches password/text, copy writes clipboard, and reload clears secret."""
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=live_server.base_url)
    page = context.new_page()
    user = db.create_test_user(prefix="e2e_t2_f9_05")
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
    step3 = get_step3_scope(page)
    assert_step3_toggle_switches_visibility(step3, temp_pw)

    find_step3_copy_button(step3).click()
    copied = page.evaluate("() => navigator.clipboard.readText()")
    assert copied == temp_pw

    storage_json = page.evaluate(
        "() => JSON.stringify({ ls: Object.assign({}, localStorage), ss: Object.assign({}, sessionStorage) })"
    )
    assert temp_pw not in storage_json

    page.reload(wait_until="domcontentloaded")
    wait_for_login_page_ready(page)
    assert temp_pw not in page.content()
    expect(page.get_by_text("Khôi phục mật khẩu thành công!", exact=False)).to_have_count(0)


# ---------------------------------------------------------------------------
# F10: Avatar Dropdown & Change Password Modal (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f10_dropdown_stays_within_desktop_viewport(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F10-01 (TC10): Open #userDropdown fits inside viewport with zero overflow at 1280x800 and 1024x768."""
    user = db.create_test_user(
        prefix="e2e_t2_f10_01",
        password="UserPass1!",
        full_name="Nguyễn Văn Kiểm Thử Tên Rất Dài",
    )
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    for w, h in ((1280, 800), (1024, 768)):
        page.set_viewport_size({"width": w, "height": h})
        dropdown = open_avatar_dropdown(page)
        assert_element_within_viewport(page, dropdown, label=f"#userDropdown@{w}x{h}")
        item = get_dropdown_change_password_item(dropdown)
        assert_element_within_viewport(page, item, label=f"ChangePasswordItem@{w}x{h}")
        sw, iw = check_horizontal_overflow(page)
        assert sw <= iw
        page.locator("#userMenuTrigger").click()


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f10_mobile_drawer_shows_change_password_without_overflow(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F10-02 (TC10): On 375x812 mobile, #mobileAuthArea and #userDropdown show 'Đổi mật khẩu' (with lock icon) without overflow."""
    user = db.create_test_user(prefix="e2e_t2_f10_02", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    page.set_viewport_size({"width": 375, "height": 812})
    dropdown = open_avatar_dropdown(page)
    for label in ("Hồ sơ cá nhân", "Công thức của tôi", "Yêu thích", "Đăng công thức", "Đăng xuất"):
        expect(dropdown.get_by_text(label, exact=False).first).to_be_visible()
    dd_cp = get_dropdown_change_password_item(dropdown)
    expect(dd_cp).to_be_visible()
    expect(dd_cp.locator("i.fa-lock, svg").first).to_be_visible()
    assert_element_within_viewport(page, dropdown, label="#userDropdown@375x812")
    page.locator("#userMenuTrigger").click()

    page.locator("#menuToggle").click()
    mobile_auth = page.locator("#mobileAuthArea")
    expect(mobile_auth).to_be_visible(timeout=5000)
    expect(mobile_auth).to_contain_text(user["name"])
    mobile_cp = mobile_auth.get_by_role("button", name="Đổi mật khẩu").or_(
        mobile_auth.get_by_role("link", name="Đổi mật khẩu")
    ).first
    expect(mobile_cp).to_be_visible()
    expect(mobile_cp.locator("i.fa-lock, svg").first).to_be_visible()
    sw, iw = check_horizontal_overflow(page)
    assert sw <= iw


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f10_modal_validates_empty_short_mismatch_same_password(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F10-03 (TC13, TC14): Modal validation shows visible errors for empty, <8 chars, mismatch, and new==current, and shows loading state on valid submit."""
    user = db.create_test_user(prefix="e2e_t2_f10_03", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    modal = open_change_password_modal(page)
    cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
    submit_btn = modal.locator("button").filter(
        has_text=re.compile(r"Cập nhật mật khẩu|Đang cập nhật|Đang xử lý", re.I)
    ).first
    err_ui = (
        modal.locator(
            '.auth-error-msg:visible, .form-error:visible, .error-message:visible, '
            '.field-error:visible, .invalid-feedback:visible, [role="alert"]:visible, [id*="Error" i]:visible'
        )
        .or_(page.locator(".toast:visible"))
        .or_(
            modal.get_by_text(
                re.compile(r"nhập|ít nhất 8|không khớp|trùng|khác|không hợp lệ|bắt buộc", re.I)
            )
        )
    )

    for cur_v, new_v, conf_v in (
        ("", "NewStrong2!", "NewStrong2!"),
        ("UserPass1!", "", ""),
        ("UserPass1!", "short7!", "short7!"),
        ("UserPass1!", "NewStrong2!", "Mismatch3!"),
        ("UserPass1!", "UserPass1!", "UserPass1!"),
    ):
        cur_inp.fill(cur_v)
        new_inp.fill(new_v)
        conf_inp.fill(conf_v)
        submit_btn.click()
        expect(modal).to_be_visible()
        expect(err_ui.first).to_be_visible(timeout=5000)

    assert db.get_user_by_id(user["user_id"])["password_hash"] == user["password_hash"]

    held_routes = []

    def _hold_change(route) -> None:
        held_routes.append(route)

    page.route("**/api/auth/change-password", _hold_change)
    cur_inp.fill("UserPass1!")
    new_inp.fill("ValidNewPass9!")
    conf_inp.fill("ValidNewPass9!")
    submit_btn.click()
    expect(submit_btn).to_be_disabled(timeout=5000)
    assert len(held_routes) == 1
    held_routes[0].continue_()
    page.unroute("**/api/auth/change-password", _hold_change)
    expect(modal).to_be_hidden(timeout=10000)


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f10_modal_three_toggles_switch_input_types_independently(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F10-04: Each of the 3 eye toggle buttons switches only its own field between password and text."""
    user = db.create_test_user(prefix="e2e_t2_f10_04", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    modal = open_change_password_modal(page)
    cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
    fields = (cur_inp, new_inp, conf_inp)

    for idx, field in enumerate(fields):
        toggle = get_toggle_button_for_input(field)
        expect(field).to_have_attribute("type", "password")
        toggle.click()
        expect(field).to_have_attribute("type", "text")
        for other_idx, other in enumerate(fields):
            if other_idx != idx:
                expect(other).to_have_attribute("type", "password")
        toggle.click()
        expect(field).to_have_attribute("type", "password")


@pytest.mark.tier2
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t2_f10_modal_wrong_current_password_shows_error_keeps_modal_open(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T2-F10-05 (TC12): Submitting wrong current password shows error feedback and keeps modal open."""
    user = db.create_test_user(prefix="e2e_t2_f10_05", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    modal = open_change_password_modal(page)
    cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
    cur_inp.fill("WrongCurrent9!")
    new_inp.fill("NewValidPass2!")
    conf_inp.fill("NewValidPass2!")
    modal.get_by_role("button", name="Cập nhật mật khẩu").click()

    expect(modal).to_be_visible()
    err_ui = page.locator(".toast:visible").or_(modal.get_by_text(re.compile(r"không đúng|sai", re.I)))
    expect(err_ui.first).to_be_visible(timeout=5000)
