"""Tier 1 isolated frontend unit/component tests for F7 (CookMateUI), F8 (CookMateStorage), F9 (Forgot UI), and F10 (Avatar Dropdown & Change Modal)."""

from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Page, expect

from helpers.browser_helper import (
    get_change_password_inputs,
    get_computed_z_index,
    get_dropdown_change_password_item,
    get_step2_scope,
    get_step3_scope,
    login_via_ui,
    measure_header_height,
    open_avatar_dropdown,
    open_change_password_modal,
    open_forgot_password_step1,
    submit_forgot_password_email,
    wait_for_app_ready,
    wait_for_login_page_ready,
    fill_otp_step2,
    submit_verify_otp_step2,
    find_step3_toggle_button,
    find_step3_copy_button,
    extract_step3_temp_password,
)
from helpers.db_helper import DbHelper
from helpers.server_harness import CookMateServerHarness


# ---------------------------------------------------------------------------
# F7: Shared Modal & Toast Alignment (CookMateUI) (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f7_show_modal_renders_active_bem_classes(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T1-F7-01: CookMateUI.showModal renders visible .modal.active with BEM children."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    page.evaluate(
        "() => CookMateUI.showModal({ title: 'T1 Modal', content: '<p>Nội dung thử</p>', footer: '<button class=\"btn btn-primary\">OK</button>' })"
    )
    modal = page.locator("#cookmate-modal.modal.active, .modal.active").last
    expect(modal).to_be_visible(timeout=5000)
    expect(modal.locator(".modal__content")).to_be_visible()
    expect(modal.locator(".modal__header")).to_contain_text("T1 Modal")
    expect(modal.locator(".modal__body")).to_contain_text("Nội dung thử")


