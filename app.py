# -*- coding: utf-8 -*-
"""
CookMate — Python Flask Backend Application (app.py)
=====================================================
Serves both:
  1. All 21 Frontend HTML pages and static assets (`index.html`, `pages/**`, `assets/**`)
     without altering existing relative paths or Admin SPA routing.
  2. Complete RESTful API (`/api/...`) backed by SQLite (`database/cookmate.db`)
     covering all 21 Use Cases (`UC01` - `UC21`), including:
       - Authentication & User Profile (`UC11`, `UC12`, `UC14`, `UC20`)
       - Recipes CRUD & Approval Workflow (`UC01`-`UC10`, `UC16`, `UC18`)
       - Dynamic Portion Scaling (`UC06-A`) & Nutrition Estimation (`UC06-B`)
       - Categories & Ingredients Management (`UC03`, `UC04`, `UC17`, `UC19`)
       - Comments & Ratings (`UC07`, `UC21`)
       - Favorites (`UC13`)
       - Admin Dashboard & Statistics (`UC15`)
"""

import os
from typing import Any, Dict, Optional

from backend import chatbot as ai_chatbot
from backend import database as db
from backend.flask_compat import (
     USING_NATIVE_FLASK,
    Flask,
    jsonify,
    redirect,
    request,
    send_from_directory,
    session,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "assets"),
    static_url_path="/assets",
    template_folder=os.path.join(BASE_DIR, "templates"),
)
app.secret_key = os.environ.get(
    "COOKMATE_SECRET_KEY", "cookmate-ptdacntt-secret-key-2026"
)

# Ensure SQLite database and seed data exist at startup
db.init_db()


def _current_user() -> Optional[Dict[str, Any]]:
    """Retrieve currently authenticated user from session or X-User-Id header."""
    uid = session.get("user_id")
    if not uid:
        header_uid = request.headers.get("X-User-Id")
        if header_uid and str(header_uid).isdigit():
            uid = int(header_uid)
    if not uid:
        return None
    return db.get_user_by_id(int(uid))


# ============================================================
# FRONTEND PAGE & ASSET ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def serve_root():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/index.html", methods=["GET"])
def serve_index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/pages/<path:filename>", methods=["GET"])
def serve_pages(filename: str):
    return send_from_directory(os.path.join(BASE_DIR, "pages"), filename)


@app.route("/assets/<path:filename>", methods=["GET"])
def serve_assets(filename: str):
    return send_from_directory(os.path.join(BASE_DIR, "assets"), filename)


@app.route("/static/<path:filename>", methods=["GET"])
def serve_static_alias(filename: str):
    return send_from_directory(os.path.join(BASE_DIR, "assets"), filename)


# ============================================================
# SYSTEM & BOOTSTRAP API
# ============================================================

@app.route("/api/health", methods=["GET"])
def api_health():
    stats = db.get_statistics()
    return jsonify(
        {
            "status": "ok",
            "service": "CookMate Python Flask Backend",
            "nativeFlask": USING_NATIVE_FLASK,
            "database": db.get_db_path(),
            "counts": {
                "recipes": stats["totalRecipes"],
                "approvedRecipes": stats["approvedRecipes"],
                "pendingRecipes": stats["pendingRecipes"],
                "categories": stats["totalCategories"],
                "ingredients": stats["totalIngredients"],
                "users": stats["totalUsers"],
                "comments": stats["totalComments"],
            },
        }
    )


@app.route("/api/bootstrap", methods=["GET"])
def api_bootstrap():
    user = _current_user()
    uid = user["id"] if user else None
    q_uid = request.args.get("userId")
    if not uid and q_uid and str(q_uid).isdigit():
        uid = int(q_uid)
    payload = db.get_bootstrap_payload(current_user_id=uid)
    payload["currentUser"] = user
    return jsonify(payload)


