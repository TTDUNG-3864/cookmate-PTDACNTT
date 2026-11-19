"""Opaque-box Playwright browser launcher and resilient UI page helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Locator, Page, Playwright, expect


def launch_browser(playwright: Playwright) -> Browser:
    """Launch headless Chromium using system Chrome/Edge channel fallback."""
    custom_path = os.environ.get("COOKMATE_CHROME_PATH", "").strip()
    if custom_path and Path(custom_path).exists():
        return playwright.chromium.launch(executable_path=custom_path, headless=True)

    last_error: Exception | None = None
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch(channel=channel, headless=True)
        except Exception as exc:
            last_error = exc

    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        raise RuntimeError(
            f"Unable to launch Playwright headless browser via channel='chrome', 'msedge', or default chromium. "
            f"Channel error: {last_error}; Default error: {exc}"
        ) from exc


def wait_for_app_ready(page: Page, *, authenticated: bool | None = None) -> None:
    """Wait until CookMateStorage deferred DOMContentLoaded finishes rendering #siteHeader."""
    expect(page.locator("#siteHeader .header-inner")).to_be_visible(timeout=15000)
    if authenticated is True:
        expect(page.locator("#userMenuTrigger")).to_be_visible(timeout=15000)
    elif authenticated is False:
        expect(page.locator("#authArea")).to_be_visible(timeout=15000)


def wait_for_login_page_ready(page: Page) -> None:
    """Wait until CookMateStorage + CookMateAuthUI finish initializing login.html."""
    expect(page.locator("#loginForm")).to_be_visible(timeout=15000)
    expect(page.locator("#loginSubmitBtn")).to_be_enabled(timeout=15000)
    page.evaluate(
        "() => typeof CookMateStorage !== 'undefined' && CookMateStorage.ready "
        "? CookMateStorage.ready.then(() => new Promise(r => setTimeout(r, 0))) "
        ": Promise.resolve()"
    )


def login_via_ui(page: Page, base_url: str, email: str, password: str, *, wait_redirect: bool = True) -> None:
    page.goto(f"{base_url}/pages/auth/login.html", wait_until="domcontentloaded")
    wait_for_login_page_ready(page)
    page.locator("#loginEmail").fill(email)
    page.locator("#loginPassword").fill(password)
    page.locator("#loginSubmitBtn").click()
    if wait_redirect:
        page.wait_for_url(re.compile(r"(index\.html|/)$"), timeout=15000)
        wait_for_app_ready(page, authenticated=True)


def get_forgot_trigger(page: Page) -> Locator:
    return page.get_by_role("link", name="Quên mật khẩu?").or_(
        page.get_by_role("button", name="Quên mật khẩu?")
    ).first


def open_forgot_password_step1(page: Page) -> Locator:
    get_forgot_trigger(page).click()
    expect(page.get_by_text("Khôi phục mật khẩu", exact=False).first).to_be_visible(timeout=10000)
    expect(
        page.get_by_text("Nhập địa chỉ email đã đăng ký để nhận mã xác minh.", exact=False).first
    ).to_be_visible(timeout=10000)
    return get_step1_scope(page)


def get_step1_scope(page: Page) -> Locator:
    modal_scope = page.locator(
        '.modal.active, .modal.modal-show, [role="dialog"]:visible, #cookmate-modal:visible'
    ).filter(has_text="Khôi phục mật khẩu")
    if modal_scope.count() > 0:
        return modal_scope.last
    card_scope = page.locator("#authCardWrapper, .cookmate-auth__card-inner, main, body").filter(
        has_text="Khôi phục mật khẩu"
    )
    return card_scope.last


def get_step1_email_input(scope: Locator) -> Locator:
    email_inputs = scope.locator('input[type="email"]:visible, input[name*="email" i]:visible')
    for idx in range(email_inputs.count()):
        candidate = email_inputs.nth(idx)
        if candidate.get_attribute("id") != "loginEmail":
            return candidate
    fallback = scope.locator("input:visible").first
    return fallback


def submit_forgot_password_email(page: Page, email: str) -> None:
    scope = get_step1_scope(page)
    email_input = get_step1_email_input(scope)
    email_input.fill(email)
    page.get_by_role("button", name="Gửi mã xác minh").click()


def get_step2_scope(page: Page) -> Locator:
    modal_scope = page.locator(
        '.modal.active, .modal.modal-show, [role="dialog"]:visible, #cookmate-modal:visible'
    ).filter(has_text="Xác minh tài khoản")
    if modal_scope.count() > 0:
        return modal_scope.last
    return page.locator("#authCardWrapper, .cookmate-auth__card-inner, main, body").filter(
        has_text="Xác minh tài khoản"
    ).last