@pytest.mark.tier1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f7_show_toast_renders_variant_classes(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T1-F7-02: CookMateUI.showToast renders visible variant toasts for success/error/warning/info."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    for variant in ("success", "error", "warning", "info"):
        msg = f"Toast-{variant}"
        page.evaluate("([m, v]) => CookMateUI.showToast(m, v, 5000)", [msg, variant])
        toast = page.locator(f".toast--{variant}:visible").filter(has_text=msg)
        expect(toast.first).to_be_visible(timeout=5000)


@pytest.mark.tier1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f7_modal_and_toast_zindex_above_chefbot(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T1-F7-03: Modal and toast z-index values are strictly greater than #cmChefBotLauncher (>9999)."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    launcher = page.locator("#cmChefBotLauncher")
    expect(launcher).to_be_visible(timeout=10000)
    launcher_z = get_computed_z_index(launcher)

    page.evaluate("() => { CookMateUI.showModal({ title: 'ZCheck', content: '<p>Body</p>' }); CookMateUI.showToast('ZToast', 'info', 5000); }")
    modal = page.locator(".modal.active:visible, .modal.modal-show:visible, #cookmate-modal:visible").first
    toast = page.locator(".toast:visible").last
    expect(modal).to_be_visible(timeout=5000)
    expect(toast).to_be_visible(timeout=5000)

    modal_z = get_computed_z_index(modal)
    toast_container = page.locator(".toast-container").filter(has=page.locator(".toast:visible")).last
    expect(toast_container).to_be_visible(timeout=5000)
    toast_container_z = get_computed_z_index(toast_container)
    assert modal_z > launcher_z and modal_z > 9999, f"Expected modal root z-index > 9999, got {modal_z}"
    assert toast_container_z > launcher_z and toast_container_z > 9999, (
        f"Expected .toast-container z-index > 9999, got {toast_container_z}"
    )


@pytest.mark.tier1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f7_modal_closes_via_close_button(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T1-F7-04: Clicking .modal__close / #modalCloseBtn dismisses the active modal."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    page.evaluate("() => CookMateUI.showModal({ title: 'Closable', content: '<p>Hi</p>' })")
    modal = page.locator("#cookmate-modal")
    expect(modal).to_be_visible(timeout=5000)
    modal.locator("#modalCloseBtn, .modal__close").first.click()
    expect(modal).to_have_count(0, timeout=5000)


@pytest.mark.tier1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f7_show_confirm_remains_functional(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T1-F7-05: CookMateUI.showConfirm invokes onConfirm callback when #confirmOk is clicked."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page)

    page.evaluate("() => { window.__confirmed = false; CookMateUI.showConfirm('Xác nhận xóa?', () => { window.__confirmed = true; }); }")
    ok_btn = page.locator("#confirmOk")
    expect(ok_btn).to_be_visible(timeout=5000)
    ok_btn.click()
    assert page.evaluate("() => window.__confirmed") is True


# ---------------------------------------------------------------------------
# F8: Client Storage API Wrappers (CookMateStorage) (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f8_storage_exposes_all_auth_methods(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T1-F8-01: CookMateStorage exposes all 4 new password management wrapper methods."""
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    types = page.evaluate(
        """() => ({
            req: typeof CookMateStorage.requestPasswordResetOtp,
            verify: typeof CookMateStorage.verifyPasswordResetOtp,
            resend: typeof CookMateStorage.resendPasswordResetOtp,
            change: typeof CookMateStorage.changePassword,
        })"""
    )
    assert all(val == "function" for val in types.values()), f"Missing methods: {types}"


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f8_storage_request_otp_sends_csrf_and_resolves(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F8-02 (TC01): CookMateStorage.requestPasswordResetOtp sends X-CSRF-Token and resolves."""
    user = db.create_test_user(prefix="e2e_f8_02")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    mark = live_server.output_mark()
    res = page.evaluate(
        "email => CookMateStorage.requestPasswordResetOtp(email)",
        user["email"],
    )
    assert res.get("success") is True
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    assert len(otp) == 6


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f8_storage_resend_otp_resolves_after_cooldown(
    server_factory, db: DbHelper, page: Page
) -> None:
    """T1-F8-03: CookMateStorage.resendPasswordResetOtp resolves with success: true after cooldown."""
    srv = server_factory(
        {
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "1",
            "OTP_IP_RATE_LIMIT_MAX": "500",
        }
    )
    user = db.create_test_user(prefix="e2e_f8_03")
    page.goto(f"{srv.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    assert page.evaluate("email => CookMateStorage.requestPasswordResetOtp(email)", user["email"]).get("success") is True
    time.sleep(1.1)
    db.backdate_otps_created_at(user["user_id"], seconds_ago=120)

    mark2 = srv.output_mark()
    res2 = page.evaluate("email => CookMateStorage.resendPasswordResetOtp(email)", user["email"])
    assert res2.get("success") is True
    assert len(srv.wait_for_otp(user["email"], since_mark=mark2, timeout=5.0)) == 6


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f8_storage_verify_otp_returns_temp_password(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F8-04 (TC02): CookMateStorage.verifyPasswordResetOtp returns temporary_password >= 16 chars."""
    user = db.create_test_user(prefix="e2e_f8_04")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    mark = live_server.output_mark()
    assert page.evaluate("email => CookMateStorage.requestPasswordResetOtp(email)", user["email"]).get("success") is True
    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)

    res = page.evaluate("([e, o]) => CookMateStorage.verifyPasswordResetOtp(e, o)", [user["email"], otp])
    assert res.get("success") is True
    assert len(res.get("temporary_password", "")) >= 16


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f8_storage_change_password_when_logged_in(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F8-05 (TC11): CookMateStorage.changePassword succeeds for authenticated browser session."""
    user = db.create_test_user(prefix="e2e_f8_05", password="StartPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "StartPass1!")

    res = page.evaluate(
        "() => CookMateStorage.changePassword('StartPass1!', 'UpdatedPass2!', 'UpdatedPass2!')"
    )
    assert res.get("success") is True


# ---------------------------------------------------------------------------
# F9: Forgot Password 3-Step UI (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f9_forgot_password_link_opens_step1_card(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T1-F9-01: Clicking 'Quên mật khẩu?' opens Step 1 'Khôi phục mật khẩu' UI."""
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    expect(page.get_by_role("button", name="Gửi mã xác minh")).to_be_visible()
    back_btn = page.get_by_role("button", name="Quay lại đăng nhập").or_(
        page.get_by_role("link", name="Quay lại đăng nhập")
    ).first
    expect(back_btn).to_be_visible()


@pytest.mark.tier1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f9_back_to_login_button_restores_login_form(
    live_server: CookMateServerHarness, page: Page
) -> None:
    """T1-F9-02: Clicking 'Quay lại đăng nhập' restores #loginForm cleanly."""
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    page.get_by_role("button", name="Quay lại đăng nhập").or_(
        page.get_by_role("link", name="Quay lại đăng nhập")
    ).first.click()

    expect(page.locator("#loginForm")).to_be_visible(timeout=5000)
    expect(page.locator("#loginEmail")).to_be_visible()


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f9_step2_renders_6_digit_otp_and_timer(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F9-03 (TC01): Submitting Step 1 transitions to Step 2 'Xác minh tài khoản' with 6-digit input and 5:00 timer."""
    user = db.create_test_user(prefix="e2e_f9_03")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    submit_forgot_password_email(page, user["email"])

    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)
    expect(
        page.get_by_text("Nhập mã xác minh 6 chữ số được cấp trong Terminal.", exact=False).first
    ).to_be_visible()
    expect(page.get_by_role("button", name="Xác minh")).to_be_visible()
    expect(page.get_by_role("button", name="Gửi lại mã")).to_be_visible()

    step2 = get_step2_scope(page)
    expect(step2).to_contain_text(re.compile(r"\b[0-5]:[0-5]\d\b"))
    otp_inputs = step2.locator(
        'input:visible:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="email"]):not([readonly]):not([disabled]):not(#loginEmail):not(#loginPassword)'
    )
    assert otp_inputs.count() in (1, 6), f"Expected 1 or 6 OTP inputs, got {otp_inputs.count()}"


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f9_step2_never_displays_otp_in_dom(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F9-04 (TC01): Terminal OTP string is never present in DOM innerHTML or innerText."""
    user = db.create_test_user(prefix="e2e_f9_04")
    page.goto(f"{live_server.base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)

    open_forgot_password_step1(page)
    mark = live_server.output_mark()
    submit_forgot_password_email(page, user["email"])
    expect(page.get_by_text("Xác minh tài khoản", exact=False).first).to_be_visible(timeout=10000)

    otp = live_server.wait_for_otp(user["email"], since_mark=mark, timeout=5.0)
    dom_text = page.evaluate("() => document.body.innerText + '\\n' + document.body.innerHTML")
    assert otp not in dom_text


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f9_step3_displays_temp_password_toggle_copy_warning(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F9-05 (TC02): Valid OTP opens Step 3 with temp password >= 16 chars, toggle, copy, warning, and login link."""
    user = db.create_test_user(prefix="e2e_f9_05")
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
    expect(page.get_by_text("CookMate đã cấp cho bạn một mật khẩu mới.", exact=False).first).to_be_visible()
    expect(
        page.get_by_text(
            "Vui lòng lưu mật khẩu này. Mật khẩu chỉ được hiển thị một lần. Sau khi đăng nhập, bạn nên đổi sang mật khẩu riêng của mình.",
            exact=False,
        ).first
    ).to_be_visible()

    temp_pw = extract_step3_temp_password(page)
    assert len(temp_pw) >= 16

    step3 = get_step3_scope(page)
    expect(find_step3_toggle_button(step3)).to_be_visible()
    expect(find_step3_copy_button(step3)).to_be_visible()
    expect(
        step3.get_by_role("button", name="Về trang đăng nhập").or_(
            step3.get_by_role("link", name="Về trang đăng nhập")
        ).first
    ).to_be_visible()


# ---------------------------------------------------------------------------
# F10: Avatar Dropdown & Change Password Modal (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f10_avatar_dropdown_contains_change_password_and_lock_icon(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F10-01 (TC10): Logged-in #userDropdown keeps user info + existing items and places 'Đổi mật khẩu' (with lock icon) before logout."""
    user = db.create_test_user(prefix="e2e_f10_01", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    expect(page.locator("#authArea")).to_contain_text(user["name"])
    dropdown = open_avatar_dropdown(page)
    for label in ("Hồ sơ cá nhân", "Công thức của tôi", "Yêu thích", "Đăng công thức", "Đăng xuất"):
        expect(dropdown.get_by_text(label, exact=False).first).to_be_visible()

    item = get_dropdown_change_password_item(dropdown)
    expect(item).to_be_visible()
    expect(item.locator("i.fa-lock, svg").first).to_be_visible()

    logout_item = dropdown.get_by_role("button", name=re.compile(r"Đăng xuất", re.I)).or_(
        dropdown.get_by_role("link", name=re.compile(r"Đăng xuất", re.I))
    ).first
    item_box = item.bounding_box()
    logout_box = logout_item.bounding_box()
    assert item_box is not None and logout_box is not None
    assert item_box["y"] < logout_box["y"], (
        f"Expected 'Đổi mật khẩu' (y={item_box['y']}) above 'Đăng xuất' (y={logout_box['y']})"
    )


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f10_header_height_unchanged_at_72px(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F10-02 (TC10): .site-header height stays ~72px before/after login and opening dropdown."""
    page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
    wait_for_app_ready(page, authenticated=False)
    guest_h = measure_header_height(page)

    user = db.create_test_user(prefix="e2e_f10_02", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")
    logged_h = measure_header_height(page)
    open_avatar_dropdown(page)
    open_h = measure_header_height(page)

    assert abs(logged_h - guest_h) < 1.0
    assert abs(open_h - logged_h) < 1.0
    assert 70.0 <= open_h <= 75.0


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f10_clicking_change_password_opens_modal(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F10-03: Clicking 'Đổi mật khẩu' opens modal with title and subtitle."""
    user = db.create_test_user(prefix="e2e_f10_03", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    modal = open_change_password_modal(page)
    expect(modal).to_contain_text("Đổi mật khẩu")
    expect(modal).to_contain_text("Bảo vệ tài khoản bằng mật khẩu mới.")


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f10_modal_has_three_password_toggles_and_buttons(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F10-04: Modal has 3 masked password fields, 3 toggle buttons, 'Cập nhật mật khẩu', and 'Hủy'."""
    user = db.create_test_user(prefix="e2e_f10_04", password="UserPass1!")
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    modal = open_change_password_modal(page)
    cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
    expect(cur_inp).to_have_attribute("type", "password")
    expect(new_inp).to_have_attribute("type", "password")
    expect(conf_inp).to_have_attribute("type", "password")

    toggles = modal.locator("button").filter(has=page.locator("i.fa-eye, i.fa-eye-slash, svg"))
    assert toggles.count() >= 3

    expect(modal.get_by_role("button", name="Cập nhật mật khẩu")).to_be_visible()
    expect(modal.get_by_role("button", name="Hủy")).to_be_visible()


@pytest.mark.tier1
@pytest.mark.requires_m1
@pytest.mark.requires_m2
@pytest.mark.browser
def test_t1_f10_cancel_button_closes_modal_cleanly(
    live_server: CookMateServerHarness, db: DbHelper, page: Page
) -> None:
    """T1-F10-05: Clicking 'Hủy' closes the Change Password modal cleanly without mutating password."""
    user = db.create_test_user(prefix="e2e_f10_05", password="UserPass1!")
    old_hash = db.get_user_by_id(user["user_id"])["password_hash"]
    login_via_ui(page, live_server.base_url, user["email"], "UserPass1!")

    modal = open_change_password_modal(page)
    modal.get_by_role("button", name="Hủy").click()
    expect(modal).to_be_hidden(timeout=5000)
    assert db.get_user_by_id(user["user_id"])["password_hash"] == old_hash
