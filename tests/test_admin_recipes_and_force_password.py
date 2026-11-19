"""Automated API, MySQL, and Playwright E2E tests for TC01-TC22:
- Part 1: Admin Recipe Review Detail Modal (TC01-TC07)
- Part 2: Admin Recipe Delete with FK & Transaction Safety (TC08-TC14)
- Part 3: Mandatory Password Change after OTP Recovery (TC15-TC22)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.security import check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "e2e"))

from backend.database.connection import fetch_one, transaction
from backend.database import repositories as repo
from backend.database.schema_upgrade import ensure_runtime_schema
from helpers.browser_helper import (
    fill_otp_step2,
    get_change_password_inputs,
    launch_browser,
    login_via_ui,
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

ARTIFACT_DIR = Path(
    os.environ.get(
        "COOKMATE_ARTIFACT_DIR",
        r"C:\Users\TTD\.gemini\antigravity\brain\a94eb504-24b6-4a8f-bf52-92094aecae4e",
    )
)


@pytest.fixture(scope="module")
def db() -> DbHelper:
    ensure_runtime_schema()
    helper = DbHelper()
    try:
        yield helper
    finally:
        helper.cleanup()


@pytest.fixture(scope="module")
def live_server() -> CookMateServerHarness:
    harness = CookMateServerHarness(
        env_overrides={
            "DEMO_MODE": "true",
            "APP_ENV": "development",
            "SESSION_COOKIE_SECURE": "false",
            "OTP_RESEND_COOLDOWN_SECONDS": "60",
            "OTP_REQUEST_WINDOW_SECONDS": "900",
            "OTP_REQUEST_MAX_PER_WINDOW": "20",
        }
    )
    harness.start()
    try:
        yield harness
    finally:
        harness.stop()


@pytest.fixture(scope="module")
def browser_instance():
    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            yield browser
        finally:
            browser.close()


def _create_pending_recipe_in_db(
    db: DbHelper,
    author_id: int,
    *,
    title: str,
    with_dish: bool = False,
    shared_dish_id: int | None = None,
) -> dict[str, Any]:
    """Create a rich pending recipe with ingredients, steps, nutrition, sources, and optional dish link."""
    cat_row = fetch_one("SELECT category_id FROM categories ORDER BY category_id ASC LIMIT 1")
    cat_id = int(cat_row["category_id"]) if cat_row else 1

    ing_row = fetch_one("SELECT ingredient_id, ingredient_name FROM ingredients ORDER BY ingredient_id ASC LIMIT 1")
    shared_ing_id = int(ing_row["ingredient_id"])
    shared_ing_name = str(ing_row["ingredient_name"])

    dish_id = shared_dish_id
    with transaction() as (_, cur):
        if with_dish and dish_id is None:
            cur.execute(
                "INSERT INTO dishes (dish_name, slug, category_id, thumbnail_url, cook_time_mins, difficulty) "
                "VALUES (%s, %s, %s, '', 45, 'Trung bình')",
                (title, f"test-dish-{author_id}-{ abs(hash(title)) % 100000 }", cat_id),
            )
            dish_id = int(cur.lastrowid)
            cur.execute(
                "INSERT INTO dish_ingredients (dish_id, ingredient_id, is_required, weight_score) "
                "VALUES (%s, %s, 1, 1.000)",
                (dish_id, shared_ing_id),
            )

        recipe = repo.create_recipe(
            {
                "title": title,
                "description": "Mô tả chi tiết món ăn truyền thống đậm đà hương vị Việt.",
                "image": "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=800",
                "categoryId": cat_id,
                "cuisine": "Miền Bắc",
                "difficulty": "medium",
                "prepTime": 20,
                "cookTime": 25,
                "time": 45,
                "servings": 4,
                "occasion": "Cuối tuần",
                "calories": 540,
                "protein": 32.5,
                "carbs": 48.0,
                "fat": 18.0,
                "fiber": 4.5,
                "ingredients": [
                    {
                        "name": shared_ing_name,
                        "amount": 500,
                        "unit": "g",
                        "note": "Thái lát mỏng vừa ăn",
                    },
                    {
                        "name": "Nước mắm nhĩ Phú Quốc",
                        "amount": 3,
                        "unit": "muỗng canh",
                        "note": "Pha nước chấm chua ngọt",
                    },
                ],
                "steps": [
                    {
                        "title": "Ướp thịt nướng",
                        "description": "Trộn đều nguyên liệu với gia vị và ướp trong 20 phút cho thấm đều.",
                        "time": 20,
                        "tip": "Thêm chút mật ong giúp thịt nướng lên màu vàng óng.",
                        "image": "",
                    },
                    {
                        "title": "Nướng chả trên than hoa",
                        "description": "Kẹp thịt vào vỉ và nướng chín vàng đều hai mặt.",
                        "time": 15,
                        "tip": "Quét dầu ăn lên vỉ để thịt không bị dính.",
                        "image": "",
                    },
                ],
            },
            author_id,
            admin=False,
        )
        recipe_id = int(recipe["id"])
        if dish_id is not None:
            cur.execute("UPDATE recipes SET dish_id=%s WHERE recipe_id=%s", (dish_id, recipe_id))
        cur.execute(
            "INSERT INTO recipe_sources (recipe_id, source_name, source_url, relevance_score, fetched_at) "
            "VALUES (%s, %s, %s, 0.9500, UTC_TIMESTAMP())",
            (recipe_id, "Cẩm nang Ẩm thực Hà Nội", "https://cookmate.vn/nguon-bun-cha"),
        )
    return {
        "recipe_id": recipe_id,
        "dish_id": dish_id,
        "shared_ing_id": shared_ing_id,
        "shared_ing_name": shared_ing_name,
        "title": title,
    }


def _cleanup_recipe_and_dish(recipe_id: int | None, dish_id: int | None = None) -> None:
    with transaction() as (_, cur):
        if recipe_id is not None:
            cur.execute("DELETE FROM recipes WHERE recipe_id=%s", (recipe_id,))
        if dish_id is not None:
            cur.execute("DELETE FROM dish_ingredients WHERE dish_id=%s", (dish_id,))
            cur.execute("DELETE FROM dishes WHERE dish_id=%s", (dish_id,))


@pytest.fixture(scope="module")
def part1_state(live_server: CookMateServerHarness, db: DbHelper, browser_instance) -> dict[str, Any]:
    """Executes the Part 1 Admin Recipe Review scenario and records outcomes for TC01-TC07."""
    admin = db.create_test_user(prefix="tc01_admin", password="AdminPass#123", role="admin", full_name="Quản Trị Viên")
    member = db.create_test_user(prefix="tc01_member", password="MemberPass#123", role="member", full_name="Tác Giả Món Ngon")

    rec1 = _create_pending_recipe_in_db(db, member["user_id"], title="Bún Chả Hà Nội Chờ Duyệt TC01", with_dish=True)
    rec2 = _create_pending_recipe_in_db(db, member["user_id"], title="Phở Cuốn Ngũ Sắc Chờ Từ Chối TC06")
    state: dict[str, Any] = {}

    try:
        # TC07: Member cannot call admin recipe detail, approve, or reject APIs (403 Forbidden)
        member_client = ApiClient(live_server.base_url)
        assert member_client.login(member["email"], "MemberPass#123").status_code == 200
        state["tc07_get_status"] = member_client.get(f"/api/admin/recipes/{rec1['recipe_id']}").status_code
        state["tc07_approve_status"] = member_client.post(f"/api/admin/recipes/{rec1['recipe_id']}/approve", {}).status_code
        state["tc07_reject_status"] = member_client.post(
            f"/api/admin/recipes/{rec1['recipe_id']}/reject", {"reason": "Hack"}
        ).status_code

        ctx = browser_instance.new_context(viewport={"width": 1280, "height": 840})
        page = ctx.new_page()
        try:
            login_via_ui(page, live_server.base_url, admin["email"], "AdminPass#123", wait_redirect=False)
            page.wait_for_url(re.compile(r"pages/admin/index\.html"), timeout=15000)

            page.goto(f"{live_server.base_url}/pages/admin/approve-recipes.html", wait_until="domcontentloaded")
            expect(page.locator("#pendingRecipesTable")).to_contain_text(rec1["title"], timeout=15000)

            # TC01: Click "Xem chi tiết" on pending recipe rec1 -> navigates to review-recipe.html?id=<id>
            row1 = page.locator("#pendingRecipesTable tr").filter(has_text=rec1["title"]).first
            with page.expect_response(
                lambda r: f"/api/admin/recipes/{rec1['recipe_id']}" in r.url and r.request.method == "GET",
                timeout=15000,
            ) as detail_resp_info:
                row1.locator(".btn-view-detail").click()
            detail_resp = detail_resp_info.value
            detail_json = detail_resp.json()
            preview_modal = page.locator("#previewModal")
            expect(preview_modal).to_be_visible(timeout=10000)

            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "screenshot_6_admin_recipe_review_modal.png"))

            state["tc01_status"] = detail_resp.status
            state["tc01_no_pw_hash"] = "password_hash" not in str(detail_json)
            state["tc01_modal_visible"] = preview_modal.is_visible()

            general_text = preview_modal.locator("#previewSectionGeneral").inner_text()
            state["tc04_general_text"] = general_text
            state["tc04_author_email"] = member["email"]

            ing_text = preview_modal.locator("#previewIngredientsTable").inner_text()
            state["tc02_ing_text"] = ing_text
            state["tc02_shared_ing_name"] = rec1["shared_ing_name"]

            steps_text = preview_modal.locator("#previewSectionSteps").inner_text()
            nut_text = preview_modal.locator("#previewSectionNutrition").inner_text()
            src_text = preview_modal.locator("#previewSectionSources").inner_text()
            state["tc03_steps_text"] = steps_text
            state["tc03_nut_text"] = nut_text
            state["tc03_src_text"] = src_text

            # TC05: Approve directly from the bottom of the detail review page
            preview_modal.locator("#previewApproveBtn").click()
            confirm_ok = page.locator("#confirmOk")
            expect(confirm_ok).to_be_visible(timeout=5000)
            with page.expect_response(
                lambda r: r.url.endswith(f"/api/admin/recipes/{rec1['recipe_id']}/approve"),
                timeout=10000,
            ) as approve_resp:
                confirm_ok.click()
            state["tc05_http_status"] = approve_resp.value.status
            page.wait_for_url(re.compile(r"approve-recipes\.html"), timeout=10000)
            expect(page.locator("#pendingRecipesTable")).not_to_contain_text(rec1["title"])
            db_rec1 = fetch_one("SELECT status, reviewed_by FROM recipes WHERE recipe_id=%s", (rec1["recipe_id"],))
            state["tc05_db_status"] = db_rec1["status"]
            state["tc05_reviewed_by"] = int(db_rec1["reviewed_by"])
            state["admin_id"] = admin["user_id"]

            # TC06: Reject rec2 from the bottom of the detail review page with rejection reason
            row2 = page.locator("#pendingRecipesTable tr").filter(has_text=rec2["title"]).first
            row2.locator(".btn-view-detail").click()
            expect(preview_modal).to_be_visible(timeout=10000)
            expect(preview_modal.locator("#previewSectionGeneral")).to_contain_text(rec2["title"], timeout=10000)
            preview_modal.locator("#previewRejectBtn").click()

            reject_modal = page.locator("#rejectModal")
            expect(reject_modal).to_be_visible(timeout=5000)
            reject_modal.locator("#rejectionReasonText").fill("Hình ảnh minh họa cần rõ nét hơn.")
            with page.expect_response(
                lambda r: r.url.endswith(f"/api/admin/recipes/{rec2['recipe_id']}/reject"),
                timeout=10000,
            ) as reject_resp:
                reject_modal.locator("#confirmRejectBtn").click()
            state["tc06_http_status"] = reject_resp.value.status
            page.wait_for_url(re.compile(r"approve-recipes\.html"), timeout=10000)
            expect(page.locator("#pendingRecipesTable")).not_to_contain_text(rec2["title"])
            db_rec2 = fetch_one(
                "SELECT status, rejection_reason, reviewed_by FROM recipes WHERE recipe_id=%s",
                (rec2["recipe_id"],),
            )
            state["tc06_db_status"] = db_rec2["status"]
            state["tc06_rejection_reason"] = db_rec2["rejection_reason"]
            state["tc06_reviewed_by"] = int(db_rec2["reviewed_by"])
        finally:
            ctx.close()
        yield state
    finally:
        _cleanup_recipe_and_dish(rec1["recipe_id"], rec1["dish_id"])
        _cleanup_recipe_and_dish(rec2["recipe_id"], rec2["dish_id"])


@pytest.fixture(scope="module")
def part2_state(live_server: CookMateServerHarness, db: DbHelper, browser_instance) -> dict[str, Any]:
    """Executes the Part 2 Admin Recipe Delete scenario and records outcomes for TC08-TC14."""
    baseline_total = int(fetch_one("SELECT COUNT(*) AS c FROM recipes")["c"])

    admin = db.create_test_user(prefix="tc08_admin", password="AdminPass#123", role="admin")
    member = db.create_test_user(prefix="tc08_member", password="MemberPass#123", role="member")

    rec_del = _create_pending_recipe_in_db(db, admin["user_id"], title="Món Thử Nghiệm Xóa TC10", with_dish=True)
    with transaction() as (_, cur):
        cur.execute("UPDATE recipes SET status='APPROVED' WHERE recipe_id=%s", (rec_del["recipe_id"],))
    rec_keep = _create_pending_recipe_in_db(
        db,
        admin["user_id"],
        title="Món Giữ Lại Cùng Dish TC12",
        with_dish=False,
        shared_dish_id=rec_del["dish_id"],
    )
    with transaction() as (_, cur):
        cur.execute("UPDATE recipes SET status='APPROVED' WHERE recipe_id=%s", (rec_keep["recipe_id"],))
    state: dict[str, Any] = {}

    try:
        # TC13: Member cannot call DELETE /api/admin/recipes/<id>
        member_client = ApiClient(live_server.base_url)
        assert member_client.login(member["email"], "MemberPass#123").status_code == 200
        res_tc13 = member_client.delete(f"/api/admin/recipes/{rec_del['recipe_id']}")
        state["tc13_status"] = res_tc13.status_code
        state["tc13_still_exists"] = (
            fetch_one("SELECT recipe_id FROM recipes WHERE recipe_id=%s", (rec_del["recipe_id"],)) is not None
        )

        # TC14: Transaction rollback if an error occurs mid-delete
        with patch("backend.database.repositories._recount_categories", side_effect=RuntimeError("Simulated FK failure")):
            with pytest.raises(RuntimeError):
                repo.delete_recipe(rec_del["recipe_id"], admin["user_id"], admin=True)
        state["tc14_recipe_intact"] = (
            fetch_one("SELECT recipe_id FROM recipes WHERE recipe_id=%s", (rec_del["recipe_id"],)) is not None
        )
        state["tc14_ing_count"] = int(
            fetch_one("SELECT COUNT(*) AS c FROM recipe_ingredients WHERE recipe_id=%s", (rec_del["recipe_id"],))["c"]
        )
        state["tc14_step_count"] = int(
            fetch_one("SELECT COUNT(*) AS c FROM recipe_steps WHERE recipe_id=%s", (rec_del["recipe_id"],))["c"]
        )

        ctx = browser_instance.new_context(viewport={"width": 1280, "height": 840})
        page = ctx.new_page()
        try:
            login_via_ui(page, live_server.base_url, admin["email"], "AdminPass#123", wait_redirect=False)
            page.wait_for_url(re.compile(r"pages/admin/index\.html"), timeout=15000)

            page.goto(f"{live_server.base_url}/pages/admin/recipes.html", wait_until="domcontentloaded")
            search_inp = page.locator("#recipeSearchInput")
            expect(search_inp).to_be_visible(timeout=15000)
            search_inp.fill("Món Thử Nghiệm Xóa TC10")

            row = page.locator(f"#admin-recipe-row-{rec_del['recipe_id']}")
            expect(row).to_be_visible(timeout=10000)

            # TC08: Red delete button with trash icon and tooltip "Xóa công thức"
            del_btn = row.locator(".btn-delete-recipe")
            expect(del_btn).to_be_visible()
            state["tc08_btn_visible"] = del_btn.is_visible()
            state["tc08_btn_title"] = del_btn.get_attribute("title")

            # TC09: Click Delete -> Modal opens -> Click "Hủy" -> Row and DB unchanged
            del_btn.click()
            modal = page.locator("#cookmate-modal")
            expect(modal).to_be_visible(timeout=5000)
            state["tc09_modal_text"] = modal.inner_text()
            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "screenshot_7_admin_recipe_delete_modal.png"))
            modal.locator("#cancelDeleteRecipeBtn").click()
            expect(modal).to_have_count(0, timeout=5000)
            state["tc09_row_still_visible"] = row.is_visible()
            state["tc09_db_still_exists"] = (
                fetch_one("SELECT recipe_id FROM recipes WHERE recipe_id=%s", (rec_del["recipe_id"],)) is not None
            )

            # TC10: Click Delete -> Confirm -> Row disappears, count updates, toast shown
            del_btn.click()
            modal = page.locator("#cookmate-modal")
            expect(modal).to_be_visible(timeout=5000)
            with page.expect_response(
                lambda r: r.url.endswith(f"/api/admin/recipes/{rec_del['recipe_id']}") and r.request.method == "DELETE",
                timeout=10000,
            ) as del_resp:
                modal.locator("#confirmDeleteRecipeBtn").click()
            state["tc10_http_status"] = del_resp.value.status
            expect(modal).to_have_count(0, timeout=5000)
            expect(page.locator(f"#admin-recipe-row-{rec_del['recipe_id']}")).to_have_count(0)
            toast_el = page.locator(".toast:visible").first
            expect(toast_el).to_contain_text("Đã xóa công thức thành công")
            state["tc10_toast_text"] = toast_el.inner_text()
            state["tc10_row_count_after"] = page.locator(f"#admin-recipe-row-{rec_del['recipe_id']}").count()
        finally:
            ctx.close()

        # TC11: Deleted recipe and child rows removed from DB and absent from public API
        state["tc11_recipe_in_db"] = fetch_one(
            "SELECT recipe_id FROM recipes WHERE recipe_id=%s", (rec_del["recipe_id"],)
        )
        state["tc11_ing_count"] = int(
            fetch_one("SELECT COUNT(*) AS c FROM recipe_ingredients WHERE recipe_id=%s", (rec_del["recipe_id"],))["c"]
        )
        state["tc11_step_count"] = int(
            fetch_one("SELECT COUNT(*) AS c FROM recipe_steps WHERE recipe_id=%s", (rec_del["recipe_id"],))["c"]
        )
        state["tc11_src_count"] = int(
            fetch_one("SELECT COUNT(*) AS c FROM recipe_sources WHERE recipe_id=%s", (rec_del["recipe_id"],))["c"]
        )
        public_client = ApiClient(live_server.base_url)
        state["tc11_public_detail_status"] = public_client.get(f"/api/recipes/{rec_del['recipe_id']}").status_code
        search_res = public_client.get("/api/recipes?q=Món Thử Nghiệm Xóa TC10").json()
        state["tc11_in_public_search"] = any(
            int(r["id"]) == rec_del["recipe_id"] for r in search_res.get("recipes", [])
        )

        # TC12: Shared catalog ingredient, shared dish, and rec_keep remain intact
        state["tc12_shared_ing_exists"] = (
            fetch_one("SELECT ingredient_id FROM ingredients WHERE ingredient_id=%s", (rec_del["shared_ing_id"],))
            is not None
        )
        state["tc12_shared_dish_exists"] = (
            fetch_one("SELECT dish_id FROM dishes WHERE dish_id=%s", (rec_del["dish_id"],)) is not None
        )
        state["tc12_other_recipe_exists"] = (
            fetch_one("SELECT recipe_id FROM recipes WHERE recipe_id=%s", (rec_keep["recipe_id"],)) is not None
        )
        yield state
    finally:
        _cleanup_recipe_and_dish(rec_del["recipe_id"], None)
        _cleanup_recipe_and_dish(rec_keep["recipe_id"], rec_del["dish_id"])
        assert int(fetch_one("SELECT COUNT(*) AS c FROM recipes")["c"]) == baseline_total


@pytest.fixture(scope="module")
def part3_state(live_server: CookMateServerHarness, db: DbHelper, browser_instance) -> dict[str, Any]:
    """Executes the Part 3 Mandatory Password Change scenario and records outcomes for TC15-TC22."""
    user = db.create_test_user(prefix="tc15_user", password="OriginalPass#123")
    normal_user = db.create_test_user(prefix="tc21_normal", password="NormalPass#123")
    state: dict[str, Any] = {}

    ctx = browser_instance.new_context(viewport={"width": 1280, "height": 820})
    page = ctx.new_page()
    try:
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
        temp_pw = page.locator("#tempPasswordDisplay").input_value()

        # TC15: must_change_password == 1 in MySQL after OTP verification
        user_row = db.get_user_by_id(user["user_id"])
        state["tc15_flag_in_db"] = int(user_row["must_change_password"])

        page.locator("#forgotSuccessBackToLoginBtn").click()
        wait_for_login_page_ready(page)
        page.locator("#loginEmail").fill(user["email"])
        page.locator("#loginPassword").fill(temp_pw)

        with page.expect_response(lambda r: r.url.endswith("/api/auth/login"), timeout=10000) as login_resp_info:
            page.locator("#loginSubmitBtn").click()
        login_json = login_resp_info.value.json()
        state["tc16_login_flag"] = login_json["user"]["must_change_password"]

        # TC16: Mandatory Password Change overlay opens
        overlay = page.locator("#mandatoryPasswordChangeOverlay")
        expect(overlay).to_be_visible(timeout=10000)
        if ARTIFACT_DIR.exists():
            page.screenshot(path=str(ARTIFACT_DIR / "screenshot_8_mandatory_password_change.png"))
        state["tc16_overlay_visible"] = overlay.is_visible()
        state["tc16_overlay_text"] = overlay.inner_text()
        state["tc16_close_btn_count"] = overlay.locator(".modal__close, #modalCloseBtn").count()

        # TC17: Reload or direct navigation still forces mandatory password change screen
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#mandatoryPasswordChangeOverlay")).to_be_visible(timeout=10000)
        state["tc17_after_reload"] = page.locator("#mandatoryPasswordChangeOverlay").is_visible()

        page.goto(f"{live_server.base_url}/index.html", wait_until="domcontentloaded")
        expect(page.locator("#mandatoryPasswordChangeOverlay")).to_be_visible(timeout=10000)
        state["tc17_on_index"] = page.locator("#mandatoryPasswordChangeOverlay").is_visible()

        page.goto(f"{live_server.base_url}/pages/account/profile.html", wait_until="domcontentloaded")
        expect(page.locator("#mandatoryPasswordChangeOverlay")).to_be_visible(timeout=10000)
        state["tc17_on_profile"] = page.locator("#mandatoryPasswordChangeOverlay").is_visible()

        # TC18: Business APIs blocked with 403 while must_change_password == 1
        state["tc18_api"] = page.evaluate(
            """async () => {
                const csrfRes = await fetch('/api/auth/csrf', { credentials: 'include' });
                const { csrfToken } = await csrfRes.json();
                const headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken };
                const r1 = await fetch('/api/recipes/my', { credentials: 'include' });
                const r2 = await fetch('/api/favorites', { credentials: 'include' });
                const r3 = await fetch('/api/users/profile', {
                    method: 'PUT',
                    credentials: 'include',
                    headers,
                    body: JSON.stringify({ name: 'Blocked Update' })
                });
                const r4 = await fetch('/api/auth/me', { credentials: 'include' });
                return {
                    myRecipes: r1.status,
                    favorites: r2.status,
                    updateProfile: r3.status,
                    authMe: r4.status,
                    r1Body: await r1.json()
                };
            }"""
        )

        # TC19: Submit valid new password -> must_change_password becomes 0
        new_personal_pw = "MyBrandNewPass#2026"
        overlay = page.locator("#mandatoryPasswordChangeOverlay")
        overlay.locator("#forceNewPassword").fill(new_personal_pw)
        overlay.locator("#forceConfirmPassword").fill(new_personal_pw)
        with page.expect_response(
            lambda r: r.url.endswith("/api/auth/force-change-password"),
            timeout=10000,
        ) as force_resp_info:
            overlay.locator("#forceChangePasswordSubmitBtn").click()
        state["tc19_http_status"] = force_resp_info.value.status

        # TC20: Redirected to index.html, normal access restored, must_change_password == 0
        page.wait_for_url(re.compile(r"(index\.html|/)$"), timeout=15000)
        wait_for_app_ready(page, authenticated=True)
        state["tc20_overlay_count"] = page.locator("#mandatoryPasswordChangeOverlay").count()
        user_row_after = db.get_user_by_id(user["user_id"])
        state["tc19_flag_after"] = int(user_row_after["must_change_password"])
        state["tc19_hash_matches"] = check_password_hash(user_row_after["password_hash"], new_personal_pw)
        state["tc20_my_recipes_status"] = page.evaluate(
            "async () => (await fetch('/api/recipes/my', { credentials: 'include' })).status"
        )

        # TC22: Avatar dropdown regular Change Password works and keeps must_change_password == 0
        modal = open_change_password_modal(page)
        cur_inp, new_inp, conf_inp = get_change_password_inputs(modal)
        second_pw = "SecondRegularPass#2026"
        cur_inp.fill(new_personal_pw)
        new_inp.fill(second_pw)
        conf_inp.fill(second_pw)
        modal.get_by_role("button", name="Cập nhật mật khẩu").click()
        expect(modal).to_be_hidden(timeout=10000)

        user_row_tc22 = db.get_user_by_id(user["user_id"])
        state["tc22_flag_after"] = int(user_row_tc22["must_change_password"])
        state["tc22_hash_matches"] = check_password_hash(user_row_tc22["password_hash"], second_pw)
    finally:
        ctx.close()

    # TC21: Normal user (must_change_password == 0) logs in normally without mandatory screen
    ctx2 = browser_instance.new_context(viewport={"width": 1280, "height": 820})
    page2 = ctx2.new_page()
    try:
        login_via_ui(page2, live_server.base_url, normal_user["email"], "NormalPass#123")
        state["tc21_overlay_count"] = page2.locator("#mandatoryPasswordChangeOverlay").count()
        state["tc21_avatar_visible"] = page2.locator("#userMenuTrigger").is_visible()
    finally:
        ctx2.close()

    return state


# ===========================================================================
# 5.1. Duyệt công thức (TC01 - TC07)
# ===========================================================================

def test_tc01_admin_clicks_view_opens_full_detail_modal(part1_state: dict[str, Any]) -> None:
    """TC01: Admin nhấn 'Xem' ở công thức chờ duyệt -> Mở modal đầy đủ thông tin công thức."""
    assert part1_state["tc01_status"] == 200
    assert part1_state["tc01_no_pw_hash"] is True
    assert part1_state["tc01_modal_visible"] is True


def test_tc02_ingredients_table_displays_full_list_and_amounts(part1_state: dict[str, Any]) -> None:
    """TC02: Kiểm tra danh sách nguyên liệu -> Hiển thị đầy đủ nguyên liệu và định lượng."""
    ing_text = part1_state["tc02_ing_text"]
    assert part1_state["tc02_shared_ing_name"] in ing_text
    assert "500" in ing_text
    assert "Thái lát mỏng vừa ăn" in ing_text
    assert "Nguyên liệu chính" in ing_text
    assert "Nước mắm nhĩ Phú Quốc" in ing_text
    assert "muỗng canh" in ing_text


def test_tc03_cooking_steps_nutrition_and_sources_displayed_in_order(part1_state: dict[str, Any]) -> None:
    """TC03: Kiểm tra các bước chế biến -> Hiển thị đúng thứ tự step_number, tiêu đề, hướng dẫn."""
    steps_text = part1_state["tc03_steps_text"]
    pos1 = steps_text.find("Bước 1: Ướp thịt nướng")
    pos2 = steps_text.find("Bước 2: Nướng chả trên than hoa")
    assert pos1 != -1 and pos2 != -1 and pos1 < pos2
    assert "Thêm chút mật ong" in steps_text
    assert "540 kcal" in part1_state["tc03_nut_text"]
    assert "ước tính" in part1_state["tc03_nut_text"]
    assert "Cẩm nang Ẩm thực Hà Nội" in part1_state["tc03_src_text"]


def test_tc04_general_info_author_category_times_and_servings(part1_state: dict[str, Any]) -> None:
    """TC04: Kiểm tra thông tin tác giả, danh mục, thời gian, khẩu phần -> Hiển thị chính xác."""
    gen_text = part1_state["tc04_general_text"]
    assert "Tác Giả Món Ngon" in gen_text
    assert part1_state["tc04_author_email"] in gen_text
    assert "20 phút" in gen_text
    assert "25 phút" in gen_text
    assert "45 phút" in gen_text
    assert "4 người" in gen_text
    assert "Cuối tuần" in gen_text


def test_tc05_approve_from_detail_modal_updates_status_to_approved(part1_state: dict[str, Any]) -> None:
    """TC05: Duyệt ngay trong modal chi tiết -> Trạng thái chuyển sang APPROVED."""
    assert part1_state["tc05_http_status"] == 200
    assert part1_state["tc05_db_status"] == "APPROVED"
    assert part1_state["tc05_reviewed_by"] == part1_state["admin_id"]


def test_tc06_reject_from_detail_modal_updates_status_to_rejected(part1_state: dict[str, Any]) -> None:
    """TC06: Từ chối trong modal chi tiết -> Trạng thái chuyển sang REJECTED."""
    assert part1_state["tc06_http_status"] == 200
    assert part1_state["tc06_db_status"] == "REJECTED"
    assert "rõ nét" in part1_state["tc06_rejection_reason"]
    assert part1_state["tc06_reviewed_by"] == part1_state["admin_id"]


def test_tc07_member_cannot_call_admin_recipe_review_apis(part1_state: dict[str, Any]) -> None:
    """TC07: Member gọi API chi tiết công thức admin -> Trả về 403."""
    assert part1_state["tc07_get_status"] == 403
    assert part1_state["tc07_approve_status"] == 403
    assert part1_state["tc07_reject_status"] == 403


# ===========================================================================
# 5.2. Xóa công thức (TC08 - TC14)
# ===========================================================================

def test_tc08_admin_sees_delete_button_in_recipes_management(part2_state: dict[str, Any]) -> None:
    """TC08: Admin mở trang Quản lý công thức -> Mỗi công thức có nút Xóa."""
    assert part2_state["tc08_btn_visible"] is True
    assert part2_state["tc08_btn_title"] == "Xóa công thức"


def test_tc09_click_delete_then_cancel_keeps_recipe_intact(part2_state: dict[str, Any]) -> None:
    """TC09: Nhấn Xóa rồi nhấn Hủy -> Công thức không bị xóa."""
    assert "Xác nhận xóa công thức" in part2_state["tc09_modal_text"]
    assert part2_state["tc09_row_still_visible"] is True
    assert part2_state["tc09_db_still_exists"] is True


def test_tc10_click_delete_then_confirm_removes_row_and_shows_toast(part2_state: dict[str, Any]) -> None:
    """TC10: Nhấn Xóa rồi xác nhận -> Công thức biến mất khỏi danh sách."""
    assert part2_state["tc10_http_status"] == 200
    assert part2_state["tc10_row_count_after"] == 0
    assert "Đã xóa công thức thành công" in part2_state["tc10_toast_text"]


def test_tc11_deleted_recipe_absent_from_public_search_and_detail(part2_state: dict[str, Any]) -> None:
    """TC11: Kiểm tra trang công thức công khai sau khi xóa -> Công thức đã xóa không còn xuất hiện."""
    assert part2_state["tc11_recipe_in_db"] is None
    assert part2_state["tc11_ing_count"] == 0
    assert part2_state["tc11_step_count"] == 0
    assert part2_state["tc11_src_count"] == 0
    assert part2_state["tc11_public_detail_status"] == 404
    assert part2_state["tc11_in_public_search"] is False


def test_tc12_shared_ingredients_and_shared_dishes_preserved(part2_state: dict[str, Any]) -> None:
    """TC12: Kiểm tra nguyên liệu dùng chung sau khi xóa công thức -> Bảng ingredients không mất dữ liệu dùng chung."""
    assert part2_state["tc12_shared_ing_exists"] is True
    assert part2_state["tc12_shared_dish_exists"] is True
    assert part2_state["tc12_other_recipe_exists"] is True


def test_tc13_member_cannot_call_admin_delete_recipe_api(part2_state: dict[str, Any]) -> None:
    """TC13: Member gọi API xóa công thức admin -> Trả về 403."""
    assert part2_state["tc13_status"] == 403
    assert part2_state["tc13_still_exists"] is True


def test_tc14_transaction_rollback_when_delete_fails_midway(part2_state: dict[str, Any]) -> None:
    """TC14: Xóa công thức có dữ liệu phụ thuộc -> Không lỗi khóa ngoại, transaction rollback an toàn nếu có lỗi."""
    assert part2_state["tc14_recipe_intact"] is True
    assert part2_state["tc14_ing_count"] == 2
    assert part2_state["tc14_step_count"] == 2


# ===========================================================================
# 5.3. Bắt buộc đổi mật khẩu sau OTP (TC15 - TC22)
# ===========================================================================

def test_tc15_otp_recovery_sets_must_change_password_flag_to_1(part3_state: dict[str, Any]) -> None:
    """TC15: Khôi phục mật khẩu bằng OTP thành công -> must_change_password = 1."""
    assert part3_state["tc15_flag_in_db"] == 1


def test_tc16_login_with_temp_password_opens_mandatory_password_change_screen(part3_state: dict[str, Any]) -> None:
    """TC16: Đăng nhập bằng mật khẩu tạm -> Hiện màn hình bắt buộc đổi mật khẩu."""
    assert part3_state["tc16_login_flag"] is True
    assert part3_state["tc16_overlay_visible"] is True
    assert "Đổi mật khẩu để tiếp tục" in part3_state["tc16_overlay_text"]
    assert part3_state["tc16_close_btn_count"] == 0


def test_tc17_reload_or_direct_url_cannot_bypass_mandatory_password_change(part3_state: dict[str, Any]) -> None:
    """TC17: Reload trang hoặc đổi URL khi chưa đổi mật khẩu -> Vẫn bị yêu cầu đổi mật khẩu."""
    assert part3_state["tc17_after_reload"] is True
    assert part3_state["tc17_on_index"] is True
    assert part3_state["tc17_on_profile"] is True


def test_tc18_business_apis_blocked_with_403_until_password_changed(part3_state: dict[str, Any]) -> None:
    """TC18: Gọi API chức năng khác khi must_change_password = 1 -> Bị chặn với 403."""
    api = part3_state["tc18_api"]
    assert api["myRecipes"] == 403
    assert api["favorites"] == 403
    assert api["updateProfile"] == 403
    assert api["r1Body"]["must_change_password"] is True
    assert api["authMe"] == 200


def test_tc19_valid_forced_password_change_resets_flag_to_0(part3_state: dict[str, Any]) -> None:
    """TC19: Đổi mật khẩu mới hợp lệ -> must_change_password = 0."""
    assert part3_state["tc19_http_status"] == 200
    assert part3_state["tc19_flag_after"] == 0
    assert part3_state["tc19_hash_matches"] is True


def test_tc20_after_forced_password_change_user_accesses_system_normally(part3_state: dict[str, Any]) -> None:
    """TC20: Sau khi đổi mật khẩu bắt buộc thành công -> Vào hệ thống bình thường."""
    assert part3_state["tc20_overlay_count"] == 0
    assert part3_state["tc20_my_recipes_status"] == 200


def test_tc21_normal_user_login_is_not_asked_to_force_change_password(part3_state: dict[str, Any]) -> None:
    """TC21: Đăng nhập tài khoản bình thường không qua OTP -> Không bị bắt đổi mật khẩu."""
    assert part3_state["tc21_overlay_count"] == 0
    assert part3_state["tc21_avatar_visible"] is True


def test_tc22_avatar_dropdown_change_password_still_works(part3_state: dict[str, Any]) -> None:
    """TC22: Đổi mật khẩu trong menu avatar -> Vẫn hoạt động bình thường."""
    assert part3_state["tc22_flag_after"] == 0
    assert part3_state["tc22_hash_matches"] is True