def fill_otp_step2(page: Page, otp: str) -> None:
    """Populate either a 6-box digit input array or a single 6-digit OTP input."""
    scope = get_step2_scope(page)
    otp_inputs = scope.locator(
        'input:visible:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="email"]):not([readonly]):not([disabled]):not(#loginEmail):not(#loginPassword)'
    )
    count = otp_inputs.count()
    if count >= 6:
        digit_inputs = otp_inputs
        for idx, ch in enumerate(otp[:6]):
            digit_inputs.nth(idx).fill(ch)
    elif count >= 1:
        otp_inputs.first.fill(otp)
    else:
        raise AssertionError("No visible OTP input found in Step 2 ('Xác minh tài khoản').")


def submit_verify_otp_step2(page: Page) -> None:
    page.get_by_role("button", name="Xác minh").click()


def get_step3_scope(page: Page) -> Locator:
    modal_scope = page.locator(
        '.modal.active, .modal.modal-show, [role="dialog"]:visible, #cookmate-modal:visible'
    ).filter(has_text="Khôi phục mật khẩu thành công!")
    if modal_scope.count() > 0:
        return modal_scope.last
    return page.locator("#authCardWrapper, .cookmate-auth__card-inner, main, body").filter(
        has_text="Khôi phục mật khẩu thành công!"
    ).last


def extract_step3_temp_password(page: Page) -> str:
    """Extract the generated temporary password from Step 3 regardless of tag/masking."""
    scope = get_step3_scope(page)
    pw_input = scope.locator(
        'input[type="password"]:visible:not(#loginEmail):not(#loginPassword), '
        'input[type="text"]:visible:not(#loginEmail):not(#loginPassword)'
    )
    for idx in range(pw_input.count()):
        candidate = pw_input.nth(idx)
        val = candidate.input_value().strip()
        if len(val) >= 16:
            return val

    code_el = scope.locator("code:visible, pre:visible, [data-temp-password]:visible")
    for idx in range(code_el.count()):
        el = code_el.nth(idx)
        attr_val = (el.get_attribute("data-temp-password") or "").strip()
        if len(attr_val) >= 16 and not any(ch.isspace() for ch in attr_val):
            return attr_val
        txt = el.inner_text().strip()
        if len(txt) >= 16 and not any(ch.isspace() for ch in txt) and not (set(txt) <= {"•", "*", "●"}):
            return txt

    raise AssertionError("Could not extract >=16-char temporary password from Step 3 UI.")


def find_step3_toggle_button(scope: Locator) -> Locator:
    btn = scope.locator("button:visible").filter(
        has=scope.page.locator("i.fa-eye, i.fa-eye-slash, svg")
    )
    if btn.count() > 0:
        return btn.first
    return scope.get_by_role("button", name=re.compile(r"hiện|ẩn|xem|show|hide", re.I)).first


def assert_step3_toggle_switches_visibility(step3: Locator, expected_temp_pw: str) -> None:
    """Verify Step 3 show/hide toggle switches masked vs revealed state without silent skips."""
    toggle_btn = find_step3_toggle_button(step3)
    expect(toggle_btn).to_be_visible()

    pw_field = step3.locator(
        'input[type="password"]:visible:not(#loginEmail):not(#loginPassword), '
        'input[type="text"]:visible:not(#loginEmail):not(#loginPassword)'
    ).first
    if pw_field.count() > 0:
        initial_type = pw_field.get_attribute("type")
        toggle_btn.click()
        toggled_type = pw_field.get_attribute("type")
        assert initial_type != toggled_type, (
            f"Step 3 toggle did not change input type ({initial_type!r} -> {toggled_type!r})"
        )
        assert {initial_type, toggled_type} == {"password", "text"}
        return

    code_el = step3.locator("code:visible, pre:visible, [data-temp-password]:visible").first
    assert code_el.count() > 0, (
        "Expected visible temporary password <input> or <code>/<pre>/[data-temp-password] in Step 3."
    )
    before_text = code_el.inner_text().strip()
    toggle_btn.click()
    after_text = code_el.inner_text().strip()
    assert before_text != after_text, (
        f"Step 3 toggle did not change masked/revealed text in code/pre element ({before_text!r})."
    )
    assert expected_temp_pw in (before_text, after_text), (
        f"Expected temporary password in revealed state ({before_text!r} / {after_text!r})."
    )


def find_step3_copy_button(scope: Locator) -> Locator:
    named = scope.get_by_role("button", name=re.compile(r"sao chép|copy", re.I))
    if named.count() > 0:
        return named.first
    icon_btn = scope.locator("button:visible").filter(
        has=scope.page.locator("i.fa-copy, i.fa-clone")
    )
    return icon_btn.first