# ============================================================
# AUTHENTICATION & USER PROFILE API (UC11, UC12, UC14, UC20)
# ============================================================

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    body = request.get_json(silent=True) or {}
    user, err = db.register_user(
        name=body.get("name", ""),
        email=body.get("email", ""),
        password=body.get("password", ""),
        avatar=body.get("avatar"),
        bio=body.get("bio", ""),
    )
    if err:
        return jsonify({"success": False, "error": err}), 400
    session["user_id"] = user["id"]
    session["user_role"] = user["role"]
    return jsonify({"success": True, "user": user}), 201


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    body = request.get_json(silent=True) or {}
    user, err = db.authenticate_user(
        email=body.get("email", ""),
        password=body.get("password", ""),
    )
    if err:
        status_code = 403 if err and "khóa" in err else 401
        return jsonify({"success": False, "error": err}), status_code
    session["user_id"] = user["id"]
    session["user_role"] = user["role"]
    return jsonify({"success": True, "user": user})


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/auth/me", methods=["GET"])
def api_me():
    user = _current_user()
    return jsonify({"authenticated": bool(user), "user": user})


@app.route("/api/users/profile", methods=["PUT"])
def api_update_profile():
    body = request.get_json(silent=True) or {}
    user = _current_user()
    user_id = body.get("id") or body.get("userId") or (user["id"] if user else None)
    if not user_id:
        return jsonify({"success": False, "error": "Chưa đăng nhập."}), 401
    updated, err = db.update_user_profile(int(user_id), body)
    if err:
        return jsonify({"success": False, "error": err}), 400
    return jsonify({"success": True, "user": updated})


# ============================================================
# RECIPES CRUD, APPROVAL & SCALING API (UC01-UC10, UC16, UC18)
# ============================================================

@app.route("/api/recipes", methods=["GET"])
def api_get_recipes():
    status = request.args.get("status", "approved")
    category_id = request.args.get("categoryId")
    author_id = request.args.get("authorId")
    featured_param = request.args.get("featured")
    holiday = request.args.get("holiday")
    search = request.args.get("q") or request.args.get("search")

    cat_int = int(category_id) if category_id and str(category_id).isdigit() else None
    auth_int = int(author_id) if author_id and str(author_id).isdigit() else None
    feat_bool = None
    if featured_param is not None:
        feat_bool = str(featured_param).lower() in ("1", "true", "yes")

    recipes = db.get_all_recipes(
        status=status,
        category_id=cat_int,
        author_id=auth_int,
        featured=feat_bool,
        holiday=holiday,
        search=search,
    )
    return jsonify({"recipes": recipes, "total": len(recipes)})


@app.route("/api/recipes/<int:recipe_id>", methods=["GET"])
def api_get_recipe_detail(recipe_id: int):
    recipe = db.get_recipe_by_id(recipe_id)
    if not recipe:
        return jsonify({"error": "Không tìm thấy công thức."}), 404
    if request.args.get("incrementView") in ("1", "true"):
        new_views = db.increment_recipe_views(recipe_id)
        recipe["views"] = new_views
    return jsonify(recipe)


@app.route("/api/recipes", methods=["POST"])
def api_create_recipe():
    body = request.get_json(silent=True) or {}
    user = _current_user()
    actor_role = body.get("actorRole") or (user["role"] if user else "user")
    if body.get("status") == "approved":
        actor_role = "admin"
    created = db.create_recipe(body, actor_role=actor_role)
    return jsonify({"success": True, "recipe": created}), 201


@app.route("/api/recipes/<int:recipe_id>", methods=["PUT"])
def api_update_recipe(recipe_id: int):
    body = request.get_json(silent=True) or {}
    updated = db.update_recipe(recipe_id, body)
    if not updated:
        return jsonify({"success": False, "error": "Không tìm thấy công thức."}), 404
    return jsonify({"success": True, "recipe": updated})


@app.route("/api/recipes/<int:recipe_id>", methods=["DELETE"])
def api_delete_recipe(recipe_id: int):
    deleted = db.delete_recipe(recipe_id)
    if not deleted:
        return jsonify({"success": False, "error": "Không tìm thấy công thức."}), 404
    return jsonify({"success": True, "deletedId": recipe_id})


@app.route("/api/recipes/<int:recipe_id>/approve", methods=["POST"])
def api_approve_recipe(recipe_id: int):
    updated = db.set_recipe_status(recipe_id, "approved")
    if not updated:
        return jsonify({"success": False, "error": "Không tìm thấy công thức."}), 404
    return jsonify({"success": True, "recipe": updated})


