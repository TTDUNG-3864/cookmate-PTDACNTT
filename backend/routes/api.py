"""CookMate JSON API routes. All authorization is enforced here, server side."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import re
import time
import uuid
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session

from backend.database.connection import check_database
from backend.database import repositories as repo
from backend.security.authentication import admin_required, current_user, login_required
from backend.security.validators import clean_text, safe_int, valid_email
from backend.services.ai_search_service import search_online
from backend.services.chatbot_service import answer_message

api = Blueprint("api", __name__, url_prefix="/api")


def _body() -> dict[str, Any]:
    value=request.get_json(silent=True)
    return value if isinstance(value,dict) else {}


def _error(message: str, status: int = 400):
    return jsonify({"success":False,"error":message}),status


@api.get("/health")
def health():
    from backend.gemini_manager import get_gemini_runtime_status
    from backend.ollama_manager import OllamaServiceManager

    check_database()
    counts = repo.get_statistics()
    return jsonify({
        "status": "ok",
        "service": "CookMate Flask API",
        "database": "mysql",
        "counts": counts,
        "ollama": OllamaServiceManager.get_runtime_status(),
        "gemini": get_gemini_runtime_status(),
    })


@api.get("/bootstrap")
def bootstrap():
    user=current_user()
    return jsonify(repo.get_bootstrap_payload(user["id"] if user else None))


@api.get("/auth/csrf")
def csrf_token():
    token=session.get("csrf_token")
    if not token:
        token=secrets.token_urlsafe(32); session["csrf_token"]=token
    return jsonify({"csrfToken":token})


@api.post("/auth/register")
def register():
    body=_body()
    try:
        name=clean_text(body.get("name") or body.get("fullName"),maximum=150,required=True)
        email=valid_email(body.get("email"))
        user=repo.register_user(name,email,str(body.get("password") or ""))
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        if getattr(exc,"errno",None)==1062:
            return _error("Email đã được sử dụng.",409)
        raise
    session.clear(); session.permanent=True; session["user_id"]=user["id"]
    token=secrets.token_urlsafe(32); session["csrf_token"]=token
    return jsonify({"success":True,"user":user,"csrfToken":token}),201


@api.post("/auth/login")
def login():
    body=_body()
    try:
        email=valid_email(body.get("email"))
        password=str(body.get("password") or "")
        if not password:
            return _error("Vui lòng nhập mật khẩu.")
        user=repo.authenticate_user(email,password)
    except PermissionError as exc:
        return _error(str(exc),403)
    except ValueError as exc:
        return _error(str(exc))
    if not user:
        return _error("Email hoặc mật khẩu không đúng.",401)
    session.clear(); session.permanent=True; session["user_id"]=user["id"]
    token=secrets.token_urlsafe(32); session["csrf_token"]=token
    return jsonify({"success":True,"user":user,"csrfToken":token})


@api.post("/auth/logout")
def logout():
    session.clear()
    return jsonify({"success":True})


@api.get("/auth/me")
def auth_me():
    return jsonify({"authenticated":bool(current_user()),"user":current_user(),"csrfToken":session.get("csrf_token","")})


def _handle_password_reset_otp_request():
    body=_body()
    try:
        email=valid_email(body.get("email"))
    except ValueError:
        return _error("Email không hợp lệ.",400)

    limiter=current_app.extensions.get("otp_rate_limiter")
    if limiter is not None:
        allowed=limiter.check_and_record(
            email,
            request.remote_addr or "unknown",
            secret_key=str(current_app.config["SECRET_KEY"]),
            cooldown_seconds=int(current_app.config.get("OTP_RESEND_COOLDOWN_SECONDS",60)),
            max_requests=int(current_app.config.get("OTP_RATE_LIMIT_MAX_REQUESTS",5)),
            window_seconds=int(current_app.config.get("OTP_RATE_LIMIT_WINDOW_SECONDS",900)),
            ip_max_requests=int(current_app.config.get("OTP_IP_RATE_LIMIT_MAX",30)),
            ip_window_seconds=int(current_app.config.get("OTP_IP_RATE_LIMIT_WINDOW_SECONDS",300)),
        )
        if not allowed:
            return _error("Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút.",429)

    issued=None
    for attempt in range(5):
        try:
            issued=repo.create_password_reset_otp(
                email,
                secret_key=str(current_app.config["SECRET_KEY"]),
                otp_length=int(current_app.config.get("OTP_LENGTH",6)),
                expiry_minutes=int(current_app.config.get("OTP_EXPIRY_MINUTES",5)),
            )
            break
        except Exception as exc:
            if getattr(exc,"errno",None) not in (1213,1205) or attempt==4:
                raise
            time.sleep(0.005*(attempt+1)+secrets.randbelow(10)*0.001)

    if issued is not None and bool(current_app.config.get("DEMO_MODE",False)):
        banner=(
            f"{'=' * 50}\n"
            f"[COOKMATE DEMO MODE] Password Reset OTP\n"
            f"Email: {issued['email']}\n"
            f"OTP: {issued['otp']}\n"
            f"Expires in: {issued['expiry_minutes']} minutes\n"
            f"{'=' * 50}"
        )
        print(banner,flush=True)

    return jsonify({
        "success":True,
        "message":"Nếu email tồn tại trong hệ thống, mã xác minh đã được cấp.",
    })


@api.post("/auth/forgot-password")
def forgot_password():
    return _handle_password_reset_otp_request()


@api.post("/auth/resend-otp")
def resend_otp():
    return _handle_password_reset_otp_request()


@api.post("/auth/verify-otp")
def verify_otp():
    if str(current_app.config.get("APP_ENV") or "development").strip().lower()=="production" and not request.is_secure:
        return _error("Chỉ hỗ trợ khôi phục mật khẩu qua kết nối HTTPS trong môi trường production.",403)
    body=_body()
    try:
        email=valid_email(body.get("email"))
    except ValueError:
        return _error("Email không hợp lệ.",400)

    otp_len=max(6,int(current_app.config.get("OTP_LENGTH",6)))
    raw_otp=body.get("otp")
    if not isinstance(raw_otp,str) or any(ord(ch)<32 or ord(ch)==127 for ch in raw_otp):
        return _error("Mã xác minh phải gồm đúng 6 chữ số.",400)
    otp=raw_otp.strip(" ")
    if not re.fullmatch(rf"[0-9]{{{otp_len}}}",otp):
        return _error("Mã xác minh phải gồm đúng 6 chữ số.",400)

    result=repo.verify_password_reset_otp(
        email,
        otp,
        secret_key=str(current_app.config["SECRET_KEY"]),
        max_attempts=int(current_app.config.get("OTP_MAX_ATTEMPTS",5)),
        temp_password_length=int(current_app.config.get("TEMP_PASSWORD_LENGTH",16)),
    )
    if not result.get("ok"):
        return _error(str(result.get("error") or "Mã xác minh không hợp lệ."),int(result.get("status") or 400))

    return jsonify({
        "success":True,
        "message":"Khôi phục mật khẩu thành công",
        "temporary_password":result["temporary_password"],
    })


@api.post("/auth/change-password")
@login_required
def change_password():
    body=_body(); user=current_user()
    raw_current=body.get("current_password")
    raw_new=body.get("new_password")
    raw_confirm=body.get("confirm_password")
    current_password=raw_current if isinstance(raw_current,str) else ""
    new_password=raw_new if isinstance(raw_new,str) else ""
    confirm_password=raw_confirm if isinstance(raw_confirm,str) else ""
    try:
        repo.change_user_password(
            user["id"],
            current_password,
            new_password,
            confirm_password,
        )
    except PermissionError as exc:
        session.clear()
        return _error(str(exc),403)
    except ValueError as exc:
        return _error(str(exc),400)
    return jsonify({"success":True,"message":"Đổi mật khẩu thành công."})


@api.post("/auth/force-change-password")
@login_required
def force_change_password():
    body=_body(); user=current_user()
    raw_new=body.get("new_password")
    raw_confirm=body.get("confirm_password")
    new_password=raw_new if isinstance(raw_new,str) else ""
    confirm_password=raw_confirm if isinstance(raw_confirm,str) else ""
    try:
        updated=repo.force_change_user_password(
            user["id"],
            new_password,
            confirm_password,
        )
    except PermissionError as exc:
        session.clear()
        return _error(str(exc),403)
    except ValueError as exc:
        return _error(str(exc),400)
    return jsonify({
        "success":True,
        "message":"Mật khẩu đã được cập nhật thành công",
        "user":updated,
    })


@api.put("/users/profile")
@login_required
def update_profile():
    body=_body(); user=current_user()
    try:
        updated=repo.update_user_profile(user["id"],body)
        return jsonify({"success":True,"user":updated})
    except ValueError as exc:
        return _error(str(exc))


@api.post("/recommendations/match")
def recommendations():
    body=_body()
    ids=body.get("ingredientIds") or []
    names=body.get("ingredientNames") or []
    if not isinstance(ids,list) or not isinstance(names,list):
        return _error("ingredientIds and ingredientNames must be lists.")
    try:
        payload=repo.match_dishes_detailed(ids,names)
    except (TypeError,ValueError):
        return _error("Danh sách nguyên liệu không hợp lệ.")
    return jsonify(payload)


@api.get("/recipes")
def recipes():
    filters={}
    if request.args.get("categoryId","").isdigit(): filters["category_id"]=int(request.args["categoryId"])
    if request.args.get("dishId","").isdigit(): filters["dish_id"]=int(request.args["dishId"])
    if request.args.get("q") or request.args.get("search"): filters["q"]=request.args.get("q") or request.args.get("search")
    if request.args.get("holiday"): filters["occasion"]=request.args["holiday"]
    if request.args.get("difficulty"): filters["difficulty"]=request.args["difficulty"]
    if request.args.get("maxTime","").isdigit(): filters["max_time"]=int(request.args["maxTime"])
    if request.args.get("featured") is not None: filters["featured"]=request.args.get("featured").lower() in ("1","true","yes")
    data=repo.list_recipes(filters)
    return jsonify({"recipes":data,"total":len(data)})


@api.get("/recipes/my")
@login_required
def my_recipes():
    data=repo.list_my_recipes(current_user()["id"])
    return jsonify({"recipes":data,"total":len(data)})


@api.get("/recipes/<int:recipe_id>")
def recipe_detail(recipe_id: int):
    recipe=repo.get_recipe(recipe_id)
    if not recipe:
        user=current_user()
        if user:
            mine=next((item for item in repo.list_my_recipes(user["id"]) if item["id"]==recipe_id),None)
            if mine: return jsonify(mine)
        return _error("Không tìm thấy công thức công khai.",404)
    if request.args.get("incrementView") in ("1","true"):
        recipe["views"]=repo.increment_recipe_views(recipe_id)
    return jsonify(recipe)


_ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _detect_image_magic(data: bytes, orig_ext: str) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        if orig_ext and orig_ext not in (".jpg", ".jpeg"):
            raise repo.RecipeValidationError(
                "RECIPE_IMAGE_INVALID_FORMAT",
                "Định dạng file không khớp với nội dung ảnh JPEG.",
            )
        return ".jpeg" if orig_ext == ".jpeg" else ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if orig_ext and orig_ext != ".png":
            raise repo.RecipeValidationError(
                "RECIPE_IMAGE_INVALID_FORMAT",
                "Định dạng file không khớp với nội dung ảnh PNG.",
            )
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if orig_ext and orig_ext != ".webp":
            raise repo.RecipeValidationError(
                "RECIPE_IMAGE_INVALID_FORMAT",
                "Định dạng file không khớp với nội dung ảnh WebP.",
            )
        return ".webp"
    raise repo.RecipeValidationError(
        "RECIPE_IMAGE_INVALID_FORMAT",
        "File tải lên không phải ảnh hợp lệ. Chỉ hỗ trợ JPG, JPEG, PNG và WebP.",
    )


def _save_uploaded_recipe_image(file_storage) -> str:
    raw_name = str(getattr(file_storage, "filename", "") or "").strip()
    orig_ext = Path(raw_name).suffix.lower() if raw_name else ""
    if orig_ext and orig_ext not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise repo.RecipeValidationError(
            "RECIPE_IMAGE_INVALID_FORMAT",
            "Định dạng file không được phép. Chỉ chấp nhận JPG, JPEG, PNG và WebP.",
        )
    max_bytes = int(current_app.config.get("RECIPE_IMAGE_MAX_BYTES", 5 * 1024 * 1024))
    stream = getattr(file_storage, "stream", file_storage)
    try:
        stream.seek(0)
    except Exception:
        pass
    raw_bytes = stream.read(max_bytes + 1)
    if not raw_bytes:
        raise repo.RecipeValidationError(
            "RECIPE_IMAGE_INVALID_FORMAT",
            "File ảnh tải lên bị rỗng hoặc không hợp lệ.",
        )
    if len(raw_bytes) > max_bytes:
        raise repo.RecipeValidationError(
            "RECIPE_IMAGE_TOO_LARGE",
            "Dung lượng ảnh vượt quá giới hạn tối đa 5 MB.",
        )
    detected_ext = _detect_image_magic(raw_bytes, orig_ext)
    new_filename = f"{uuid.uuid4()}{detected_ext}"
    upload_dir = Path(
        str(current_app.config.get("RECIPE_UPLOAD_DIR") or (Path(current_app.root_path) / "static" / "uploads" / "recipes"))
    )
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = upload_dir / new_filename
    target_path.write_bytes(raw_bytes)
    return f"static/uploads/recipes/{new_filename}"


def _parse_recipe_request() -> dict[str, Any]:
    content_type = str(request.content_type or "").lower()
    if content_type.startswith("multipart/form-data"):
        payload: dict[str, Any] = {}
        raw_payload = request.form.get("payload")
        if raw_payload:
            try:
                loaded = json.loads(raw_payload)
                if isinstance(loaded, dict):
                    payload.update(loaded)
            except (TypeError, ValueError):
                raise repo.RecipeValidationError("INVALID_PAYLOAD", "Dữ liệu biểu mẫu công thức không hợp lệ.")
        for key in (
            "title", "name", "slug", "description", "cuisine", "difficulty",
            "occasion", "image", "image_url", "imageUrl",
            "categoryId", "category_id", "servings", "prepTime", "prep_time",
            "cookTime", "cook_time", "calories", "protein", "carbs", "fat", "fiber",
        ):
            if key in request.form:
                val = request.form.get(key)
                if val is not None and (key not in payload or val != ""):
                    payload[key] = val
        for json_key in ("ingredients", "steps", "nutrition", "tags"):
            if json_key in request.form and request.form.get(json_key):
                try:
                    payload[json_key] = json.loads(request.form[json_key])
                except (TypeError, ValueError):
                    raise repo.RecipeValidationError("INVALID_PAYLOAD", f"Trường {json_key} không đúng định dạng JSON.")
        if not payload.get("title") and payload.get("name"):
            payload["title"] = payload["name"]

        upload = (
            request.files.get("image_file")
            or request.files.get("imageFile")
            or request.files.get("image")
            or request.files.get("file")
        )
        has_file = bool(upload and str(getattr(upload, "filename", "") or "").strip())
        raw_url = str(payload.get("image") or payload.get("image_url") or payload.get("imageUrl") or "").strip()
        if has_file and raw_url:
            raise repo.RecipeValidationError(
                "RECIPE_IMAGE_CONFLICT",
                "Không được gửi đồng thời cả file ảnh tải lên và URL hình ảnh.",
            )
        if has_file:
            saved_path = _save_uploaded_recipe_image(upload)
            payload["image"] = saved_path
            payload["image_url"] = saved_path
            payload["imageUrl"] = saved_path
        return payload

    payload = dict(_body())
    if not payload.get("title") and payload.get("name"):
        payload["title"] = payload["name"]
    return payload


@api.post("/recipes")
@login_required
def create_recipe():
    user=current_user()
    try:
        payload=_parse_recipe_request()
        recipe=repo.create_recipe(payload,user["id"],admin=user["role"]=="admin")
        return jsonify({"success":True,"recipe":recipe}),201
    except repo.RecipeValidationError as exc:
        return jsonify({"success":False,"error":exc.code,"message":exc.message}),400
    except ValueError as exc:
        return jsonify({"success":False,"error":str(exc),"message":str(exc)}),400


@api.put("/recipes/<int:recipe_id>")
@login_required
def update_recipe(recipe_id: int):
    user=current_user()
    try:
        payload=_parse_recipe_request()
        recipe=repo.update_recipe(recipe_id,user["id"],payload,admin=user["role"]=="admin")
        return jsonify({"success":True,"recipe":recipe}) if recipe else _error("Không tìm thấy công thức của bạn.",404)
    except repo.RecipeValidationError as exc:
        return jsonify({"success":False,"error":exc.code,"message":exc.message}),400
    except ValueError as exc:
        return jsonify({"success":False,"error":str(exc),"message":str(exc)}),400


@api.delete("/recipes/<int:recipe_id>")
@login_required
def delete_recipe(recipe_id: int):
    user=current_user()
    deleted=repo.delete_recipe(recipe_id,user["id"],admin=user["role"]=="admin")
    return jsonify({"success":True,"deletedId":recipe_id}) if deleted else _error("Không tìm thấy công thức của bạn.",404)


@api.get("/recipes/<int:recipe_id>/scale")
def scale_recipe(recipe_id: int):
    try:
        servings=safe_int(request.args.get("servings",4),minimum=1,maximum=50)
    except ValueError as exc:
        return _error(str(exc))
    result=repo.scale_recipe(recipe_id,servings)
    return jsonify(result) if result else _error("Không tìm thấy công thức công khai.",404)


@api.post("/recipes/ai-search")
def ai_search():
    try:
        query=clean_text(_body().get("query") or _body().get("dishName") or _body().get("dish"),maximum=200,required=True)
        return jsonify(search_online(query))
    except ValueError as exc:
        return _error(str(exc))


@api.get("/categories")
def categories():
    rows=repo.list_categories()
    return jsonify({"categories":rows,"total":len(rows)})


@api.post("/categories")
@admin_required
def create_category():
    try: return jsonify({"success":True,"category":repo.save_category(_body())}),201
    except ValueError as exc: return _error(str(exc))


@api.put("/categories/<int:category_id>")
@admin_required
def update_category(category_id: int):
    try:
        row=repo.save_category(_body(),category_id)
        return jsonify({"success":True,"category":row}) if row else _error("Không tìm thấy danh mục.",404)
    except ValueError as exc: return _error(str(exc))


@api.delete("/categories/<int:category_id>")
@admin_required
def remove_category(category_id: int):
    return jsonify({"success":True,"deletedId":category_id}) if repo.delete_category(category_id) else _error("Không tìm thấy danh mục.",404)


@api.put("/categories/sync")
@admin_required
def sync_categories():
    body=_body();values=body.get("categories") or []
    if not isinstance(values,list):return _error("categories must be a list.")
    try:
        rows=repo.sync_categories(values);return jsonify({"success":True,"categories":rows})
    except ValueError as exc:return _error(str(exc))


@api.get("/ingredients")
def ingredients():
    rows=repo.list_ingredients()
    return jsonify({"ingredients":rows,"total":len(rows)})


@api.post("/ingredients")
@admin_required
def create_ingredient():
    try:return jsonify({"success":True,"ingredient":repo.save_ingredient(_body())}),201
    except ValueError as exc:return _error(str(exc))


@api.put("/ingredients/<int:ingredient_id>")
@admin_required
def update_ingredient(ingredient_id: int):
    try:
        row=repo.save_ingredient(_body(),ingredient_id)
        return jsonify({"success":True,"ingredient":row}) if row else _error("Không tìm thấy nguyên liệu.",404)
    except ValueError as exc:return _error(str(exc))


@api.delete("/ingredients/<int:ingredient_id>")
@admin_required
def remove_ingredient(ingredient_id: int):
    return jsonify({"success":True,"deletedId":ingredient_id}) if repo.delete_ingredient(ingredient_id) else _error("Không tìm thấy nguyên liệu hoặc nguyên liệu đang được dùng.",409)


@api.put("/ingredients/sync")
@admin_required
def sync_ingredients():
    body=_body();values=body.get("ingredients") or []
    if not isinstance(values,list):return _error("ingredients must be a list.")
    try:
        rows=repo.sync_ingredients(values);return jsonify({"success":True,"ingredients":rows})
    except ValueError as exc:return _error(str(exc))


@api.get("/favorites")
@login_required
def favorites():
    rows=repo.list_favorite_recipes(current_user()["id"])
    return jsonify({"favorites":[item["id"] for item in rows],"recipes":rows,"total":len(rows)})


@api.post("/favorites/toggle")
@login_required
def favorites_toggle():
    try:
        recipe_id=safe_int(_body().get("recipeId"),minimum=1,maximum=2_147_483_647)
        return jsonify({"success":True,**repo.toggle_favorite(current_user()["id"],recipe_id)})
    except ValueError as exc:
        return _error(str(exc),404 if "không tìm thấy" in str(exc).lower() else 400)


@api.get("/admin/pending-recipes")
@admin_required
def admin_pending_recipes():
    rows=repo.list_pending_recipes()
    return jsonify({"recipes":rows,"total":len(rows)})


@api.get("/admin/recipes")
@admin_required
def admin_all_recipes():
    status_param = request.args.get("status")
    rows=repo.list_all_recipes_admin(status_param)
    return jsonify({"recipes":rows,"total":len(rows)})


@api.get("/admin/recipes/<int:recipe_id>")
@admin_required
def admin_recipe_detail(recipe_id: int):
    row=repo.get_admin_recipe_review(recipe_id)
    return jsonify(row) if row else _error("Không tìm thấy công thức.",404)


@api.get("/admin/recipes/<int:recipe_id>/review")
@admin_required
def admin_recipe_review(recipe_id: int):
    row=repo.get_admin_recipe_review(recipe_id)
    return jsonify(row) if row else _error("Không tìm thấy công thức.",404)


@api.delete("/admin/recipes/<int:recipe_id>")
@admin_required
def admin_delete_recipe(recipe_id: int):
    deleted=repo.delete_recipe(recipe_id,current_user()["id"],admin=True)
    if not deleted:
        return _error("Không tìm thấy công thức.",404)
    return jsonify({"success":True,"deletedId":recipe_id,"message":"Đã xóa công thức thành công"})


@api.post("/admin/recipes/<int:recipe_id>/approve")
@admin_required
def admin_approve_recipe(recipe_id: int):
    row=repo.moderate_recipe(recipe_id,current_user()["id"],"APPROVED")
    return jsonify({"success":True,"recipe":row}) if row else _error("Công thức không còn ở trạng thái chờ duyệt.",409)


@api.post("/admin/recipes/<int:recipe_id>/reject")
@admin_required
def admin_reject_recipe(recipe_id: int):
    reason=clean_text(_body().get("reason") or _body().get("rejectionReason") or "",maximum=500)
    row=repo.moderate_recipe(recipe_id,current_user()["id"],"REJECTED",reason=reason)
    return jsonify({"success":True,"recipe":row}) if row else _error("Công thức không còn ở trạng thái chờ duyệt.",409)


# Compatibility routes used by the retained admin pages. They share the same RBAC checks.
@api.post("/recipes/<int:recipe_id>/approve")
@admin_required
def approve_recipe_compat(recipe_id: int):
    return admin_approve_recipe.__wrapped__.__wrapped__(recipe_id)


@api.post("/recipes/<int:recipe_id>/reject")
@admin_required
def reject_recipe_compat(recipe_id: int):
    return admin_reject_recipe.__wrapped__.__wrapped__(recipe_id)


@api.get("/admin/users")
@admin_required
def admin_users():
    rows=repo.list_users()
    return jsonify({"users":rows,"total":len(rows)})


@api.put("/admin/users/<int:user_id>/status")
@admin_required
def admin_user_status(user_id: int):
    try:
        row=repo.set_user_status(user_id,str(_body().get("status") or ""))
        return jsonify({"success":True,"user":row}) if row else _error("Không tìm thấy tài khoản.",404)
    except ValueError as exc:
        return _error(str(exc))


@api.get("/admin/statistics")
@admin_required
def admin_statistics():
    return jsonify(repo.get_statistics())


@api.get("/recipes/<int:recipe_id>/comments")
def recipe_comments(recipe_id: int):
    if not repo.get_recipe(recipe_id): return _error("Không tìm thấy công thức công khai.",404)
    rows=repo.list_comments(recipe_id)
    return jsonify({"comments":rows,"total":len(rows)})


@api.post("/recipes/<int:recipe_id>/comments")
@login_required
def add_recipe_comment(recipe_id: int):
    try:
        item=repo.add_comment(recipe_id,current_user(),_body())
        return jsonify({"success":True,"comment":item}),201
    except ValueError as exc:
        return _error(str(exc),404 if "không tìm thấy" in str(exc).lower() else 400)


@api.get("/comments")
@admin_required
def comments():
    rows=repo.list_comments()
    return jsonify({"comments":rows,"total":len(rows)})


@api.delete("/comments/<int:comment_id>")
@login_required
def delete_comment(comment_id: int):
    user=current_user()
    try:
        return jsonify({"success":True,"deletedId":comment_id}) if repo.delete_comment(comment_id,user["id"],admin=user["role"]=="admin") else _error("Không tìm thấy bình luận.",404)
    except PermissionError as exc:return _error(str(exc),403)


@api.post("/nutrition/estimate")
def nutrition_estimate():
    body=_body(); items=body.get("ingredients") or []
    servings=max(1,min(50,int(body.get("servings") or 2)))
    lookup={item["name"].lower():item for item in repo.list_ingredients()}
    totals={key:0.0 for key in ("calories","protein","fat","carbs","fiber")}
    for item in items:
        if not isinstance(item,dict): continue
        found=lookup.get(str(item.get("name") or "").lower())
        if not found: continue
        try: amount=float(re.sub(r"[^0-9.,]","",str(item.get("amount") or "1")).replace(",","."))
        except ValueError: amount=1
        unit=str(item.get("unit") or "g").lower(); factor=amount/100 if unit in ("g","ml","100g","100ml") else amount
        for key in totals: totals[key]+=float(found.get(key) or 0)*factor
    nutrition={key:round(value/servings,1) for key,value in totals.items()}
    return jsonify({"success":True,"nutrition":nutrition,"basis":"estimated per serving using ingredient values per 100g/100ml"})


@api.post("/chatbot/sessions")
def create_chat_session():
    user=current_user(); body=_body(); recipe_id=body.get("recipe_id") or body.get("recipeId")
    if recipe_id:
        recipe=repo.get_recipe(int(recipe_id))
        if not recipe: return _error("Không tìm thấy công thức công khai.",404)
        recipe_id=recipe["id"]
    session_id=secrets.token_urlsafe(32)
    repo.create_chat_session(session_id,user["id"] if user else None,recipe_id)
    guest_ids=session.get("guest_chat_sessions",[])
    if not user:
        guest_ids.append(session_id); session["guest_chat_sessions"]=guest_ids[-20:]
    return jsonify({"success":True,"session_id":session_id}),201


def _owned_chat_session(session_id: str):
    row=repo.get_chat_session(session_id)
    if not row: return None
    user=current_user()
    if row["user_id"] is not None:
        return row if user and user["id"]==row["user_id"] else None
    return row if session_id in session.get("guest_chat_sessions",[]) else None


@api.get("/chatbot/sessions/<session_id>")
def get_chat_session(session_id: str):
    if not _owned_chat_session(session_id): return _error("Không tìm thấy phiên trò chuyện.",404)
    return jsonify({"session_id":session_id,"messages":repo.get_chat_history(session_id)})


@api.delete("/chatbot/sessions/<session_id>")
def delete_chat_session(session_id: str):
    if not _owned_chat_session(session_id): return _error("Không tìm thấy phiên trò chuyện.",404)
    repo.delete_chat_session(session_id)
    guest_ids=[item for item in session.get("guest_chat_sessions",[]) if item!=session_id]
    session["guest_chat_sessions"]=guest_ids
    return jsonify({"success":True})


@api.post("/chatbot")
def chatbot():
    body=_body()
    if "apiKey" in body or "api_key" in body:
        return _error("API key is server-managed and cannot be sent by clients.",400)
    message=str(body.get("message") or "")
    session_id=str(body.get("session_id") or body.get("sessionId") or "")
    if not session_id or not _owned_chat_session(session_id):
        return _error("Phiên trò chuyện không hợp lệ. Hãy bắt đầu cuộc trò chuyện mới.",404)
    chat=repo.get_chat_session(session_id)
    recipe_id=body.get("recipe_id") or body.get("recipeId") or chat.get("context_recipe_id")
    history=repo.get_chat_history(session_id)
    result=answer_message(message,recipe_id=int(recipe_id) if recipe_id else None,history=history)
    if result["classification"] not in ("EMPTY","TOO_LONG"):
        repo.save_chat_messages(session_id,message,result["reply"])
    status_by_error={
        "AI_CONFIGURATION_ERROR":503,
        "AI_MISSING_API_KEY":503,
        "AI_INVALID_API_KEY":503,
        "AI_EXPIRED_REVOKED_API_KEY":503,
        "AI_PERMISSION_DENIED":503,
        "AI_SERVICE_UNAVAILABLE":503,
        "AI_OLLAMA_UNAVAILABLE":503,
        "AI_INVALID_INPUT":400,
        "AI_REQUEST_REJECTED":400,
    }
    return jsonify({"success":True,**result}),status_by_error.get(result.get("error_code"),200)


@api.post("/chatbot/feedback")
def chatbot_feedback():
    body=_body()
    session_id=str(body.get("session_id") or body.get("sessionId") or "").strip()
    if session_id and not _owned_chat_session(session_id):
        return _error("Phiên trò chuyện không hợp lệ.",404)
    try:
        qa_id=safe_int(body.get("qa_id") or body.get("qaId"),minimum=1,maximum=10**9)
        rating=int(body.get("rating") or 0)
        if rating not in (1,-1):
            raise ValueError("rating must be 1 or -1.")
    except (TypeError,ValueError) as exc:
        return _error(str(exc),400)
    updated=repo.record_chatbot_feedback(qa_id,rating)
    if not updated:
        return _error("Không tìm thấy mục kiến thức trợ lý để đánh giá.",404)
    return jsonify({"success":True,"feedback":updated})


@api.get("/chatbot/config")
def chatbot_config():
    from backend.config import validate_gemini_configuration
    validation=validate_gemini_configuration()
    local_configured=bool(current_app.config.get("OLLAMA_BASE_URL") and current_app.config.get("OLLAMA_MODEL"))
    return jsonify({
        "success":True,
        "configured":local_configured,
        "localConfigured":local_configured,
        "localModel":current_app.config.get("OLLAMA_MODEL"),
        "fallbackConfigured":bool(validation["configured"]),
        "inputKeyEnabled":False,
        "apiKeyStatus":validation["api_key_status"],
        "apiKeyValidity":validation["api_key_validity"],
        "keyConflict":validation["api_key_conflict"],
        "errors":list(validation["errors"]),
    })