def open_avatar_dropdown(page: Page) -> Locator:
    trigger = page.locator("#userMenuTrigger")
    expect(trigger).to_be_visible(timeout=15000)
    dropdown = page.locator("#userDropdown")
    if not dropdown.is_visible():
        trigger.click()
    expect(dropdown).to_be_visible(timeout=5000)
    return dropdown


def get_dropdown_change_password_item(dropdown: Locator) -> Locator:
    return dropdown.get_by_role("button", name="Đổi mật khẩu").or_(
        dropdown.get_by_role("link", name="Đổi mật khẩu")
    ).first


def open_change_password_modal(page: Page) -> Locator:
    dropdown = open_avatar_dropdown(page)
    item = get_dropdown_change_password_item(dropdown)
    expect(item).to_be_visible(timeout=5000)
    item.click()
    expect(
        page.locator(
            '.modal.active:visible, .modal.modal-show:visible, #cookmate-modal:visible, [role="dialog"]:visible'
        )
        .filter(has_text="Đổi mật khẩu")
        .first
    ).to_be_visible(timeout=10000)
    modal = get_active_change_password_modal(page)
    expect(modal).to_be_visible(timeout=10000)
    return modal


def get_active_change_password_modal(page: Page) -> Locator:
    outer_modal = page.locator(
        ".modal.active:visible, .modal.modal-show:visible, #cookmate-modal:visible"
    ).filter(has_text="Đổi mật khẩu")
    if outer_modal.count() > 0:
        return outer_modal.last
    return page.locator('[role="dialog"]:visible').filter(has_text="Đổi mật khẩu").last


def get_change_password_inputs(modal: Locator) -> tuple[Locator, Locator, Locator]:
    cur = modal.get_by_label(re.compile(r"mật khẩu hiện tại|hiện tại", re.I))
    new = modal.get_by_label(re.compile(r"^mật khẩu mới", re.I))
    conf = modal.get_by_label(re.compile(r"xác nhận", re.I))
    if cur.count() > 0 and new.count() > 0 and conf.count() > 0:
        return cur.first, new.first, conf.first
    inputs = modal.locator('input[type="password"], input[type="text"]')
    assert inputs.count() >= 3, f"Expected 3 password fields in Change Password modal, got {inputs.count()}"
    return inputs.nth(0), inputs.nth(1), inputs.nth(2)


def get_toggle_button_for_input(input_locator: Locator) -> Locator:
    parent_btn = input_locator.locator("xpath=..").locator("button")
    if parent_btn.count() > 0:
        return parent_btn.first
    grand_btn = input_locator.locator("xpath=../..").locator("button")
    return grand_btn.first


def measure_header_height(page: Page) -> float:
    box = page.locator("#siteHeader, .site-header").first.bounding_box()
    assert box is not None, "Header bounding box was None"
    return float(box["height"])


def check_horizontal_overflow(page: Page) -> tuple[int, int]:
    dims = page.evaluate("() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth })")
    return int(dims["sw"]), int(dims["iw"])


def assert_element_within_viewport(page: Page, locator: Locator, label: str = "element") -> dict[str, float]:
    box = locator.bounding_box()
    assert box is not None, f"{label} bounding_box() returned None"
    vp = page.evaluate("() => ({ w: window.innerWidth, h: window.innerHeight })")
    assert box["x"] >= -0.5, f"{label} overflows left edge: x={box['x']}"
    assert box["y"] >= -0.5, f"{label} overflows top edge: y={box['y']}"
    assert box["x"] + box["width"] <= vp["w"] + 0.5, (
        f"{label} overflows right edge: x+w={box['x'] + box['width']} > innerWidth={vp['w']}"
    )
    assert box["y"] + box["height"] <= vp["h"] + 0.5, (
        f"{label} overflows bottom edge: y+h={box['y'] + box['height']} > innerHeight={vp['h']}"
    )
    return {k: float(v) for k, v in box.items()}


def get_computed_z_index(locator: Locator) -> int:
    raw = locator.evaluate("el => window.getComputedStyle(el).zIndex")
    if raw == "auto" or raw is None or raw == "":
        return 0
    return int(float(raw))


def hit_test_center(page: Page, locator: Locator) -> dict[str, Any]:
    box = locator.bounding_box()
    assert box is not None, "Target element has no bounding box for hit-test"
    cx = box["x"] + box["width"] / 2.0
    cy = box["y"] + box["height"] / 2.0
    return locator.evaluate(
        """(targetEl, [x, y]) => {
            const hit = document.elementFromPoint(x, y);
            if (!hit) return { hit: false, sameOrDescendant: false, id: '', tag: '', className: '' };
            return {
                hit: true,
                sameOrDescendant: targetEl === hit || targetEl.contains(hit) || hit.contains(targetEl),
                id: hit.id || '',
                tag: hit.tagName || '',
                className: typeof hit.className === 'string' ? hit.className : '',
            };
        }""",
        [cx, cy],
    )