@app.route("/api/recipes/<int:recipe_id>/reject", methods=["POST"])
def api_reject_recipe(recipe_id: int):
    updated = db.set_recipe_status(recipe_id, "rejected")
    if not updated:
        return jsonify({"success": False, "error": "Không tìm thấy công thức."}), 404
    return jsonify({"success": True, "recipe": updated})


@app.route("/api/recipes/<int:recipe_id>/view", methods=["POST"])
def api_increment_view(recipe_id: int):
    views = db.increment_recipe_views(recipe_id)
    return jsonify({"success": True, "recipeId": recipe_id, "views": views})


@app.route("/api/recipes/<int:recipe_id>/scale", methods=["GET"])
def api_scale_recipe(recipe_id: int):
    """UC06-A: Scale recipe ingredient quantities & calories by target servings."""
    servings_str = request.args.get("servings", "4")
    try:
        servings = int(servings_str)
    except ValueError:
        servings = 4
    scaled = db.scale_recipe(recipe_id, servings)
    if not scaled:
        return jsonify({"error": "Không tìm thấy công thức."}), 404
    return jsonify(scaled)


@app.route("/api/nutrition/estimate", methods=["POST"])
def api_estimate_nutrition():
    """UC06-B: Estimate calories, protein, fat, carbs, fiber from ingredient list."""
    body = request.get_json(silent=True) or {}
    ingredients = body.get("ingredients") or []
    servings = int(body.get("servings") or 2)
    nutrition = db.estimate_nutrition(ingredients, servings=servings)
    return jsonify({"success": True, "nutrition": nutrition})


# ============================================================
# CATEGORIES API (UC04, UC17)
# ============================================================

@app.route("/api/categories", methods=["GET"])
def api_get_categories():
    cats = db.get_all_categories()
    return jsonify({"categories": cats, "total": len(cats)})


@app.route("/api/categories", methods=["POST"])
def api_create_category():
    body = request.get_json(silent=True) or {}
    cat = db.create_category(body)
    return jsonify({"success": True, "category": cat}), 201


@app.route("/api/categories/<int:cat_id>", methods=["PUT"])
def api_update_category(cat_id: int):
    body = request.get_json(silent=True) or {}
    cat = db.update_category(cat_id, body)
    if not cat:
        return jsonify({"success": False, "error": "Không tìm thấy danh mục."}), 404
    return jsonify({"success": True, "category": cat})


@app.route("/api/categories/<int:cat_id>", methods=["DELETE"])
def api_delete_category(cat_id: int):
    ok = db.delete_category(cat_id)
    if not ok:
        return jsonify({"success": False, "error": "Không tìm thấy danh mục."}), 404
    return jsonify({"success": True, "deletedId": cat_id})


@app.route("/api/categories/sync", methods=["PUT"])
def api_sync_categories():
    body = request.get_json(silent=True)
    cats_list = body.get("categories") if isinstance(body, dict) else body
    cats = db.sync_categories(cats_list or [])
    return jsonify({"success": True, "categories": cats})


# ============================================================
# INGREDIENTS API (UC03, UC19)
# ============================================================

@app.route("/api/ingredients", methods=["GET"])
def api_get_ingredients():
    ings = db.get_all_ingredients()
    return jsonify({"ingredients": ings, "total": len(ings)})


@app.route("/api/ingredients", methods=["POST"])
def api_create_ingredient():
    body = request.get_json(silent=True) or {}
    ing = db.create_ingredient(body)
    return jsonify({"success": True, "ingredient": ing}), 201


@app.route("/api/ingredients/<int:ing_id>", methods=["PUT"])
def api_update_ingredient(ing_id: int):
    body = request.get_json(silent=True) or {}
    ing = db.update_ingredient(ing_id, body)
    if not ing:
        return jsonify({"success": False, "error": "Không tìm thấy nguyên liệu."}), 404
    return jsonify({"success": True, "ingredient": ing})


@app.route("/api/ingredients/<int:ing_id>", methods=["DELETE"])
def api_delete_ingredient(ing_id: int):
    ok = db.delete_ingredient(ing_id)
    if not ok:
        return jsonify({"success": False, "error": "Không tìm thấy nguyên liệu."}), 404
    return jsonify({"success": True, "deletedId": ing_id})


