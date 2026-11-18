"""CookMate JSON API routes. All authorization is enforced here, server side."""

from __future__ import annotations

import secrets
import re
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


@api.post("/recipes")
@login_required
def create_recipe():
    user=current_user()
    try:
        recipe=repo.create_recipe(_body(),user["id"],admin=user["role"]=="admin")
        return jsonify({"success":True,"recipe":recipe}),201
    except ValueError as exc:
        return _error(str(exc))


@api.put("/recipes/<int:recipe_id>")
@login_required
def update_recipe(recipe_id: int):
    user=current_user()
    try:
        recipe=repo.update_recipe(recipe_id,user["id"],_body(),admin=user["role"]=="admin")
        return jsonify({"success":True,"recipe":recipe}) if recipe else _error("Không tìm thấy công thức của bạn.",404)
    except ValueError as exc:
        return _error(str(exc))


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


@api.get("/admin/recipes/<int:recipe_id>")
@admin_required
def admin_recipe_detail(recipe_id: int):
    row=repo.get_recipe(recipe_id,include_private=True)
    return jsonify(row) if row else _error("Không tìm thấy công thức.",404)


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

