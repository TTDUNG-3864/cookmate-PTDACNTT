"""End-to-end API, MySQL, and Playwright tests for the 6 features of:
COOKMATE – COMPLETE RECIPE SUBMISSION & ADMIN MODERATION WORKFLOW
1. Device Image Upload & Mutual Exclusion with Image URL
2. Simplified Step 5 on Member & Admin Recipe Forms
3. Mandatory Valid Image (No Automatic Default/Fallback Image on New Recipes)
4. 7-Hour Timezone Offset Fix (UTC ISO-8601 'Z' Serialization & Asia/Ho_Chi_Minh Display)
5. Redesigned Recipe Review Workflow with Dedicated Detail Page (/pages/admin/review-recipe.html)
6. Separation of Pending Recipes from Recipe Management (/pages/admin/recipes.html)
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import sync_playwright, expect

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "e2e"))

from backend.database.connection import fetch_all, fetch_one, transaction
from backend.database.schema_upgrade import ensure_runtime_schema
from helpers.browser_helper import launch_browser, login_via_ui
from helpers.db_helper import DbHelper
from helpers.http_client import ApiClient
from helpers.server_harness import CookMateServerHarness

ARTIFACT_DIR = Path(
    os.environ.get(
        "COOKMATE_ARTIFACT_DIR",
        r"C:\Users\TTD\.gemini\antigravity\brain\a94eb504-24b6-4a8f-bf52-92094aecae4e",
    )
)

# Minimal valid 1x1 PNG image bytes
VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
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


def _cleanup_created_recipes(recipe_ids: list[int], uploaded_paths: list[str]) -> None:
    if recipe_ids:
        with transaction() as (_, cur):
            for rid in recipe_ids:
                cur.execute("DELETE FROM recipe_ingredients WHERE recipe_id=%s", (rid,))
                cur.execute("DELETE FROM recipe_steps WHERE recipe_id=%s", (rid,))
                cur.execute("DELETE FROM recipe_sources WHERE recipe_id=%s", (rid,))
                cur.execute("DELETE FROM recipes WHERE recipe_id=%s", (rid,))
    for rel_path in uploaded_paths:
        if rel_path and rel_path.startswith("static/uploads/recipes/"):
            full_path = PROJECT_ROOT / rel_path
            if full_path.is_file():
                try:
                    full_path.unlink()
                except OSError:
                    pass


@pytest.fixture(scope="module")
def workflow_state(live_server: CookMateServerHarness, db: DbHelper, browser_instance) -> dict[str, Any]:
    """Executes all 5 mandatory test groups (Section VIII) end-to-end against MySQL + Flask + Playwright."""
    baseline_recipes = fetch_all("SELECT recipe_id, created_at FROM recipes ORDER BY recipe_id ASC")
    baseline_count = len(baseline_recipes)
    baseline_map = {int(r["recipe_id"]): str(r["created_at"]) for r in baseline_recipes}

    member = db.create_test_user(prefix="wf_member", password="MemberPass#123", role="member", full_name="Đầu Bếp Thành Viên")
    admin = db.create_test_user(prefix="wf_admin", password="AdminPass#123", role="admin", full_name="Quản Trị Viên")

    created_recipe_ids: list[int] = []
    uploaded_paths: list[str] = []
    state: dict[str, Any] = {
        "baseline_count": baseline_count,
    }

    tmp_dir = ARTIFACT_DIR / "scratch" / "recipe_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    valid_png_file = tmp_dir / "bun_bo_hue.png"
    valid_png_file.write_bytes(VALID_PNG_BYTES)

    bad_exe_file = tmp_dir / "malware.exe"
    bad_exe_file.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00fake-executable")

    try:
        # -------------------------------------------------------------------
        # 1. API-level Upload & Image Validation Tests (Feature 1 & Feature 3)
        # -------------------------------------------------------------------
        member_api = ApiClient(live_server.base_url)
        assert member_api.login(member["email"], "MemberPass#123").status_code == 200
        member_api.ensure_csrf()

        admin_api = ApiClient(live_server.base_url)
        assert admin_api.login(admin["email"], "AdminPass#123").status_code == 200
        admin_api.ensure_csrf()

        base_payload = {
            "title": "Món Thiếu Ảnh Không Được Tạo",
            "description": "Kiểm tra từ chối khi thiếu ảnh",
            "categoryId": 1,
            "servings": 4,
            "prepTime": 15,
            "cookTime": 25,
            "difficulty": "Dễ",
            "ingredients": [{"name": "Thịt bò", "amount": 300, "unit": "g"}],
            "steps": [{"step": 1, "description": "Xào thịt bò trên lửa lớn."}],
        }

        # 1a. Missing image rejected for BOTH Member and Admin (400 RECIPE_IMAGE_REQUIRED)
        res_missing_member = member_api.post("/api/recipes", {**base_payload, "image": "", "image_url": ""})
        state["missing_img_member_status"] = res_missing_member.status_code
        state["missing_img_member_json"] = res_missing_member.json()

        res_missing_admin = admin_api.post("/api/recipes", {**base_payload, "image": ""})
        state["missing_img_admin_status"] = res_missing_admin.status_code
        state["missing_img_admin_json"] = res_missing_admin.json()

        # 1b. Default/fallback SVG category image rejected (no automatic default image allowed!)
        res_fallback_svg = member_api.post(
            "/api/recipes",
            {**base_payload, "image": "../../assets/images/categories/mon-chinh.svg"},
        )
        state["fallback_svg_status"] = res_fallback_svg.status_code
        state["fallback_svg_error"] = res_fallback_svg.json().get("error")

        # 1c. Invalid URL format rejected (400 RECIPE_IMAGE_INVALID_URL)
        res_bad_url = member_api.post("/api/recipes", {**base_payload, "image_url": "not-a-valid-url"})
        state["bad_url_status"] = res_bad_url.status_code
        state["bad_url_error"] = res_bad_url.json().get("error")

        # 1d. Invalid file format (.exe and fake .png) rejected via multipart/form-data
        multipart_headers = {
            "Origin": live_server.base_url,
            "X-CSRF-Token": member_api.csrf_token,
        }
        res_exe = member_api.session.post(
            f"{live_server.base_url}/api/recipes",
            data={"payload": json.dumps(base_payload)},
            files={"image_file": ("exploit.exe", b"MZ\x90\x00executable", "application/octet-stream")},
            headers=multipart_headers,
            timeout=10.0,
        )
        state["bad_exe_status"] = res_exe.status_code
        state["bad_exe_error"] = res_exe.json().get("error")

        res_fake_png = member_api.session.post(
            f"{live_server.base_url}/api/recipes",
            data={"payload": json.dumps(base_payload)},
            files={"image_file": ("fake.png", b"not-a-real-png-header", "image/png")},
            headers=multipart_headers,
            timeout=10.0,
        )
        state["fake_png_status"] = res_fake_png.status_code
        state["fake_png_error"] = res_fake_png.json().get("error")

        # 1e. File > 5 MB rejected (400 RECIPE_IMAGE_TOO_LARGE)
        oversized_bytes = VALID_PNG_BYTES + (b"\x00" * (5 * 1024 * 1024 + 64))
        res_oversized = member_api.session.post(
            f"{live_server.base_url}/api/recipes",
            data={"payload": json.dumps(base_payload)},
            files={"image_file": ("huge.png", oversized_bytes, "image/png")},
            headers=multipart_headers,
            timeout=15.0,
        )
        state["oversized_status"] = res_oversized.status_code
        state["oversized_error"] = res_oversized.json().get("error")

        # 1f. Simultaneous file upload AND non-empty URL rejected (400 RECIPE_IMAGE_CONFLICT)
        res_conflict = member_api.session.post(
            f"{live_server.base_url}/api/recipes",
            data={
                "payload": json.dumps(
                    {**base_payload, "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=800"}
                )
            },
            files={"image_file": ("valid.png", VALID_PNG_BYTES, "image/png")},
            headers=multipart_headers,
            timeout=10.0,
        )
        state["conflict_status"] = res_conflict.status_code
        state["conflict_error"] = res_conflict.json().get("error")

        # Verify zero records were created in DB by any of the rejected requests above!
        state["count_after_rejections"] = int(fetch_one("SELECT COUNT(*) AS c FROM recipes")["c"])

        # -------------------------------------------------------------------
        # 2. Browser UI: Member Form (Upload File, Mutual Exclusion, Step 5, Submit)
        # -------------------------------------------------------------------
        ctx_member = browser_instance.new_context(viewport={"width": 1280, "height": 860})
        page_m = ctx_member.new_page()
        try:
            login_via_ui(page_m, live_server.base_url, member["email"], "MemberPass#123")
            page_m.goto(f"{live_server.base_url}/pages/account/recipe-form.html", wait_until="domcontentloaded")
            expect(page_m.locator("#ingredientsList .ingredient-row").first).to_be_visible(timeout=15000)

            # Check Step 5 simplified UI for Member
            state["member_step5_notice_count"] = page_m.locator(".recipe-submit-notice").count()
            state["member_submit_btn_text"] = page_m.locator("#submitRecipeBtn").inner_text().strip()
            state["member_cancel_btn_text"] = page_m.locator("#cancelRecipeBtn").inner_text().strip()

            # Test mutual exclusion in UI:
            # First type a valid local image URL -> preview becomes visible
            local_img_url = f"{live_server.base_url}/favicon.ico"
            url_input = page_m.locator("#recipeImage")
            url_input.fill(local_img_url)
            expect(page_m.locator("#imagePreview")).to_be_visible()

            # Now select a file from device -> URL input is automatically cleared, file info & preview shown
            page_m.locator("#recipeImageFile").set_input_files(str(valid_png_file))
            state["url_after_file_select"] = url_input.input_value()
            expect(page_m.locator("#selectedFileInfo")).to_be_visible()
            state["selected_file_name"] = page_m.locator("#selectedFileName").inner_text().strip()
            state["selected_file_size"] = page_m.locator("#selectedFileSize").inner_text().strip()
            state["preview_visible_after_file"] = page_m.locator("#imagePreview").is_visible()

            # Type URL again -> selected file is automatically cleared
            url_input.fill(local_img_url)
            state["file_info_visible_after_url"] = page_m.locator("#selectedFileInfo").is_visible()

            # Now re-select the file to test full device upload submission
            page_m.locator("#recipeImageFile").set_input_files(str(valid_png_file))
            assert url_input.input_value() == ""

            if ARTIFACT_DIR.exists():
                page_m.locator("#uploadImageMethodBox").scroll_into_view_if_needed()
                page_m.screenshot(path=str(ARTIFACT_DIR / "screenshot_9_recipe_form_image_upload.png"))

            # Fill recipe fields & submit as Member
            upload_recipe_title = "Bún Bò Huế Tải Ảnh Thiết Bị WF01"
            page_m.locator("#recipeName").fill(upload_recipe_title)
            page_m.locator("#recipeDesc").fill("Nước dùng đậm đà hương sả ruốc Huế.")
            page_m.locator("#recipeCategory").select_option(index=1)
            page_m.locator("#recipePrepTime").fill("25")
            page_m.locator("#recipeCookTime").fill("45")
            page_m.locator("#recipeServings").fill("4")

            ing_row = page_m.locator("#ingredientsList .ingredient-row").first
            ing_row.locator(".ingredient-name").fill("Bún sợi to")
            ing_row.locator(".ingredient-amount").fill("500")
            ing_row.locator(".ingredient-unit").fill("g")

            step_row = page_m.locator("#stepsList .step-row").first
            step_row.locator(".step-desc").fill("Hầm xương bò với sả cây trong 45 phút.")

            with page_m.expect_response(
                lambda r: r.url.endswith("/api/recipes") and r.request.method == "POST",
                timeout=15000,
            ) as create_resp_info:
                page_m.locator("#submitRecipeBtn").click()
            create_resp = create_resp_info.value
            assert create_resp.status == 201
            created_rec1 = create_resp.json()["recipe"]
            rec1_id = int(created_rec1["id"])
            created_recipe_ids.append(rec1_id)
            uploaded_paths.append(created_rec1["image"])

            state["rec1_id"] = rec1_id
            state["rec1_image"] = created_rec1["image"]
            state["rec1_status"] = created_rec1["status"]
            state["rec1_created_at_iso"] = created_rec1["createdAt"]

            # Verify the uploaded file exists on disk with a UUID filename (not "bun_bo_hue.png")
            state["rec1_file_exists"] = (PROJECT_ROOT / created_rec1["image"]).is_file()
            state["rec1_http_serve_status"] = member_api.get("/" + created_rec1["image"]).status_code

            # Also create a 2nd pending recipe via URL method to test Rejection flow
            res_rec2 = member_api.post(
                "/api/recipes",
                {
                    **base_payload,
                    "title": "Gỏi Cuốn Tôm Thịt URL WF02",
                    "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=800",
                },
            )
            assert res_rec2.status_code == 201
            rec2_data = res_rec2.json()["recipe"]
            rec2_id = int(rec2_data["id"])
            created_recipe_ids.append(rec2_id)
            state["rec2_id"] = rec2_id
            state["rec2_image"] = rec2_data["image"]
        finally:
            ctx_member.close()

        # -------------------------------------------------------------------
        # 3. Browser UI: Admin Recipe Form Step 5, Pending Queue, Dedicated Review Page, and Recipe Management Separation
        # -------------------------------------------------------------------
        ctx_admin = browser_instance.new_context(viewport={"width": 1280, "height": 860})
        page_a = ctx_admin.new_page()
        try:
            login_via_ui(page_a, live_server.base_url, admin["email"], "AdminPass#123", wait_redirect=False)
            page_a.wait_for_url(re.compile(r"pages/admin/index\.html"), timeout=15000)

            # 3a. Check Admin Recipe Form Step 5 simplified UI
            page_a.goto(f"{live_server.base_url}/pages/admin/recipe-form.html", wait_until="domcontentloaded")
            expect(page_a.locator("#adminRecipeName")).to_be_visible(timeout=15000)
            state["admin_step5_notice_count"] = page_a.locator(".recipe-submit-notice").count()
            state["admin_submit_btn_text"] = page_a.locator("#saveRecipeBtn").inner_text().strip()
            state["admin_cancel_btn_text"] = page_a.locator("#cancelAdminRecipeBtn").inner_text().strip()

            # 3b. Check Feature 6 BEFORE approval:
            # GET /api/admin/recipes must NOT contain any pending recipes (filtered in SQL)
            admin_recipes_api_res = admin_api.get("/api/admin/recipes").json()
            state["api_admin_recipes_has_pending"] = any(
                str(r.get("status", "")).lower() == "pending" for r in admin_recipes_api_res.get("recipes", [])
            )
            state["api_admin_recipes_contains_rec1_before_approve"] = any(
                int(r["id"]) == rec1_id for r in admin_recipes_api_res.get("recipes", [])
            )

            # Open /pages/admin/recipes.html and verify pending recipes do NOT appear and status filter has no 'pending'
            page_a.goto(f"{live_server.base_url}/pages/admin/recipes.html", wait_until="domcontentloaded")
            expect(page_a.locator("#recipeSearchInput")).to_be_visible(timeout=15000)
            state["mgmt_status_filter_options"] = page_a.locator("#statusFilter option").all_inner_texts()
            page_a.locator("#recipeSearchInput").fill(upload_recipe_title)
            state["mgmt_has_pending_rec1_in_ui"] = (
                page_a.locator(f"#admin-recipe-row-{rec1_id}").count() > 0
            )

            # 3c. Open /pages/admin/approve-recipes.html (Pending Queue)
            page_a.goto(f"{live_server.base_url}/pages/admin/approve-recipes.html", wait_until="domcontentloaded")
            row_rec1 = page_a.locator(f"#pending-recipe-row-{rec1_id}")
            expect(row_rec1).to_be_visible(timeout=15000)

            if ARTIFACT_DIR.exists():
                page_a.screenshot(path=str(ARTIFACT_DIR / "screenshot_10_approve_queue_no_direct_buttons.png"))

            # Verify Feature 4 (Timezone): newly submitted recipe shows "Vừa xong" (NOT "7 giờ trước")
            row1_text = row_rec1.inner_text()
            state["queue_row1_text"] = row1_text

            # Verify Feature 5: Pending table row has ONLY "Xem chi tiết" and NO "Duyệt" or "Từ chối" buttons
            state["queue_row1_approve_btn_count"] = row_rec1.get_by_role("button", name=re.compile(r"Duyệt", re.I)).count()
            state["queue_row1_reject_btn_count"] = row_rec1.get_by_role("button", name=re.compile(r"Từ chối", re.I)).count()
            view_detail_link = row_rec1.locator(".btn-view-detail")
            state["queue_row1_view_detail_text"] = view_detail_link.inner_text().strip()

            # Click "Xem chi tiết" -> Navigates to dedicated page /pages/admin/review-recipe.html?id=<rec1_id>
            with page_a.expect_response(
                lambda r: f"/api/admin/recipes/{rec1_id}/review" in r.url and r.request.method == "GET",
                timeout=15000,
            ) as review_api_info:
                view_detail_link.click()
            page_a.wait_for_url(re.compile(rf"pages/admin/review-recipe\.html\?id={rec1_id}"), timeout=15000)
            state["review_api_status"] = review_api_info.value.status
            state["review_page_url"] = page_a.url

            expect(page_a.locator("#previewSectionGeneral")).to_contain_text(upload_recipe_title, timeout=10000)
            if ARTIFACT_DIR.exists():
                page_a.screenshot(path=str(ARTIFACT_DIR / "screenshot_11_dedicated_review_recipe_page.png"))

            state["review_general_text"] = page_a.locator("#previewSectionGeneral").inner_text()
            state["review_ing_text"] = page_a.locator("#previewIngredientsTable").inner_text()
            state["review_steps_text"] = page_a.locator("#previewSectionSteps").inner_text()
            state["review_nutrition_text"] = page_a.locator("#previewSectionNutrition").inner_text()
            state["review_footer_visible"] = page_a.locator("#reviewActionFooter").is_visible()

            # Approve rec1 at the bottom of review-recipe.html
            page_a.locator("#previewApproveBtn").click()
            confirm_ok = page_a.locator("#confirmOk")
            expect(confirm_ok).to_be_visible(timeout=5000)
            with page_a.expect_response(
                lambda r: r.url.endswith(f"/api/admin/recipes/{rec1_id}/approve"),
                timeout=10000,
            ) as approve_resp_info:
                confirm_ok.click()
            state["approve_http_status"] = approve_resp_info.value.status

            # Returns to approve-recipes.html and rec1 is no longer in pending queue
            page_a.wait_for_url(re.compile(r"pages/admin/approve-recipes\.html"), timeout=15000)
            expect(page_a.locator(f"#pending-recipe-row-{rec1_id}")).to_have_count(0)
            state["rec1_db_status_after_approve"] = fetch_one(
                "SELECT status FROM recipes WHERE recipe_id=%s", (rec1_id,)
            )["status"]

            # Now review and reject rec2 on dedicated review-recipe.html
            row_rec2 = page_a.locator(f"#pending-recipe-row-{rec2_id}")
            expect(row_rec2).to_be_visible(timeout=10000)
            row_rec2.locator(".btn-view-detail").click()
            page_a.wait_for_url(re.compile(rf"pages/admin/review-recipe\.html\?id={rec2_id}"), timeout=15000)
            expect(page_a.locator("#previewSectionGeneral")).to_contain_text("Gỏi Cuốn Tôm Thịt URL WF02", timeout=10000)

            page_a.locator("#previewRejectBtn").click()
            reject_modal = page_a.locator("#rejectModal")
            expect(reject_modal).to_be_visible(timeout=5000)
            reject_modal.locator("#rejectionReasonText").fill("Cần bổ sung chi tiết cách pha nước chấm.")
            with page_a.expect_response(
                lambda r: r.url.endswith(f"/api/admin/recipes/{rec2_id}/reject"),
                timeout=10000,
            ) as reject_resp_info:
                reject_modal.locator("#confirmRejectBtn").click()
            state["reject_http_status"] = reject_resp_info.value.status
            page_a.wait_for_url(re.compile(r"pages/admin/approve-recipes\.html"), timeout=15000)
            expect(page_a.locator(f"#pending-recipe-row-{rec2_id}")).to_have_count(0)

            rec2_db = fetch_one("SELECT status, rejection_reason FROM recipes WHERE recipe_id=%s", (rec2_id,))
            state["rec2_db_status_after_reject"] = rec2_db["status"]
            state["rec2_db_reason_after_reject"] = rec2_db["rejection_reason"]

            # Verify Feature 6 AFTER approval/rejection on /pages/admin/recipes.html:
            # Approved rec1 and Rejected rec2 appear in Recipe Management, while Pending never appears;
            # Public API shows rec1 (APPROVED) and hides rec2 (REJECTED).
            page_a.goto(f"{live_server.base_url}/pages/admin/recipes.html", wait_until="domcontentloaded")
            expect(page_a.locator("#recipeSearchInput")).to_be_visible(timeout=15000)

            page_a.locator("#recipeSearchInput").fill(upload_recipe_title)
            expect(page_a.locator(f"#admin-recipe-row-{rec1_id}")).to_be_visible(timeout=10000)
            state["mgmt_has_approved_rec1_after"] = page_a.locator(f"#admin-recipe-row-{rec1_id}").is_visible()
            state["mgmt_count_ matches_filtered_rec1"] = int(page_a.locator("#totalRecipesCount").inner_text()) == 1

            page_a.locator("#recipeSearchInput").fill("Gỏi Cuốn Tôm Thịt URL WF02")
            expect(page_a.locator(f"#admin-recipe-row-{rec2_id}")).to_be_visible(timeout=10000)
            state["mgmt_has_rejected_rec2_after"] = page_a.locator(f"#admin-recipe-row-{rec2_id}").is_visible()

            public_api = ApiClient(live_server.base_url)
            state["public_rec1_status"] = public_api.get(f"/api/recipes/{rec1_id}").status_code
            state["public_rec2_status"] = public_api.get(f"/api/recipes/{rec2_id}").status_code
        finally:
            ctx_admin.close()

        # Verify existing baseline records were not modified or shifted by 7 hours
        after_recipes = fetch_all("SELECT recipe_id, created_at FROM recipes ORDER BY recipe_id ASC")
        after_map = {int(r["recipe_id"]): str(r["created_at"]) for r in after_recipes}
        state["existing_timestamps_unchanged"] = all(
            after_map.get(rid) == ts for rid, ts in baseline_map.items()
        )

        yield state
    finally:
        _cleanup_created_recipes(created_recipe_ids, uploaded_paths)
        assert int(fetch_one("SELECT COUNT(*) AS c FROM recipes")["c"]) == baseline_count


# ===========================================================================
# VIII.1. Kiểm thử Upload ảnh & Bắt buộc có ảnh hợp lệ (Feature 1 & Feature 3)
# ===========================================================================

def test_upload_image_from_device_and_preview_success(workflow_state: dict[str, Any]) -> None:
    """Chọn ảnh từ máy tính thành công, xem trước ảnh, lưu UUID vào static/uploads/recipes/."""
    assert workflow_state["preview_visible_after_file"] is True
    assert workflow_state["selected_file_name"] == "bun_bo_hue.png"
    assert "B" in workflow_state["selected_file_size"]
    rel_path = workflow_state["rec1_image"]
    assert rel_path.startswith("static/uploads/recipes/")
    assert "bun_bo_hue" not in rel_path
    assert re.fullmatch(r"static/uploads/recipes/[0-9a-f-]{36}\.png", rel_path)
    assert workflow_state["rec1_file_exists"] is True
    assert workflow_state["rec1_http_serve_status"] == 200


def test_image_url_submission_and_mutual_exclusion(workflow_state: dict[str, Any]) -> None:
    """Nhập URL ảnh thành công; chọn ảnh từ thiết bị và nhập URL loại trừ lẫn nhau trên cả UI và API."""
    assert workflow_state["url_after_file_select"] == ""
    assert workflow_state["file_info_visible_after_url"] is False
    assert workflow_state["rec2_image"] == "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=800"
    assert workflow_state["conflict_status"] == 400
    assert workflow_state["conflict_error"] == "RECIPE_IMAGE_CONFLICT"


def test_missing_image_and_default_fallback_rejected_for_member_and_admin(workflow_state: dict[str, Any]) -> None:
    """Thiếu ảnh hoặc dùng ảnh mặc định bị từ chối (400 RECIPE_IMAGE_REQUIRED) cho cả Member và Admin."""
    assert workflow_state["missing_img_member_status"] == 400
    assert workflow_state["missing_img_member_json"]["error"] == "RECIPE_IMAGE_REQUIRED"
    assert workflow_state["missing_img_admin_status"] == 400
    assert workflow_state["missing_img_admin_json"]["error"] == "RECIPE_IMAGE_REQUIRED"
    assert workflow_state["fallback_svg_status"] == 400
    assert workflow_state["fallback_svg_error"] == "RECIPE_IMAGE_REQUIRED"
    assert workflow_state["count_after_rejections"] == workflow_state["baseline_count"]


def test_invalid_image_format_and_oversized_file_rejected(workflow_state: dict[str, Any]) -> None:
    """Ảnh sai định dạng (.exe, fake magic bytes, bad URL) và file > 5 MB bị từ chối với HTTP 400."""
    assert workflow_state["bad_url_status"] == 400
    assert workflow_state["bad_url_error"] == "RECIPE_IMAGE_INVALID_URL"
    assert workflow_state["bad_exe_status"] == 400
    assert workflow_state["bad_exe_error"] == "RECIPE_IMAGE_INVALID_FORMAT"
    assert workflow_state["fake_png_status"] == 400
    assert workflow_state["fake_png_error"] == "RECIPE_IMAGE_INVALID_FORMAT"
    assert workflow_state["oversized_status"] == 400
    assert workflow_state["oversized_error"] == "RECIPE_IMAGE_TOO_LARGE"


# ===========================================================================
# VIII.2. Kiểm thử Bước 5 (Feature 2)
# ===========================================================================

def test_step5_simplified_on_member_and_admin_forms(workflow_state: dict[str, Any]) -> None:
    """Member chỉ thấy 'Gửi công thức' & 'Hủy / Quay lại'; Admin chỉ thấy 'Thêm công thức' & 'Hủy / Quay lại'; bỏ khung giải thích dài."""
    assert workflow_state["member_step5_notice_count"] == 0
    assert "Gửi công thức" in workflow_state["member_submit_btn_text"]
    assert "Hủy / Quay lại" in workflow_state["member_cancel_btn_text"]

    assert workflow_state["admin_step5_notice_count"] == 0
    assert "Thêm công thức" in workflow_state["admin_submit_btn_text"]
    assert "Hủy / Quay lại" in workflow_state["admin_cancel_btn_text"]


# ===========================================================================
# VIII.3. Kiểm thử Thời gian (Feature 4)
# ===========================================================================

def test_recipe_submission_time_has_no_7_hour_offset_and_preserves_old_records(workflow_state: dict[str, Any]) -> None:
    """Công thức mới trả timestamp chuẩn ISO UTC ('...Z'), hiển thị 'Vừa xong' không lệch 7 tiếng, giữ nguyên bản ghi cũ."""
    iso_ts = workflow_state["rec1_created_at_iso"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", iso_ts)
    row_text = workflow_state["queue_row1_text"]
    assert "Vừa xong" in row_text or "phút trước" in row_text
    assert "7 giờ trước" not in row_text
    assert workflow_state["existing_timestamps_unchanged"] is True


# ===========================================================================
# VIII.4. Kiểm thử Duyệt công thức trên trang chi tiết riêng (Feature 5)
# ===========================================================================

def test_pending_list_has_only_view_detail_and_navigates_to_dedicated_review_page(workflow_state: dict[str, Any]) -> None:
    """Danh sách chờ duyệt không có nút Duyệt/Từ chối; nhấn 'Xem chi tiết' điều hướng sang review-recipe.html?id=<id>."""
    assert workflow_state["queue_row1_approve_btn_count"] == 0
    assert workflow_state["queue_row1_reject_btn_count"] == 0
    assert "Xem chi tiết" in workflow_state["queue_row1_view_detail_text"]
    assert workflow_state["review_api_status"] == 200
    assert f"pages/admin/review-recipe.html?id={workflow_state['rec1_id']}" in workflow_state["review_page_url"]


def test_dedicated_review_page_displays_full_recipe_and_moderates_at_bottom(workflow_state: dict[str, Any]) -> None:
    """Trang chi tiết hiển thị đầy đủ thông tin, nguyên liệu, bước nấu, dinh dưỡng ('Chưa cập nhật'), và duyệt/từ chối ở cuối trang."""
    assert "Đầu Bếp Thành Viên" in workflow_state["review_general_text"]
    assert "Bún sợi to" in workflow_state["review_ing_text"]
    assert "500" in workflow_state["review_ing_text"]
    assert "Hầm xương bò với sả cây trong 45 phút." in workflow_state["review_steps_text"]
    assert "Chưa cập nhật" in workflow_state["review_nutrition_text"]
    assert workflow_state["review_footer_visible"] is True

    assert workflow_state["approve_http_status"] == 200
    assert workflow_state["rec1_db_status_after_approve"] == "APPROVED"

    assert workflow_state["reject_http_status"] == 200
    assert workflow_state["rec2_db_status_after_reject"] == "REJECTED"
    assert "nước chấm" in workflow_state["rec2_db_reason_after_reject"]


# ===========================================================================
# VIII.5. Kiểm thử Phân tách Hàng đợi duyệt và Quản lý công thức (Feature 6)
# ===========================================================================

def test_pending_separated_from_recipe_management_at_sql_and_ui(workflow_state: dict[str, Any]) -> None:
    """Pending chỉ xuất hiện ở hàng đợi duyệt, không xuất hiện ở Quản lý công thức (kể cả API SQL); Approved & Rejected phân tách đúng."""
    assert workflow_state["api_admin_recipes_has_pending"] is False
    assert workflow_state["api_admin_recipes_contains_rec1_before_approve"] is False
    assert workflow_state["mgmt_has_pending_rec1_in_ui"] is False
    assert all("Chờ duyệt" not in opt for opt in workflow_state["mgmt_status_filter_options"])

    assert workflow_state["mgmt_has_approved_rec1_after"] is True
    assert workflow_state["mgmt_count_ matches_filtered_rec1"] is True
    assert workflow_state["mgmt_has_rejected_rec2_after"] is True

    assert workflow_state["public_rec1_status"] == 200
    assert workflow_state["public_rec2_status"] == 404