@app.route("/api/ingredients/sync", methods=["PUT"])
def api_sync_ingredients():
    body = request.get_json(silent=True)
    ings_list = body.get("ingredients") if isinstance(body, dict) else body
    ings = db.sync_ingredients(ings_list or [])
    return jsonify({"success": True, "ingredients": ings})


# ============================================================
# COMMENTS & RATINGS API (UC07, UC21)
# ============================================================

@app.route("/api/comments", methods=["GET"])
def api_get_all_comments():
    comments = db.get_all_comments()
    return jsonify({"comments": comments, "total": len(comments)})


@app.route("/api/recipes/<int:recipe_id>/comments", methods=["GET"])
def api_get_recipe_comments(recipe_id: int):
    comments = db.get_comments_for_recipe(recipe_id)
    return jsonify({"comments": comments, "total": len(comments)})


@app.route("/api/recipes/<int:recipe_id>/comments", methods=["POST"])
def api_add_recipe_comment(recipe_id: int):
    body = request.get_json(silent=True) or {}
    user = _current_user()
    if user and not body.get("userId"):
        body["userId"] = user["id"]
        body["userName"] = user["name"]
        body["userAvatar"] = user["avatar"]
    created = db.add_comment(recipe_id, body)
    if not created:
        return jsonify({"success": False, "error": "Không thể gửi bình luận."}), 400
    return jsonify({"success": True, "comment": created}), 201


@app.route("/api/comments/<int:comment_id>", methods=["DELETE"])
def api_delete_comment(comment_id: int):
    ok = db.delete_comment(comment_id)
    if not ok:
        return jsonify({"success": False, "error": "Không tìm thấy bình luận."}), 404
    return jsonify({"success": True, "deletedId": comment_id})


# ============================================================
# FAVORITES API (UC13)
# ============================================================

@app.route("/api/favorites", methods=["GET"])
def api_get_favorites():
    user = _current_user()
    uid = user["id"] if user else request.args.get("userId")
    if not uid or not str(uid).isdigit():
        return jsonify({"favorites": [], "total": 0})
    favs = db.get_user_favorites(int(uid))
    return jsonify({"favorites": favs, "total": len(favs)})


@app.route("/api/favorites/toggle", methods=["POST"])
def api_toggle_favorite():
    body = request.get_json(silent=True) or {}
    user = _current_user()
    uid = body.get("userId") or (user["id"] if user else 1)
    recipe_id = body.get("recipeId")
    if not recipe_id:
        return jsonify({"success": False, "error": "Thiếu recipeId."}), 400
    result = db.toggle_favorite(int(uid), int(recipe_id))
    return jsonify({"success": True, **result})


# ============================================================
# ADMIN MANAGEMENT & STATISTICS API (UC15, UC20)
# ============================================================

@app.route("/api/admin/users", methods=["GET"])
def api_admin_get_users():
    users = db.get_all_users()
    return jsonify({"users": users, "total": len(users)})


@app.route("/api/admin/users/<int:user_id>/status", methods=["PUT"])
def api_admin_set_user_status(user_id: int):
    body = request.get_json(silent=True) or {}
    status = body.get("status", "active")
    updated = db.set_user_status(user_id, status)
    if not updated:
        return jsonify({"success": False, "error": "Không thể cập nhật trạng thái tài khoản."}), 400
    return jsonify({"success": True, "user": updated})


@app.route("/api/admin/statistics", methods=["GET"])
def api_admin_statistics():
    return jsonify(db.get_statistics())


@app.route("/api/admin/reset", methods=["POST"])
def api_admin_reset():
    db.init_db(force_reset=True)
    return jsonify({"success": True, "message": "Đã khôi phục cơ sở dữ liệu mặc định."})


# ============================================================
# COOKMATE CHEFBOT — AI CHATBOT API (3 FEATURE GROUPS)
# ============================================================

@app.route("/api/chatbot", methods=["POST"])
def api_chatbot():
    body = request.get_json(silent=True) or {}
    message = body.get("message", "")
    context = body.get("context") or {}
    result = ai_chatbot.generate_chatbot_response(message=message, context=context)
    return jsonify({"success": True, **result})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f" * CookMate Flask Server starting on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
