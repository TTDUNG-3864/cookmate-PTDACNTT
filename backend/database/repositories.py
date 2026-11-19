"""Parameterized MySQL repositories for CookMate's MVP workflows."""

from __future__ import annotations

import hmac
import json
import re
import hashlib
import secrets
import string
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from backend.database.connection import cursor, fetch_all, fetch_one, transaction
from backend.security.validators import clean_text

_SYNONYM_CACHE: dict[str, Any] = {"expires_at": 0.0, "mapping": {}}


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _format_utc_iso(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = str(value).strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?", raw):
        return raw.replace(" ", "T", 1) + "Z"
    return raw


class RecipeValidationError(ValueError):
    """Structured recipe validation error with machine-readable code and Vietnamese message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_FORBIDDEN_DEFAULT_IMAGE_PATTERNS = (
    "assets/images/categories/",
    "assets/images/placeholders/",
    "recipe-placeholder.svg",
    "mon-chinh.svg",
    "canh-sup.svg",
    "mon-xao.svg",
    "mon-nuong-chien.svg",
    "mon-chay.svg",
    "trang-mieng-banh.svg",
    "do-uong-sinh-to.svg",
    "khai-vi-goi-cuon.svg",
)

_UPLOADED_RECIPE_IMAGE_RE = re.compile(
    r"^/?static/uploads/recipes/[0-9a-fA-F-]{8,64}\.(?:jpg|jpeg|png|webp)$"
)

_HTTP_IMAGE_URL_RE = re.compile(
    r"^https?://(?:localhost|\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+)(?::\d{1,5})?(?:/[^\s]*)?$"
)


def validate_recipe_image_url(raw_url: Any) -> str:
    text = str(raw_url or "").strip()
    if not text:
        raise RecipeValidationError(
            "RECIPE_IMAGE_REQUIRED",
            "Vui lòng cung cấp URL ảnh hoặc tải ảnh từ thiết bị.",
        )
    if len(text) > 500 or any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in text):
        raise RecipeValidationError(
            "RECIPE_IMAGE_INVALID_URL",
            "URL hình ảnh không đúng định dạng hợp lệ.",
        )
    lowered = text.lower()
    if any(pat in lowered for pat in _FORBIDDEN_DEFAULT_IMAGE_PATTERNS):
        raise RecipeValidationError(
            "RECIPE_IMAGE_REQUIRED",
            "Vui lòng cung cấp URL ảnh hoặc tải ảnh từ thiết bị.",
        )
    if _UPLOADED_RECIPE_IMAGE_RE.fullmatch(text):
        return text.lstrip("/")
    if not _HTTP_IMAGE_URL_RE.fullmatch(text):
        raise RecipeValidationError(
            "RECIPE_IMAGE_INVALID_URL",
            "URL hình ảnh không đúng định dạng hợp lệ (cần bắt đầu bằng http:// hoặc https://).",
        )
    return text


def _user(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    must_change = bool(int(row.get("must_change_password") or 0))
    return {
        "id": int(row["user_id"]),
        "user_id": int(row["user_id"]),
        "name": row["full_name"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "status": row.get("status", "active"),
        "avatar": row.get("avatar_url") or "",
        "bio": row.get("bio") or "",
        "joinDate": str(row.get("created_at") or "")[:10],
        "recipeCount": int(row.get("recipe_count") or 0),
        "must_change_password": must_change,
        "mustChangePassword": must_change,
    }


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    row = fetch_one(
        "SELECT u.user_id,u.full_name,u.email,u.role,u.status,u.must_change_password,u.avatar_url,u.bio,u.created_at, "
        "(SELECT COUNT(*) FROM recipes r WHERE r.created_by=u.user_id) AS recipe_count "
        "FROM users u WHERE u.user_id=%s",
        (user_id,),
    )
    return _user(row)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    row = fetch_one(
        "SELECT user_id,full_name,email,password_hash,role,status,must_change_password,avatar_url,bio,created_at "
        "FROM users WHERE email=%s", (email.lower(),),
    )
    if not row:
        return None
    return {**(_user(row) or {}), "password_hash": row["password_hash"]}


def register_user(name: str, email: str, password: str) -> dict[str, Any]:
    name = clean_text(name, maximum=150, required=True)
    if len(password) < 8:
        raise ValueError("Mật khẩu cần có ít nhất 8 ký tự.")
    with transaction() as (_, cur):
        cur.execute(
            "INSERT INTO users(full_name,email,password_hash,role,status,must_change_password,created_at) "
            "VALUES(%s,%s,%s,'member','active',0,UTC_TIMESTAMP())",
            (name, email.lower(), generate_password_hash(password)),
        )
        user_id = cur.lastrowid
    return get_user_by_id(int(user_id))


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    row = fetch_one(
        "SELECT user_id,full_name,email,password_hash,role,status,must_change_password,avatar_url,bio,created_at "
        "FROM users WHERE email=%s", (email.lower(),),
    )
    if not row or not check_password_hash(row["password_hash"], password):
        return None
    if row["status"] != "active":
        raise PermissionError("Tài khoản đã bị vô hiệu hóa.")
    return get_user_by_id(int(row["user_id"]))


def update_user_profile(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = clean_text(payload.get("name"), maximum=150, required=True)
    bio = clean_text(payload.get("bio"), maximum=500)
    avatar = clean_text(payload.get("avatar"), maximum=500)
    with transaction() as (_, cur):
        cur.execute("UPDATE users SET full_name=%s,bio=%s,avatar_url=%s WHERE user_id=%s", (name, bio, avatar, user_id))
    return get_user_by_id(user_id)


def list_users() -> list[dict[str, Any]]:
    rows = fetch_all(
        "SELECT u.user_id,u.full_name,u.email,u.role,u.status,u.must_change_password,u.avatar_url,u.bio,u.created_at, "
        "(SELECT COUNT(*) FROM recipes r WHERE r.created_by=u.user_id) AS recipe_count "
        "FROM users u ORDER BY u.created_at DESC"
    )
    return [_user(row) for row in rows]


def set_user_status(user_id: int, status: str) -> dict[str, Any] | None:
    if status not in ("active", "inactive"):
        raise ValueError("Trạng thái tài khoản không hợp lệ.")
    with transaction() as (_, cur):
        cur.execute("UPDATE users SET status=%s WHERE user_id=%s", (status, user_id))
    return get_user_by_id(user_id)


def list_categories() -> list[dict[str, Any]]:
    rows = fetch_all(
        "SELECT c.category_id AS id,c.name,c.slug,c.icon,c.description,c.image_url AS image, "
        "COUNT(r.recipe_id) AS recipeCount FROM categories c "
        "LEFT JOIN recipes r ON r.category_id=c.category_id AND r.status='APPROVED' "
        "GROUP BY c.category_id ORDER BY c.category_id"
    )
    return rows


def list_ingredients() -> list[dict[str, Any]]:
    rows = fetch_all(
        "SELECT ingredient_id AS id,ingredient_name AS name,category,unit,calories,protein,fat,carbs,fiber, "
        "is_popular AS popular FROM ingredients ORDER BY is_popular DESC,ingredient_name"
    )
    return rows


def save_category(payload: dict[str, Any], category_id: int | None = None) -> dict[str, Any]:
    name=clean_text(payload.get("name"),maximum=120,required=True)
    slug=clean_text(payload.get("slug") or _slug_text(name),maximum=160,required=True)
    icon=clean_text(payload.get("icon") or "restaurant",maximum=80)
    description=clean_text(payload.get("description"),maximum=500)
    image=clean_text(payload.get("image") or payload.get("image_url"),maximum=500)
    with transaction() as (_,cur):
        if category_id:
            cur.execute("UPDATE categories SET name=%s,slug=%s,icon=%s,description=%s,image_url=%s WHERE category_id=%s",
                        (name,slug,icon,description,image,category_id))
            cur.execute("SELECT category_id FROM categories WHERE category_id=%s",(category_id,))
            if not cur.fetchone(): return None
            saved_id=category_id
        else:
            cur.execute("INSERT INTO categories(name,slug,icon,description,image_url) VALUES(%s,%s,%s,%s,%s)",
                        (name,slug,icon,description,image));saved_id=int(cur.lastrowid)
    return next((row for row in list_categories() if int(row["id"])==saved_id),None)


def delete_category(category_id: int) -> bool:
    with transaction() as (_,cur):
        cur.execute("DELETE FROM categories WHERE category_id=%s",(category_id,))
        return cur.rowcount>0


def sync_categories(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(values)>100: raise ValueError("Too many categories in one request.")
    with transaction() as (_,cur):
        for value in values:
            if not isinstance(value,dict): continue
            name=clean_text(value.get("name"),maximum=120,required=True)
            slug=clean_text(value.get("slug") or _slug_text(name),maximum=160,required=True)
            category_id=value.get("id")
            fields=(name,slug,clean_text(value.get("icon") or "restaurant",maximum=80),clean_text(value.get("description"),maximum=500),
                    clean_text(value.get("image") or value.get("image_url"),maximum=500))
            if category_id:
                cur.execute("INSERT INTO categories(category_id,name,slug,icon,description,image_url) VALUES(%s,%s,%s,%s,%s,%s) "
                            "ON DUPLICATE KEY UPDATE name=VALUES(name),slug=VALUES(slug),icon=VALUES(icon),description=VALUES(description),image_url=VALUES(image_url)",
                            (int(category_id),*fields))
            else:
                cur.execute("INSERT INTO categories(name,slug,icon,description,image_url) VALUES(%s,%s,%s,%s,%s) "
                            "ON DUPLICATE KEY UPDATE name=VALUES(name),icon=VALUES(icon),description=VALUES(description),image_url=VALUES(image_url)",fields)
    return list_categories()


def save_ingredient(payload: dict[str, Any], ingredient_id: int | None = None) -> dict[str, Any] | None:
    name=clean_text(payload.get("name") or payload.get("ingredient_name"),maximum=200,required=True)
    category=clean_text(payload.get("category") or "Khác",maximum=100)
    unit=clean_text(payload.get("unit") or "100g",maximum=30)
    with transaction() as (_,cur):
        values=(name,category,unit,_number(payload.get("calories")),_number(payload.get("protein")),_number(payload.get("fat")),
                _number(payload.get("carbs")),_number(payload.get("fiber")),bool(payload.get("popular",payload.get("is_popular",False))))
        if ingredient_id:
            cur.execute("UPDATE ingredients SET ingredient_name=%s,category=%s,unit=%s,calories=%s,protein=%s,fat=%s,carbs=%s,fiber=%s,is_popular=%s WHERE ingredient_id=%s",
                        (*values,ingredient_id))
            cur.execute("SELECT ingredient_id FROM ingredients WHERE ingredient_id=%s",(ingredient_id,))
            if not cur.fetchone():return None
            saved_id=ingredient_id
        else:
            cur.execute("INSERT INTO ingredients(ingredient_name,category,unit,calories,protein,fat,carbs,fiber,is_popular) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",values)
            saved_id=int(cur.lastrowid)
    return next((row for row in list_ingredients() if int(row["id"])==saved_id),None)


def delete_ingredient(ingredient_id: int) -> bool:
    with transaction() as (_,cur):
        cur.execute("DELETE FROM ingredients WHERE ingredient_id=%s",(ingredient_id,))
        return cur.rowcount>0


def sync_ingredients(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(values)>1000: raise ValueError("Too many ingredients in one request.")
    with transaction() as (_,cur):
        for value in values:
            if not isinstance(value,dict):continue
            name=clean_text(value.get("name") or value.get("ingredient_name"),maximum=200,required=True)
            vals=(name,clean_text(value.get("category") or "Khác",maximum=100),clean_text(value.get("unit") or "100g",maximum=30),
                  _number(value.get("calories")),_number(value.get("protein")),_number(value.get("fat")),_number(value.get("carbs")),
                  _number(value.get("fiber")),bool(value.get("popular",value.get("is_popular",False))))
            ingredient_id=value.get("id")
            if ingredient_id:
                cur.execute("INSERT INTO ingredients(ingredient_id,ingredient_name,category,unit,calories,protein,fat,carbs,fiber,is_popular) "
                            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE ingredient_name=VALUES(ingredient_name),category=VALUES(category),unit=VALUES(unit),calories=VALUES(calories),protein=VALUES(protein),fat=VALUES(fat),carbs=VALUES(carbs),fiber=VALUES(fiber),is_popular=VALUES(is_popular)",
                            (int(ingredient_id),*vals))
            else:
                cur.execute("INSERT INTO ingredients(ingredient_name,category,unit,calories,protein,fat,carbs,fiber,is_popular) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                            "ON DUPLICATE KEY UPDATE category=VALUES(category),unit=VALUES(unit),calories=VALUES(calories),protein=VALUES(protein),fat=VALUES(fat),carbs=VALUES(carbs),fiber=VALUES(fiber),is_popular=VALUES(is_popular)",vals)
    return list_ingredients()


def _recipe_query(
    where: str,
    params: tuple[Any, ...],
    limit: int = 500,
    *,
    include_details: bool = True,
    include_private: bool = False,
) -> list[dict[str, Any]]:
    rows = fetch_all(
        "SELECT r.*,c.name AS category_name,"
        "u.full_name AS author_name,u.avatar_url AS author_avatar,u.email AS author_email,u.role AS author_role,"
        "d.dish_name,d.slug AS dish_slug,d.thumbnail_url AS dish_thumbnail,"
        "d.cook_time_mins AS dish_cook_time,d.difficulty AS dish_difficulty "
        "FROM recipes r "
        "LEFT JOIN categories c ON c.category_id=r.category_id "
        "LEFT JOIN users u ON u.user_id=r.created_by "
        "LEFT JOIN dishes d ON d.dish_id=r.dish_id "
        + (where + " " if where else "")
        + "ORDER BY r.created_at DESC, r.recipe_id DESC LIMIT %s",
        (*params, limit),
    )
    return _hydrate_recipes_batch(rows, include_details=include_details, include_private=include_private)


def _hydrate_recipes_batch(
    rows: list[dict[str, Any]],
    *,
    include_details: bool = True,
    include_private: bool = False,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    recipe_ids = [int(row["recipe_id"]) for row in rows]
    placeholders = ",".join(["%s"] * len(recipe_ids))
    id_tuple = tuple(recipe_ids)

    ing_map: dict[int, list[dict[str, Any]]] = {rid: [] for rid in recipe_ids}
    seen_ing_keys: dict[int, set[Any]] = {rid: set() for rid in recipe_ids}
    for item in fetch_all(
        "SELECT ri.recipe_id,ri.ingredient_id AS ingredientId,ri.ingredient_name AS name,"
        "ri.amount,ri.unit,ri.note,ri.sort_order AS sortOrder,di.is_required AS isRequired "
        "FROM recipe_ingredients ri "
        "JOIN recipes r ON r.recipe_id=ri.recipe_id "
        "LEFT JOIN dish_ingredients di ON di.dish_id=r.dish_id AND di.ingredient_id=ri.ingredient_id "
        f"WHERE ri.recipe_id IN ({placeholders}) ORDER BY ri.sort_order,ri.id",
        id_tuple,
    ):
        rid = int(item.pop("recipe_id"))
        if item.get("isRequired") is not None:
            item["isRequired"] = bool(item["isRequired"])
        ing_map.setdefault(rid, []).append(item)
        if item.get("ingredientId"):
            seen_ing_keys.setdefault(rid, set()).add(int(item["ingredientId"]))
        seen_ing_keys.setdefault(rid, set()).add(str(item.get("name") or "").strip().lower())

    for ditem in fetch_all(
        "SELECT r.recipe_id,di.ingredient_id AS ingredientId,i.ingredient_name AS name,i.unit,di.is_required AS isRequired "
        "FROM recipes r JOIN dish_ingredients di ON di.dish_id=r.dish_id "
        "JOIN ingredients i ON i.ingredient_id=di.ingredient_id "
        f"WHERE r.recipe_id IN ({placeholders})",
        id_tuple,
    ):
        rid = int(ditem.pop("recipe_id"))
        iid = ditem.get("ingredientId")
        dname = str(ditem.get("name") or "").strip()
        keys = seen_ing_keys.setdefault(rid, set())
        if (iid and int(iid) in keys) or dname.lower() in keys:
            if ditem.get("isRequired") is not None:
                for existing_ing in ing_map.get(rid, []):
                    if existing_ing.get("isRequired") is None and (
                        (iid and existing_ing.get("ingredientId") == iid)
                        or str(existing_ing.get("name") or "").strip().lower() == dname.lower()
                    ):
                        existing_ing["isRequired"] = bool(ditem["isRequired"])
            continue
        ing_map.setdefault(rid, []).append({
            "ingredientId": iid,
            "name": dname,
            "amount": "",
            "unit": ditem.get("unit") or "g",
            "note": "",
            "isRequired": bool(ditem["isRequired"]) if ditem.get("isRequired") is not None else None,
        })
        if iid:
            keys.add(int(iid))
        keys.add(dname.lower())

    step_map: dict[int, list[dict[str, Any]]] = {rid: [] for rid in recipe_ids}
    for item in fetch_all(
        "SELECT recipe_id,step_order AS step,title,instruction AS description,duration_mins AS time,tip_note AS tip,image_url AS image "
        f"FROM recipe_steps WHERE recipe_id IN ({placeholders}) ORDER BY step_order",
        id_tuple,
    ):
        rid = int(item.pop("recipe_id"))
        step_map.setdefault(rid, []).append(item)

    comment_map: dict[int, list[dict[str, Any]]] = {rid: [] for rid in recipe_ids}
    source_map: dict[int, list[dict[str, Any]]] = {rid: [] for rid in recipe_ids}
    if include_details:
        for item in fetch_all(
            "SELECT recipe_id,comment_id AS id,user_id AS userId,user_name AS userName,user_avatar AS userAvatar,"
            f"rating,comment AS content,created_at AS createdAt FROM comments WHERE recipe_id IN ({placeholders}) "
            "ORDER BY created_at DESC",
            id_tuple,
        ):
            rid = int(item.pop("recipe_id"))
            item["createdAt"] = _format_utc_iso(item.get("createdAt"))
            if len(comment_map.setdefault(rid, [])) < 30:
                comment_map[rid].append(item)
        for item in fetch_all(
            "SELECT recipe_id,source_name AS name,source_url AS url,relevance_score AS relevance,fetched_at AS fetchedAt "
            f"FROM recipe_sources WHERE recipe_id IN ({placeholders}) ORDER BY relevance_score DESC",
            id_tuple,
        ):
            rid = int(item.pop("recipe_id"))
            item["fetchedAt"] = _format_utc_iso(item.get("fetchedAt"))
            source_map.setdefault(rid, []).append(item)

    hydrated: list[dict[str, Any]] = []
    for row in rows:
        recipe_id = int(row["recipe_id"])
        status = str(row.get("status") or "PENDING").lower()
        nutrition = {
            "calories": row.get("calories") or 0,
            "protein": float(row.get("protein") or 0),
            "carbs": float(row.get("carbs") or 0),
            "fat": float(row.get("fat") or 0),
            "fiber": float(row.get("fiber") or 0),
        }
        dish_obj = (
            {
                "id": int(row["dish_id"]),
                "name": row.get("dish_name") or row["title"],
                "slug": row.get("dish_slug") or "",
                "thumbnail": row.get("dish_thumbnail") or "",
                "cookTimeMins": int(row.get("dish_cook_time") or 0),
                "difficulty": row.get("dish_difficulty") or row.get("difficulty") or "Dễ",
            }
            if row.get("dish_id")
            else None
        )
        author_obj: dict[str, Any] = {
            "id": row.get("created_by"),
            "name": row.get("author_name") or "CookMate",
            "avatar": row.get("author_avatar") or "",
        }
        if include_private:
            author_obj["email"] = row.get("author_email") or ""
            author_obj["role"] = row.get("author_role") or "member"

        src_type = row.get("source_type") or "USER"
        sources_list = [
            {**src, "type": src.get("type") or src_type}
            for src in source_map.get(recipe_id, [])
        ]
        item_dict: dict[str, Any] = {
            "id": recipe_id,
            "dishId": row.get("dish_id"),
            "dish": dish_obj,
            "title": row["title"],
            "slug": row.get("slug") or "",
            "description": row.get("description") or "",
            "image": row.get("image_url") or "",
            "categoryId": row.get("category_id"),
            "categoryName": row.get("category_name") or "",
            "cuisine": row.get("cuisine") or "Món Việt",
            "prepTime": int(row.get("prep_time") or 0),
            "cookTime": int(row.get("cook_time") or 0),
            "totalTime": int(row.get("prep_time") or 0) + int(row.get("cook_time") or 0),
            "servings": int(row.get("servings") or 1),
            "difficulty": row.get("difficulty") or "Dễ",
            "calories": int(row.get("calories") or 0),
            "nutrition": nutrition,
            "rating": float(row.get("rating") or 0),
            "reviewCount": int(row.get("review_count") or 0),
            "views": int(row.get("views") or 0),
            "isFeatured": bool(row.get("is_featured")),
            "isNew": bool(row.get("is_new")),
            "occasion": row.get("occasion") or "",
            "holiday": row.get("occasion") or "",
            "tags": _json_value(row.get("tags_json"), []),
            "authorId": row.get("created_by"),
            "authorName": row.get("author_name") or "CookMate",
            "authorAvatar": row.get("author_avatar") or "",
            "author": author_obj,
            "createdAt": _format_utc_iso(row.get("created_at")),
            "created_at": _format_utc_iso(row.get("created_at")),
            "updatedAt": _format_utc_iso(row.get("updated_at")),
            "updated_at": _format_utc_iso(row.get("updated_at")),
            "status": status,
            "rejectionReason": row.get("rejection_reason") or "",
            "sourceType": src_type,
            "ingredients": ing_map.get(recipe_id, []),
            "steps": step_map.get(recipe_id, []),
            "comments": comment_map.get(recipe_id, []),
            "sources": sources_list,
        }
        if include_private:
            item_dict["authorEmail"] = row.get("author_email") or ""
        hydrated.append(item_dict)
    return hydrated


def _hydrate_recipe(row: dict[str, Any]) -> dict[str, Any]:
    return _hydrate_recipes_batch([row], include_details=True)[0]


_SEARCH_WORD_CHAR = r"0-9a-zA-ZÀ-ỹ"

_ANIMAL_QUERY_TERMS_NFC = (
    "ức gà", "đùi gà", "cánh gà", "chân gà", "thịt gà", "lòng gà", "phở gà", "cơm gà", "miến gà", "cháo gà", "súp gà",
    "thịt bò", "bắp bò", "gầu bò", "bò tơ", "bún bò", "phở bò", "bò kho", "bò xào", "bò né", "bò lúc lắc",
    "thịt heo", "thịt lợn", "ba chỉ", "ba rọi", "nạc vai", "sườn", "giò heo", "chân giò", "móng giò", "chả lụa", "giò sống", "bún chả", "nem rán", "chả giò", "thịt kho",
    "cá lóc", "cá quả", "cá chuối", "cá tràu", "cá trắm", "cá lăng", "cá ngừ", "cá thu", "cá hồi", "cá hú", "cá basa", "cá nục", "cá bống", "cá chép", "cá điêu hồng", "cá trê", "cá kèo", "cá kho", "chả cá",
    "tôm", "mực", "bạch tuộc", "cua", "ghẹ", "ốc", "nghêu", "ngao", "hến", "sò", "hàu", "lươn", "ếch", "sứa", "trâu",
    "vịt", "ngan", "chim cút", "trứng gà", "trứng vịt", "trứng cút", "mắm tôm", "mắm nêm", "mắm ruốc", "mắm tép", "nước mắm",
)

_ANIMAL_SINGLE_WORDS_NFC = ("gà", "bò", "heo", "lợn", "cá", "tôm", "mực", "cua", "ốc", "ếch", "vịt", "lươn", "trâu")

_ANIMAL_QUERY_TERMS_ASCII = (
    "uc ga", "dui ga", "canh ga", "chan ga", "thit ga", "long ga", "pho ga", "com ga", "mien ga", "chao ga", "sup ga",
    "thit bo", "bap bo", "gau bo", "bo to", "bun bo", "pho bo", "bo kho", "bo xao", "bo ne", "bo luc lac",
    "thit heo", "thit lon", "ba chi", "ba roi", "nac vai", "suon", "gio heo", "chan gio", "cha lua", "gio song", "bun cha", "nem ran", "cha gio", "thit kho",
    "ca loc", "ca qua", "ca chuoi", "ca trau", "ca tram", "ca lang", "ca ngu", "ca thu", "ca hoi", "ca hu", "ca basa", "ca nuc", "ca bong", "ca chep", "ca dieu hong", "ca kho", "cha ca",
    "tom", "muc", "bach tuoc", "cua", "ghe", "oc", "ngheu", "ngao", "hen", "hau", "luon", "ech", "trau",
    "vit", "ngan", "chim cut", "trung ga", "trung vit", "trung cut", "mam tom", "mam nem", "mam ruoc", "nuoc mam",
)

_REGIONAL_DISH_SYNONYMS_NFC: dict[str, list[str]] = {
    "bún chả quạt": ["bún chả hà nội", "bún chả nướng"],
    "bún chả nướng than": ["bún chả hà nội", "bún chả nướng"],
    "thịt kho hột vịt": ["thịt kho tàu", "thịt kho trứng"],
    "thịt kho riệu": ["thịt kho tàu"],
    "thịt kho trứng": ["thịt kho tàu", "thịt kho hột vịt"],
    "thịt kho tàu": ["thịt kho hột vịt", "thịt kho trứng"],
    "nem rán": ["chả giò", "nem cua bể", "chả ram"],
    "chả giò": ["nem rán", "chả ram"],
    "cá quả": ["cá lóc"],
    "cá chuối": ["cá lóc"],
    "cá tràu": ["cá lóc"],
    "tào phớ": ["tàu hũ nước đường", "tàu hũ", "đậu hũ non"],
    "tàu hũ nước đường": ["tào phớ", "tàu hũ"],
    "phở hai tô": ["phở khô gia lai"],
    "bánh xèo huế": ["bánh khoái"],
    "bánh xèo miền trung": ["bánh khoái"],
    "bánh cuốn nghệ an": ["bánh mướt"],
    "củ nén": ["hành tăm"],
    "mộc nhĩ": ["nấm mèo"],
    "nấm mèo": ["mộc nhĩ"],
    "ba rọi": ["ba chỉ", "thịt ba chỉ"],
    "thịt ba rọi": ["thịt ba chỉ", "ba chỉ"],
    "thịt lợn": ["thịt heo"],
    "bột ngô": ["bột bắp"],
}

_REGIONAL_DISH_SYNONYMS_ASCII: dict[str, list[str]] = {
    "bun cha quat": ["bun cha ha noi", "bun cha nuong"],
    "bun cha nuong than": ["bun cha ha noi", "bun cha nuong"],
    "thit kho hot vit": ["thit kho tau", "thit kho trung"],
    "thit kho rieu": ["thit kho tau"],
    "thit kho trung": ["thit kho tau", "thit kho hot vit"],
    "thit kho tau": ["thit kho hot vit", "thit kho trung"],
    "nem ran": ["cha gio", "nem cua be", "cha ram"],
    "cha gio": ["nem ran", "cha ram"],
    "ca qua": ["ca loc"],
    "ca chuoi": ["ca loc"],
    "ca trau": ["ca loc"],
    "tao pho": ["tau hu nuoc duong", "tau hu", "dau hu non"],
    "tau hu nuoc duong": ["tao pho", "tau hu"],
    "pho hai to": ["pho kho gia lai"],
    "banh xeo hue": ["banh khoai"],
    "banh xeo mien trung": ["banh khoai"],
    "banh cuon nghe an": ["banh muot"],
    "cu nen": ["hanh tam"],
    "moc nhi": ["nam meo"],
    "nam meo": ["moc nhi"],
    "ba roi": ["ba chi", "thit ba chi"],
    "thit ba roi": ["thit ba chi", "ba chi"],
    "thit lon": ["thit heo"],
    "bot ngo": ["bot bap"],
}

_CONTIGUOUS_PHRASES_ASCII = {
    "uc ga", "dui ga", "chan ga", "thit ga", "nam dui ga", "trung ga", "trung vit", "trung cut",
    "thit bo", "bap bo", "bun bo", "pho bo", "pho ga", "bo kho",
    "thit heo", "thit lon", "ba chi", "ba roi", "nac vai",
    "ca loc", "ca thu", "ca hoi", "ca hu", "ca basa", "ca nuc", "ca bong", "ca chep", "ca dieu hong",
    "ca chua", "ca tim", "ca rot", "ca phe", "ca ri",
    "dau hu", "dau phu", "tau hu", "sua chua", "banh flan", "goi cuon", "cha gio",
}


def _norm_nfc_words(text: str) -> str:
    s = unicodedata.normalize("NFC", str(text or "")).lower().strip()
    s = re.sub(rf"[^{_SEARCH_WORD_CHAR}]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_ascii_search(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).lower().replace("đ", "d")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _has_whole_phrase(haystack: str, needle: str, *, is_ascii: bool = False) -> bool:
    if not haystack or not needle:
        return False
    cls = r"a-z0-9" if is_ascii else _SEARCH_WORD_CHAR
    return bool(re.search(rf"(?<![{cls}]){re.escape(needle)}(?![{cls}])", haystack))


def _expand_ingredient_aliases_nfc(raw_name: str) -> list[str]:
    n = _norm_nfc_words(raw_name)
    if not n:
        return []
    out = [n]
    raw_low = unicodedata.normalize("NFC", str(raw_name or "")).lower().strip()
    # Parenthesized cut expansions: "thịt gà (ức)" -> "ức gà", "thịt ức gà", "thịt gà" (NEVER "đùi gà"!)
    m = re.match(r"^thịt\s+gà\s*\(\s*([^)]+)\s*\)$", raw_low)
    if m:
        cut = _norm_nfc_words(m.group(1))
        if cut:
            out.extend([f"{cut} gà", f"thịt {cut} gà", "thịt gà"])
    elif n in ("cánh gà", "chân gà", "đùi gà", "ức gà"):
        out.append("thịt gà")

    m_heo = re.match(r"^thịt\s+heo\s*\(\s*([^)]+)\s*\)$", raw_low)
    if m_heo:
        cut = _norm_nfc_words(m_heo.group(1))
        if cut:
            out.extend([cut, f"thịt {cut}", "thịt heo", "thịt lợn"])
    elif "thịt ba chỉ" in n or n == "ba chỉ":
        out.extend(["ba chỉ", "ba rọi", "thịt ba chỉ", "thịt heo", "thịt lợn"])
    elif "thịt heo xay" in n:
        out.extend(["thịt băm", "thịt bằm", "thịt xay", "thịt heo", "thịt lợn"])
    elif "sườn" in n and "chay" not in n:
        out.extend(["sườn", "sườn heo", "thịt heo"])

    if n in ("bắp bò", "gầu bò", "thăn bò", "nạm bò"):
        out.append("thịt bò")
    if "đậu hũ" in n:
        out.append(n.replace("đậu hũ", "đậu phụ"))
    elif "đậu phụ" in n:
        out.append(n.replace("đậu phụ", "đậu hũ"))
    if n in ("tôm sú", "tôm tươi", "tôm thẻ", "tôm đất"):
        out.append("tôm")
    return list(dict.fromkeys(x for x in out if x))


def _query_requests_animal_without_vegan(q_nfc: str, q_ascii: str, has_diacritics: bool) -> bool:
    if _has_whole_phrase(q_nfc, "chay") or _has_whole_phrase(q_ascii, "chay", is_ascii=True) or "vegan" in q_ascii:
        return False
    if has_diacritics:
        for term in _ANIMAL_QUERY_TERMS_NFC:
            if _has_whole_phrase(q_nfc, term):
                return True
        for sw in _ANIMAL_SINGLE_WORDS_NFC:
            if _has_whole_phrase(q_nfc, sw):
                return True
        return False

    # Accentless query: guard against "ca chua", "ca tim", "ca rot", "ca phe", "ca ri", "sinh to bo", "qua bo"
    masked = q_ascii
    for non_fish in ("ca chua", "ca tim", "ca rot", "ca phe", "ca ri", "cacao", "sinh to bo", "qua bo", "trai bo", "bo lat"):
        masked = re.sub(rf"(?<![a-z0-9]){re.escape(non_fish)}(?![a-z0-9])", " ", masked)
    masked = re.sub(r"\s+", " ", masked).strip()
    for term in _ANIMAL_QUERY_TERMS_ASCII:
        if _has_whole_phrase(masked, term, is_ascii=True):
            return True
    for sw in ("ga", "bo", "heo", "lon", "ca", "tom", "muc", "cua", "oc", "ech", "vit", "luon"):
        if _has_whole_phrase(masked, sw, is_ascii=True):
            return True
    return False


def _mask_candidate_false_friends(text: str, q_ascii: str, *, is_ascii: bool) -> str:
    if not text:
        return ""
    out = text
    wants_mushroom = _has_whole_phrase(q_ascii, "nam", is_ascii=True)
    wants_egg = _has_whole_phrase(q_ascii, "trung", is_ascii=True)
    wants_broth = _has_whole_phrase(q_ascii, "nuoc dung", is_ascii=True)

    if not wants_mushroom:
        if is_ascii:
            out = re.sub(r"(?<![a-z0-9])nam dui ga(?![a-z0-9])", "nam", out)
        else:
            out = re.sub(rf"(?<![{_SEARCH_WORD_CHAR}])nấm đùi gà(?![{_SEARCH_WORD_CHAR}])", "nấm", out)
    if not wants_egg:
        if is_ascii:
            out = re.sub(r"(?<![a-z0-9])trung ga(?![a-z0-9])", "trung", out)
        else:
            out = re.sub(rf"(?<![{_SEARCH_WORD_CHAR}])trứng gà(?![{_SEARCH_WORD_CHAR}])", "trứng", out)
    if not wants_broth:
        if is_ascii:
            out = re.sub(r"(?<![a-z0-9])nuoc dung ga(?![a-z0-9])", "nuoc dung", out)
        else:
            out = re.sub(rf"(?<![{_SEARCH_WORD_CHAR}])nước dùng gà(?![{_SEARCH_WORD_CHAR}])", "nước dùng", out)

    if is_ascii:
        # Prevent accentless "ca" from matching "ca chua / ca tim / ca rot / ca phe / ca ri"
        if _has_whole_phrase(q_ascii, "ca", is_ascii=True) and not any(
            _has_whole_phrase(q_ascii, p, is_ascii=True) for p in ("ca chua", "ca tim", "ca rot", "ca phe", "ca ri")
        ):
            for non_fish in ("ca chua", "ca tim", "ca rot", "ca phe", "ca ri"):
                out = re.sub(rf"(?<![a-z0-9]){re.escape(non_fish)}(?![a-z0-9])", "rau", out)
        # Prevent accentless "bo" from matching butter/avocado/leek when user didn't ask for them
        if _has_whole_phrase(q_ascii, "bo", is_ascii=True) and not any(
            _has_whole_phrase(q_ascii, p, is_ascii=True) for p in ("bo lat", "qua bo", "trai bo", "sinh to bo", "banh bo")
        ):
            for non_beef in ("bo lat", "qua bo", "trai bo", "sinh to bo", "hanh boaro", "banh bo"):
                out = re.sub(rf"(?<![a-z0-9]){re.escape(non_beef)}(?![a-z0-9])", "thucpham", out)
    return re.sub(r"\s+", " ", out).strip()


def score_recipe_search(recipe: dict[str, Any], query: str) -> int:
    """
    Exact Vietnamese diacritic-aware & whole-word recipe relevance scorer:
      100 -> Exact phrase in recipe title
       85 -> Exact phrase (or all tokens of cut/species) in a recipe ingredient
       60 -> All query tokens (AND) match whole-words across title + ingredients + tags
        0 -> Excluded / non-matching
    """
    q_nfc = _norm_nfc_words(query)
    q_ascii = _norm_ascii_search(query)
    if not q_nfc or not q_ascii:
        return 1

    has_diacritics = (q_nfc != q_ascii)
    q_phrase = q_nfc if has_diacritics else q_ascii
    q_tokens = q_phrase.split()

    cat_id = int(recipe.get("categoryId") or recipe.get("category_id") or 0)
    cat_name_ascii = _norm_ascii_search(recipe.get("categoryName") or recipe.get("category_name") or "")
    title_raw = str(recipe.get("title") or "")
    title_ascii_raw = _norm_ascii_search(title_raw)
    is_vegan_recipe = (
        cat_id == 5
        or "chay" in cat_name_ascii
        or _has_whole_phrase(title_ascii_raw, "chay", is_ascii=True)
    )

    # Strict Category 5 / Vegan exclusion when searching animal ingredients without "chay"
    if is_vegan_recipe and _query_requests_animal_without_vegan(q_nfc, q_ascii, has_diacritics):
        return 0

    norm_fn = _norm_nfc_words if has_diacritics else _norm_ascii_search
    is_asc = not has_diacritics

    title_norm = _mask_candidate_false_friends(norm_fn(title_raw), q_ascii, is_ascii=is_asc)

    ing_aliases: list[str] = []
    for ing in recipe.get("ingredients") or []:
        iname = ing.get("name") or ing.get("ingredient_name") or ""
        for alias_nfc in _expand_ingredient_aliases_nfc(iname):
            # Do not expand chicken broth ("nước dùng gà") as chicken meat when searching chicken cuts/meat
            if alias_nfc == "nước dùng gà" and q_ascii in ("ga", "thit ga", "uc ga", "dui ga", "canh ga"):
                continue
            cand = norm_fn(alias_nfc) if not has_diacritics else alias_nfc
            masked_cand = _mask_candidate_false_friends(cand, q_ascii, is_ascii=is_asc)
            if masked_cand:
                ing_aliases.append(masked_cand)

    tags_list = recipe.get("tags") or []
    tags_norm = _mask_candidate_false_friends(
        norm_fn(" ".join(str(t) for t in tags_list)),
        q_ascii,
        is_ascii=is_asc,
    )

    # Rank 1 (100): Exact whole-word phrase in title
    if _has_whole_phrase(title_norm, q_phrase, is_ascii=is_asc):
        return 100

    # Handle bidirectional đậu hũ <-> đậu phụ and regional dish/ingredient synonyms
    alt_phrases = [q_phrase]
    if "đậu hũ" in q_phrase:
        alt_phrases.append(q_phrase.replace("đậu hũ", "đậu phụ"))
    elif "đậu phụ" in q_phrase:
        alt_phrases.append(q_phrase.replace("đậu phụ", "đậu hũ"))
    elif "dau hu" in q_phrase:
        alt_phrases.append(q_phrase.replace("dau hu", "dau phu"))
    elif "dau phu" in q_phrase:
        alt_phrases.append(q_phrase.replace("dau phu", "dau hu"))

    syn_dict = _REGIONAL_DISH_SYNONYMS_NFC if has_diacritics else _REGIONAL_DISH_SYNONYMS_ASCII
    for src_term, targets in syn_dict.items():
        if _has_whole_phrase(q_phrase, src_term, is_ascii=is_asc):
            for tgt in targets:
                replaced = re.sub(
                    rf"(?<![{'a-z0-9' if is_asc else _SEARCH_WORD_CHAR}]){re.escape(src_term)}(?![{'a-z0-9' if is_asc else _SEARCH_WORD_CHAR}])",
                    tgt,
                    q_phrase,
                ).strip()
                if replaced and replaced not in alt_phrases:
                    alt_phrases.append(replaced)
                if q_phrase == src_term and tgt not in alt_phrases:
                    alt_phrases.append(tgt)

    for ap in alt_phrases:
        if _has_whole_phrase(title_norm, ap, is_ascii=is_asc):
            return 100

    # Rank 2 (85): Exact whole-word phrase inside an ingredient alias
    for alias in ing_aliases:
        for ap in alt_phrases:
            if _has_whole_phrase(alias, ap, is_ascii=is_asc):
                return 85
        if len(q_tokens) >= 2 and q_ascii not in ("uc ga", "dui ga", "canh ga", "chan ga"):
            if all(_has_whole_phrase(alias, tok, is_ascii=is_asc) for tok in q_tokens):
                return 85

    # If the query is a specific indivisible cut/noun phrase (like "ức gà", "đùi gà", "cá lóc", "trứng gà"),
    # do NOT allow scattered token matching across unrelated fields!
    if q_ascii in _CONTIGUOUS_PHRASES_ASCII:
        for ap in alt_phrases:
            if _has_whole_phrase(tags_norm, ap, is_ascii=is_asc):
                return 60
        return 0

    # If query contains a contiguous sub-phrase (e.g. "ức gà áp chảo"), require that sub-phrase in title or ingredients
    for cp in _CONTIGUOUS_PHRASES_ASCII:
        if _has_whole_phrase(q_ascii, cp, is_ascii=True):
            # Verify contiguous sub-phrase is satisfied in title or ingredients
            cp_check = cp
            if has_diacritics:
                # Extract corresponding accented sub-phrase if present
                idx_toks = q_ascii.split()
                cp_toks = cp.split()
                for i in range(len(idx_toks) - len(cp_toks) + 1):
                    if idx_toks[i:i + len(cp_toks)] == cp_toks:
                        cp_check = " ".join(q_tokens[i:i + len(cp_toks)])
                        break
            if not (
                _has_whole_phrase(title_norm, cp_check, is_ascii=is_asc)
                or any(_has_whole_phrase(a, cp_check, is_ascii=is_asc) for a in ing_aliases)
            ):
                return 0

    # Rank 3 (60): ALL query tokens match whole-words across title + ingredients + tags (strict AND)
    combined = f"{title_norm} {' '.join(ing_aliases)} {tags_norm}".strip()
    if all(_has_whole_phrase(combined, tok, is_ascii=is_asc) for tok in q_tokens):
        return 60

    return 0


def list_recipes(filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    filters = filters or {}
    clauses = ["r.status='APPROVED'"]
    params: list[Any] = []
    if filters.get("category_id"):
        clauses.append("r.category_id=%s"); params.append(filters["category_id"])
    if filters.get("occasion"):
        clauses.append("r.occasion LIKE %s"); params.append(f"%{filters['occasion']}%")
    if filters.get("difficulty"):
        clauses.append("r.difficulty=%s"); params.append(filters["difficulty"])
    if filters.get("max_time"):
        clauses.append("(r.prep_time+r.cook_time)<=%s"); params.append(filters["max_time"])
    if filters.get("featured") is not None:
        clauses.append("r.is_featured=%s"); params.append(int(bool(filters["featured"])))
    if filters.get("dish_id"):
        clauses.append("r.dish_id=%s"); params.append(filters["dish_id"])
    include_details = bool(filters.get("include_details", False))
    raw_q = str(filters.get("q") or "").strip()
    req_limit = int(filters.get("limit") or 500)
    rows = _recipe_query(
        "WHERE " + " AND ".join(clauses),
        tuple(params),
        500 if raw_q else req_limit,
        include_details=include_details,
    )
    if not raw_q:
        return rows
    scored: list[tuple[int, float, int, dict[str, Any]]] = []
    for item in rows:
        sc = score_recipe_search(item, raw_q)
        if sc > 0:
            item["relevanceScore"] = sc
            scored.append((sc, float(item.get("rating") or 0), int(item.get("id") or 0), item))
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return [t[3] for t in scored[:req_limit]]


def get_recipe(recipe_id: int, *, include_private: bool = False) -> dict[str, Any] | None:
    where = "WHERE r.recipe_id=%s" if include_private else "WHERE r.recipe_id=%s AND r.status='APPROVED'"
    rows = _recipe_query(where, (recipe_id,), 1, include_details=True, include_private=include_private)
    return rows[0] if rows else None


def search_chatbot_recipes(
    ingredient_ids: list[int],
    ingredient_names: list[str],
    title_terms: list[str],
    *,
    recipe_id: int | None = None,
    excluded_ingredient_ids: list[int] | None = None,
    excluded_ingredient_names: list[str] | None = None,
    ingredient_groups: list[dict[str, Any]] | None = None,
    category_hint: int | None = None,
    vegan_only: bool = False,
    has_animal_group: bool = False,
    max_calories: int | None = None,
    high_protein: bool = False,
    pantry_names_ascii: set[str] | None = None,
    use_funnel: bool = False,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return approved recipes grounded in catalog ingredients and stored steps."""
    if use_funnel or ingredient_groups is not None:
        funnel_rows, tier = search_chatbot_funnel(
            ingredient_groups or [],
            title_terms,
            recipe_id=recipe_id,
            category_hint=category_hint,
            vegan_only=vegan_only,
            has_animal_group=has_animal_group,
            max_calories=max_calories,
            high_protein=high_protein,
            excluded_ingredient_ids=excluded_ingredient_ids,
            excluded_ingredient_names=excluded_ingredient_names,
            pantry_names_ascii=pantry_names_ascii,
            limit=limit,
        )
        for item in funnel_rows:
            item["funnelTier"] = tier
        return funnel_rows
    ids = sorted({int(value) for value in ingredient_ids if str(value).isdigit()})
    names = sorted({str(value).strip().lower() for value in ingredient_names if str(value).strip()})
    excluded_ids = sorted({int(value) for value in (excluded_ingredient_ids or []) if str(value).isdigit()})
    excluded_names = sorted({str(value).strip().lower() for value in (excluded_ingredient_names or []) if str(value).strip()})
    terms = sorted({str(value).strip().lower() for value in title_terms if str(value).strip()})

    def ingredient_match(alias: str = "ri") -> tuple[str, list[Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if ids:
            clauses.append(f"{alias}.ingredient_id IN ({','.join(['%s'] * len(ids))})")
            values.extend(ids)
        if names:
            clauses.append("(" + " OR ".join(f"LOWER({alias}.ingredient_name) LIKE %s" for _ in names) + ")")
            values.extend(f"%{name}%" for name in names)
        return ("(" + " OR ".join(clauses) + ")" if clauses else "0=1"), values

    match_sql, match_params = ingredient_match()
    title_sql = " OR ".join("LOWER(r.title) LIKE %s" for _ in terms) or "0=1"
    title_params = [f"%{term}%" for term in terms]
    recipe_filter_clause = " OR r.recipe_id=%s" if recipe_id else ""
    where_sql = f"({match_sql} OR {title_sql}{recipe_filter_clause})"
    candidate_params = [*match_params, *title_params]
    if recipe_id:
        candidate_params.append(int(recipe_id))
    exclusion_sql = ""
    exclusion_params: list[Any] = []
    excluded_clauses: list[str] = []
    if excluded_ids:
        excluded_clauses.append(f"rx.ingredient_id IN ({','.join(['%s'] * len(excluded_ids))})")
        exclusion_params.extend(excluded_ids)
    if excluded_names:
        excluded_clauses.append("(" + " OR ".join("LOWER(rx.ingredient_name) LIKE %s" for _ in excluded_names) + ")")
        exclusion_params.extend(f"%{name}%" for name in excluded_names)
    if excluded_clauses:
        exclusion_sql = " AND NOT EXISTS (SELECT 1 FROM recipe_ingredients rx WHERE rx.recipe_id=r.recipe_id AND (" + " OR ".join(excluded_clauses) + "))"

    matched_count_sql = f"COUNT(DISTINCT CASE WHEN {match_sql} THEN ri.id END)" if ids or names else "0"
    rows = fetch_all(
        "SELECT r.recipe_id AS id,r.dish_id,r.category_id,r.title,r.description,r.image_url AS image,"
        "r.prep_time,r.cook_time,r.difficulty,r.servings,r.calories,r.protein,r.carbs,r.fat,r.fiber,r.rating,"
        f"{matched_count_sql} AS matched_ingredients,COUNT(DISTINCT ri.id) AS total_ingredients "
        "FROM recipes r JOIN recipe_ingredients ri ON ri.recipe_id=r.recipe_id "
        f"WHERE r.status='APPROVED' AND {where_sql}{exclusion_sql} "
        "GROUP BY r.recipe_id ORDER BY matched_ingredients DESC,r.rating DESC,r.recipe_id DESC LIMIT %s",
        (*match_params, *candidate_params, *exclusion_params, max(1, min(int(limit), 8))),
    )
    return _hydrate_chatbot_rows(rows)


def _hydrate_chatbot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    results: list[dict[str, Any]] = []
    for row in rows:
        recipe_id = int(row["id"])
        ingredients = fetch_all(
            "SELECT ri.ingredient_id AS id,ri.ingredient_name AS name,ri.amount,ri.unit,ri.note,"
            "i.category,di.is_required AS dish_required "
            "FROM recipe_ingredients ri LEFT JOIN ingredients i ON i.ingredient_id=ri.ingredient_id "
            "JOIN recipes r ON r.recipe_id=ri.recipe_id "
            "LEFT JOIN dish_ingredients di ON di.dish_id=r.dish_id AND di.ingredient_id=ri.ingredient_id "
            "WHERE ri.recipe_id=%s ORDER BY ri.sort_order,ri.id",
            (recipe_id,),
        )
        seen_ids = {int(i["id"]) for i in ingredients if i.get("id") is not None}
        seen_names = {str(i.get("name") or "").strip().lower() for i in ingredients}
        dish_extra = fetch_all(
            "SELECT di.ingredient_id AS id,i.ingredient_name AS name,'' AS amount,i.unit,'' AS note,"
            "i.category,di.is_required AS dish_required "
            "FROM recipes r JOIN dish_ingredients di ON di.dish_id=r.dish_id "
            "JOIN ingredients i ON i.ingredient_id=di.ingredient_id "
            "WHERE r.recipe_id=%s",
            (recipe_id,),
        )
        for dx in dish_extra:
            dx_id = dx.get("id")
            dx_name = str(dx.get("name") or "").strip().lower()
            if (dx_id is not None and int(dx_id) in seen_ids) or dx_name in seen_names:
                continue
            ingredients.append(dx)
            if dx_id is not None:
                seen_ids.add(int(dx_id))
            seen_names.add(dx_name)

        steps = fetch_all(
            "SELECT step_order AS step,title,instruction AS description,duration_mins AS duration,tip_note AS tip "
            "FROM recipe_steps WHERE recipe_id=%s ORDER BY step_order",
            (recipe_id,),
        )
        prep_t = int(row.get("prep_time") or 0)
        cook_t = int(row.get("cook_time") or 0)
        cal_val = int(row.get("calories") or 0)
        nutrition = {
            "calories": cal_val,
            "protein": float(row.get("protein") or 0),
            "carbs": float(row.get("carbs") or 0),
            "fat": float(row.get("fat") or 0),
            "fiber": float(row.get("fiber") or 0),
        }
        results.append({
            "id": recipe_id,
            "categoryId": int(row.get("category_id") or 0),
            "title": row["title"],
            "description": row.get("description") or "",
            "image": row.get("image") or "",
            "prepTime": prep_t,
            "cookTime": cook_t,
            "totalTime": prep_t + cook_t,
            "difficulty": row.get("difficulty") or "Dễ",
            "servings": int(row.get("servings") or 1),
            "calories": cal_val,
            "rating": float(row.get("rating") or 0),
            "ingredients": ingredients,
            "steps": steps,
            "nutrition": nutrition if any(float(value or 0) > 0 for value in nutrition.values()) else None,
            "matched_ingredients": int(row.get("matched_ingredients") or 0),
            "total_ingredients": int(row.get("total_ingredients") or len(ingredients)),
            "status": "APPROVED",
        })
    return results


def search_chatbot_funnel(
    ingredient_groups: list[dict[str, Any]],
    title_terms: list[str],
    *,
    recipe_id: int | None = None,
    category_hint: int | None = None,
    vegan_only: bool = False,
    has_animal_group: bool = False,
    max_calories: int | None = None,
    high_protein: bool = False,
    excluded_ingredient_ids: list[int] | None = None,
    excluded_ingredient_names: list[str] | None = None,
    pantry_names_ascii: set[str] | None = None,
    limit: int = 3,
) -> tuple[list[dict[str, Any]], str]:
    """
    4-Tier MySQL Funnel (100% APPROVED database records, zero non-DB guessing):
      Tier 1 ('direct_title')            : Direct context recipe_id or exact dish title match
      Tier 2 ('full_group_intersection') : Single recipe satisfying ALL user core OR-groups
      Tier 3 ('multi_dish_pairing')      : 2-3 real MySQL dishes covering user's OR-groups together
      Tier 4 ('top_category_fallback')   : Top MySQL dishes by category/calorie/protein/rating
    """
    excl_ids = {int(v) for v in (excluded_ingredient_ids or []) if str(v).isdigit()}
    excl_names_asc = {_norm_ascii_search(str(v)) for v in (excluded_ingredient_names or []) if str(v).strip()}
    pantry_asc = pantry_names_ascii or set()

    # Load all APPROVED recipes + union(recipe_ingredients, dish_ingredients) in 2 fast queries
    base_rows = fetch_all(
        "SELECT r.recipe_id AS id,r.dish_id,r.category_id,r.title,r.description,r.image_url AS image,"
        "r.prep_time,r.cook_time,r.difficulty,r.servings,r.calories,r.protein,r.carbs,r.fat,r.fiber,"
        "r.rating,r.is_featured "
        "FROM recipes r WHERE r.status='APPROVED' ORDER BY r.is_featured DESC,r.rating DESC,r.recipe_id ASC"
    )
    if not base_rows:
        return [], "empty_db"

    union_links = fetch_all(
        "SELECT ri.recipe_id,ri.ingredient_id,ri.ingredient_name AS name "
        "FROM recipe_ingredients ri JOIN recipes r ON r.recipe_id=ri.recipe_id WHERE r.status='APPROVED' "
        "UNION "
        "SELECT r.recipe_id,di.ingredient_id,i.ingredient_name AS name "
        "FROM recipes r JOIN dish_ingredients di ON di.dish_id=r.dish_id "
        "JOIN ingredients i ON i.ingredient_id=di.ingredient_id WHERE r.status='APPROVED'"
    )
    ing_by_recipe: dict[int, list[tuple[int | None, str, str]]] = {}
    for lk in union_links:
        rid = int(lk["recipe_id"])
        iid = int(lk["ingredient_id"]) if lk.get("ingredient_id") is not None else None
        nm = str(lk.get("name") or "").strip()
        ing_by_recipe.setdefault(rid, []).append((iid, nm, _norm_ascii_search(nm)))

    def _is_allowed(row: dict[str, Any]) -> bool:
        rid = int(row["id"])
        cat_id = int(row.get("category_id") or 0)
        title_asc = _norm_ascii_search(row.get("title") or "")
        is_veg = cat_id == 5 or _has_whole_phrase(title_asc, "chay", is_ascii=True)
        if vegan_only and not is_veg:
            return False
        if has_animal_group and not vegan_only and is_veg:
            return False
        for iid, _, nm_asc in ing_by_recipe.get(rid, []):
            if iid is not None and iid in excl_ids:
                return False
            if excl_names_asc and any(_has_whole_phrase(nm_asc, ex, is_ascii=True) for ex in excl_names_asc):
                return False
        return True

    allowed_rows = [r for r in base_rows if _is_allowed(r)]
    if not allowed_rows:
        allowed_rows = base_rows

    def _matched_group_indices(row: dict[str, Any]) -> tuple[set[int], int]:
        rid = int(row["id"])
        r_ings = ing_by_recipe.get(rid, [])
        non_pantry_total = sum(1 for _, _, na in r_ings if na and na not in pantry_asc)
        hit_groups: set[int] = set()
        for g_idx, grp in enumerate(ingredient_groups):
            g_ids: set[int] = set(grp.get("ids") or set())
            g_names_asc: set[str] = {_norm_ascii_search(n) for n in (grp.get("names") or set()) if n}
            for iid, _, nm_asc in r_ings:
                if (iid is not None and iid in g_ids) or (nm_asc in g_names_asc):
                    hit_groups.add(g_idx)
                    break
        return hit_groups, max(1, non_pantry_total)

    # TIER 1: Direct context recipe_id OR direct title match (when user names a dish)
    if recipe_id:
        ctx_hit = [r for r in allowed_rows if int(r["id"]) == int(recipe_id)]
        if ctx_hit and not ingredient_groups:
            return _hydrate_chatbot_rows(ctx_hit[:1]), "direct_title"

    clean_terms = [_norm_ascii_search(t) for t in title_terms if len(_norm_ascii_search(t)) >= 5 and " " in _norm_ascii_search(t)]
    if clean_terms and len(ingredient_groups) <= 1:
        t1_scored: list[tuple[int, float, dict[str, Any]]] = []
        for r in allowed_rows:
            t_asc = _norm_ascii_search(r["title"])
            best = 0
            for ct in clean_terms:
                if _has_whole_phrase(t_asc, ct, is_ascii=True):
                    best = max(best, 100 + len(ct))
            if best > 0:
                t1_scored.append((best, float(r.get("rating") or 0), r))
        if t1_scored:
            t1_scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
            chosen = [x[2] for x in t1_scored[:max(1, limit)]]
            return _hydrate_chatbot_rows(chosen), "direct_title"

    # TIER 2: Full intersection of ALL user core ingredient OR-groups (matched_groups == len(groups))
    if ingredient_groups:
        n_groups = len(ingredient_groups)
        t2_candidates: list[tuple[float, dict[str, Any]]] = []
        partial_candidates: list[tuple[int, float, set[int], dict[str, Any]]] = []
        for r in allowed_rows:
            hit_set, non_pantry_cnt = _matched_group_indices(r)
            if not hit_set:
                continue
            t_asc = _norm_ascii_search(r["title"])
            title_bonus = sum(
                0.35
                for grp in ingredient_groups
                if any(_has_whole_phrase(t_asc, kw, is_ascii=True) for kw in (grp.get("title_keywords") or []))
            )
            cat_bonus = 0.25 if (category_hint and int(r.get("category_id") or 0) == int(category_hint)) else 0.0
            cal_bonus = 0.20 if (max_calories and int(r.get("calories") or 999) <= max_calories) else 0.0
            coverage = len(hit_set) / non_pantry_cnt
            rank_score = coverage + title_bonus + cat_bonus + cal_bonus + float(r.get("rating") or 0) * 0.05
            row_copy = dict(r)
            row_copy["matched_ingredients"] = len(hit_set)
            row_copy["total_ingredients"] = non_pantry_cnt
            if len(hit_set) == n_groups:
                t2_candidates.append((rank_score, row_copy))
            else:
                partial_candidates.append((len(hit_set), rank_score, hit_set, row_copy))

        if t2_candidates:
            t2_candidates.sort(key=lambda x: x[0], reverse=True)
            chosen = [x[1] for x in t2_candidates[:max(1, limit)]]
            return _hydrate_chatbot_rows(chosen), "full_group_intersection"

        # TIER 3: Multi-dish meal pairing covering user's OR-groups across 2-3 real MySQL dishes
        if partial_candidates:
            partial_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            paired: list[dict[str, Any]] = []
            covered: set[int] = set()
            used_rids: set[int] = set()
            for _, _, hset, rcopy in partial_candidates:
                if len(paired) >= max(2, limit):
                    break
                new_gain = hset - covered
                if new_gain or not paired:
                    paired.append(rcopy)
                    covered |= hset
                    used_rids.add(int(rcopy["id"]))
                if len(covered) == n_groups and len(paired) >= 2:
                    break
            for _, _, _, rcopy in partial_candidates:
                if len(paired) >= max(1, limit):
                    break
                if int(rcopy["id"]) not in used_rids:
                    paired.append(rcopy)
                    used_rids.add(int(rcopy["id"]))
            if paired:
                return _hydrate_chatbot_rows(paired[:max(1, limit)]), "multi_dish_pairing"

    # TIER 4: Top MySQL dishes by category / nutrition / featured / rating
    pool = list(allowed_rows)
    if category_hint:
        cat_pool = [r for r in pool if int(r.get("category_id") or 0) == int(category_hint)]
        if cat_pool:
            pool = cat_pool
    if max_calories:
        cal_pool = [r for r in pool if int(r.get("calories") or 999) <= max_calories]
        if cal_pool:
            pool = sorted(cal_pool, key=lambda r: int(r.get("calories") or 999))
    elif high_protein:
        pool = sorted(pool, key=lambda r: float(r.get("protein") or 0), reverse=True)
    else:
        pool = sorted(
            pool,
            key=lambda r: (1 if r.get("is_featured") else 0, float(r.get("rating") or 0), -int(r["id"])),
            reverse=True,
        )
    return _hydrate_chatbot_rows(pool[:max(1, limit)]), "top_category_fallback"


def _recount_categories(cur) -> None:
    try:
        cur.execute(
            "UPDATE categories c SET recipe_count = ("
            "SELECT COUNT(*) FROM recipes r WHERE r.category_id = c.category_id AND r.status = 'APPROVED'"
            ")"
        )
    except Exception:
        pass


def _unique_recipe_slug(cur, base_slug: str, exclude_recipe_id: int | None = None) -> str:
    candidate = base_slug[:185] or "cong-thuc"
    sql = "SELECT recipe_id FROM recipes WHERE slug=%s"
    params: tuple[Any, ...] = (candidate,)
    if exclude_recipe_id:
        sql += " AND recipe_id<>%s"
        params = (candidate, exclude_recipe_id)
    cur.execute(sql + " LIMIT 1", params)
    if not cur.fetchone():
        return candidate
    suffix = hashlib.sha256(f"{candidate}:{time.time_ns()}".encode("utf-8")).hexdigest()[:6]
    return f"{candidate[:175]}-{suffix}"


def list_my_recipes(user_id: int) -> list[dict[str, Any]]:
    return _recipe_query("WHERE r.created_by=%s", (user_id,), 500, include_details=False)


def list_pending_recipes() -> list[dict[str, Any]]:
    return _recipe_query("WHERE r.status='PENDING'", (), 500, include_details=True, include_private=True)


def list_all_recipes_admin(status_filter: str | None = None) -> list[dict[str, Any]]:
    if status_filter:
        norm = status_filter.strip().upper()
        if norm == "PENDING":
            return []
        if norm in ("APPROVED", "REJECTED"):
            return _recipe_query("WHERE r.status=%s", (norm,), 1000, include_details=False, include_private=True)
    return _recipe_query("WHERE r.status IN ('APPROVED','REJECTED')", (), 1000, include_details=False, include_private=True)


def get_admin_recipe_review(recipe_id: int) -> dict[str, Any] | None:
    row = get_recipe(recipe_id, include_private=True)
    if not row:
        return None
    return {
        **row,
        "recipe": row,
        "recipe_steps": row.get("steps") or [],
    }


def create_recipe(payload: dict[str, Any], user_id: int, *, admin: bool = False) -> dict[str, Any]:
    title = clean_text(payload.get("title"), maximum=255, required=True)
    description = clean_text(payload.get("description"), maximum=5000)
    image_url = validate_recipe_image_url(
        payload.get("image") or payload.get("image_url") or payload.get("imageUrl")
    )
    servings = _bounded_int(payload.get("servings", 4), 1, 50, "servings")
    prep = _bounded_int(payload.get("prepTime", payload.get("prep_time", 0)), 0, 1440, "prepTime")
    cook = _bounded_int(payload.get("cookTime", payload.get("cook_time", 0)), 0, 1440, "cookTime")
    ingredients = payload.get("ingredients") or []
    steps = payload.get("steps") or []
    if not isinstance(ingredients, list) or not ingredients or not isinstance(steps, list) or not steps:
        raise ValueError("Công thức cần có nguyên liệu và ít nhất một bước nấu.")
    base_slug = re.sub(r"[^a-z0-9]+", "-", _slug_text(title)).strip("-")[:185] or "cong-thuc"
    nutrition = payload.get("nutrition") or {}
    category_id = payload.get("categoryId") or payload.get("category_id") or None
    source_type = "DB" if admin else "USER"
    status = "APPROVED" if admin else "PENDING"
    reviewed_by = user_id if admin else None
    is_featured = int(bool(payload.get("isFeatured", payload.get("is_featured", False)))) if admin else 0
    is_new = 1 if admin else 0
    with transaction() as (_, cur):
        slug = _unique_recipe_slug(cur, base_slug)
        cur.execute(
            "INSERT INTO recipes(dish_id,category_id,title,slug,description,image_url,servings,prep_time,cook_time,"
            "difficulty,occasion,calories,protein,carbs,fat,fiber,is_featured,is_new,source_type,created_by,status,reviewed_by,"
            "rejection_reason,tags_json,created_at,updated_at) "
            "VALUES(NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            (category_id, title, slug, description, image_url,
             servings, prep, cook, clean_text(payload.get("difficulty") or "Dễ", maximum=50),
             clean_text(payload.get("occasion") or "", maximum=100) or None,
             round(_number(nutrition.get("calories", payload.get("calories", 0)))),
             _number(nutrition.get("protein", payload.get("protein", 0))),
             _number(nutrition.get("carbs", payload.get("carbs", 0))),
             _number(nutrition.get("fat", payload.get("fat", 0))),
             _number(nutrition.get("fiber", payload.get("fiber", 0))),
             is_featured, is_new, source_type, user_id, status, reviewed_by,
             json.dumps(payload.get("tags") or [], ensure_ascii=False)),
        )
        recipe_id = int(cur.lastrowid)
        for idx, item in enumerate(ingredients):
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name") or item.get("ingredient_name"), maximum=200, required=True)
            ingredient_id = item.get("ingredientId") or item.get("ingredient_id") or None
            cur.execute(
                "INSERT INTO recipe_ingredients(recipe_id,ingredient_id,ingredient_name,amount,unit,sort_order,note) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (recipe_id, ingredient_id, name, str(item.get("amount") or ""), clean_text(item.get("unit"), maximum=40), idx,
                 clean_text(item.get("note"), maximum=500)),
            )
        for idx, step in enumerate(steps, 1):
            if isinstance(step, str):
                instruction, title_step, tip = step, f"Bước {idx}", ""
            else:
                instruction = step.get("description") or step.get("instruction") or ""
                title_step = step.get("title") or f"Bước {idx}"
                tip = step.get("tip") or step.get("tip_note") or ""
            instruction = clean_text(instruction, maximum=5000, required=True)
            cur.execute(
                "INSERT INTO recipe_steps(recipe_id,step_order,title,instruction,duration_mins,tip_note,image_url) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (recipe_id, idx, clean_text(title_step, maximum=200), instruction,
                 _bounded_int(step.get("time", 5) if isinstance(step, dict) else 5, 0, 1440, "step time"),
                 clean_text(tip, maximum=500), clean_text(step.get("image") if isinstance(step, dict) else "", maximum=500)),
            )
        if admin:
            _recount_categories(cur)
    return get_recipe(recipe_id, include_private=True)


def update_recipe(recipe_id: int, user_id: int, payload: dict[str, Any], *, admin: bool = False) -> dict[str, Any] | None:
    title = clean_text(payload.get("title"), maximum=255, required=True)
    description = clean_text(payload.get("description"), maximum=5000)
    image_url = validate_recipe_image_url(
        payload.get("image") or payload.get("image_url") or payload.get("imageUrl")
    )
    servings = _bounded_int(payload.get("servings", 4), 1, 50, "servings")
    prep = _bounded_int(payload.get("prepTime", payload.get("prep_time", 0)), 0, 1440, "prepTime")
    cook = _bounded_int(payload.get("cookTime", payload.get("cook_time", 0)), 0, 1440, "cookTime")
    ingredients = payload.get("ingredients") or []
    steps = payload.get("steps") or []
    if not isinstance(ingredients, list) or not ingredients or not isinstance(steps, list) or not steps:
        raise ValueError("Công thức cần có nguyên liệu và ít nhất một bước nấu.")
    base_slug = re.sub(r"[^a-z0-9]+", "-", _slug_text(title)).strip("-")[:185] or "cong-thuc"
    nutrition = payload.get("nutrition") or {}
    category_id = payload.get("categoryId") or payload.get("category_id") or None
    source_type = "DB" if admin else "USER"
    status = "APPROVED" if admin else "PENDING"
    reviewed_by = user_id if admin else None
    with transaction() as (_, cur):
        slug = _unique_recipe_slug(cur, base_slug, exclude_recipe_id=recipe_id)
        owner_clause = "" if admin else " AND created_by=%s"
        params: tuple[Any, ...] = (
            category_id, title, slug, description, image_url,
            servings, prep, cook, clean_text(payload.get("difficulty") or "Dễ", maximum=50),
            clean_text(payload.get("occasion") or "", maximum=100) or None,
            round(_number(nutrition.get("calories", payload.get("calories", 0)))),
            _number(nutrition.get("protein", payload.get("protein", 0))),
            _number(nutrition.get("carbs", payload.get("carbs", 0))),
            _number(nutrition.get("fat", payload.get("fat", 0))),
            _number(nutrition.get("fiber", payload.get("fiber", 0))),
            json.dumps(payload.get("tags") or [], ensure_ascii=False),
            source_type, status, reviewed_by, recipe_id,
        )
        if not admin:
            params += (user_id,)
        cur.execute(
            "UPDATE recipes SET category_id=%s,title=%s,slug=%s,description=%s,image_url=%s,servings=%s,prep_time=%s,"
            "cook_time=%s,difficulty=%s,occasion=%s,calories=%s,protein=%s,carbs=%s,fat=%s,fiber=%s,tags_json=%s,"
            "source_type=%s,status=%s,reviewed_by=%s,rejection_reason=NULL,updated_at=UTC_TIMESTAMP() "
            "WHERE recipe_id=%s" + owner_clause,
            params,
        )
        cur.execute("SELECT recipe_id FROM recipes WHERE recipe_id=%s" + ("" if admin else " AND created_by=%s"),
                    (recipe_id,) if admin else (recipe_id, user_id))
        if not cur.fetchone():
            return None
        cur.execute("DELETE FROM recipe_ingredients WHERE recipe_id=%s", (recipe_id,))
        cur.execute("DELETE FROM recipe_steps WHERE recipe_id=%s", (recipe_id,))
        for idx, item in enumerate(ingredients):
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name") or item.get("ingredient_name"), maximum=200, required=True)
            ingredient_id = item.get("ingredientId") or item.get("ingredient_id") or None
            cur.execute("INSERT INTO recipe_ingredients(recipe_id,ingredient_id,ingredient_name,amount,unit,sort_order,note) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                        (recipe_id, ingredient_id, name, str(item.get("amount") or ""), clean_text(item.get("unit"), maximum=40), idx,
                         clean_text(item.get("note"), maximum=500)))
        for idx, step in enumerate(steps, 1):
            if isinstance(step, str):
                instruction, title_step, tip = step, f"Bước {idx}", ""
            else:
                instruction = step.get("description") or step.get("instruction") or ""
                title_step = step.get("title") or f"Bước {idx}"
                tip = step.get("tip") or step.get("tip_note") or ""
            cur.execute("INSERT INTO recipe_steps(recipe_id,step_order,title,instruction,duration_mins,tip_note,image_url) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                        (recipe_id, idx, clean_text(title_step, maximum=200), clean_text(instruction, maximum=5000, required=True),
                         _bounded_int(step.get("time", 5) if isinstance(step, dict) else 5, 0, 1440, "step time"),
                         clean_text(tip, maximum=500), clean_text(step.get("image") if isinstance(step, dict) else "", maximum=500)))
        _recount_categories(cur)
    return get_recipe(recipe_id, include_private=True)


def delete_recipe(recipe_id: int, user_id: int, *, admin: bool = False) -> bool:
    with transaction() as (_, cur):
        cur.execute(
            "SELECT recipe_id, dish_id FROM recipes WHERE recipe_id=%s"
            + ("" if admin else " AND created_by=%s")
            + " FOR UPDATE",
            (recipe_id,) if admin else (recipe_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return False
        dish_id = row.get("dish_id")

        # Explicitly delete recipe-owned relations inside the transaction; never delete shared ingredients or users
        cur.execute("DELETE FROM recipe_ingredients WHERE recipe_id=%s", (recipe_id,))
        cur.execute("DELETE FROM recipe_steps WHERE recipe_id=%s", (recipe_id,))
        cur.execute("DELETE FROM recipe_sources WHERE recipe_id=%s", (recipe_id,))
        cur.execute("DELETE FROM favorites WHERE recipe_id=%s", (recipe_id,))
        cur.execute("DELETE FROM comments WHERE recipe_id=%s", (recipe_id,))
        cur.execute("UPDATE chat_sessions SET context_recipe_id=NULL WHERE context_recipe_id=%s", (recipe_id,))
        cur.execute("DELETE FROM recipes WHERE recipe_id=%s", (recipe_id,))

        # Clean up dish_ingredients and dishes ONLY if no other recipe shares this dish_id
        if dish_id is not None:
            cur.execute("SELECT COUNT(*) AS cnt FROM recipes WHERE dish_id=%s", (int(dish_id),))
            remaining = int((cur.fetchone() or {}).get("cnt") or 0)
            if remaining == 0:
                cur.execute("DELETE FROM dish_ingredients WHERE dish_id=%s", (int(dish_id),))
                cur.execute("DELETE FROM dishes WHERE dish_id=%s", (int(dish_id),))

        _recount_categories(cur)
        return True


def moderate_recipe(recipe_id: int, admin_id: int, status: str, reason: str = "") -> dict[str, Any] | None:
    if status not in ("APPROVED", "REJECTED"):
        raise ValueError("Trạng thái kiểm duyệt không hợp lệ.")
    rejection_reason = clean_text(reason, maximum=500) if status == "REJECTED" else None
    with transaction() as (_, cur):
        cur.execute(
            "UPDATE recipes SET status=%s,reviewed_by=%s,rejection_reason=%s,updated_at=UTC_TIMESTAMP() "
            "WHERE recipe_id=%s AND status='PENDING'",
            (status, admin_id, rejection_reason or None, recipe_id),
        )
        if cur.rowcount == 0:
            return None
        _recount_categories(cur)
    return get_recipe(recipe_id, include_private=True)


def increment_recipe_views(recipe_id: int) -> int:
    with transaction() as (_, cur):
        cur.execute("UPDATE recipes SET views=views+1 WHERE recipe_id=%s AND status='APPROVED'", (recipe_id,))
        if cur.rowcount == 0:
            return 0
        cur.execute("SELECT views FROM recipes WHERE recipe_id=%s", (recipe_id,))
        return int(cur.fetchone()["views"])


def scale_recipe(recipe_id: int, servings: int) -> dict[str, Any] | None:
    recipe = get_recipe(recipe_id)
    if not recipe:
        return None
    original = max(1, int(recipe["servings"]))
    ratio = servings / original
    scaled = []
    for item in recipe["ingredients"]:
        amount = str(item.get("amount") or "")
        match = re.match(r"^\s*(\d+(?:[.,]\d+)?)(.*)$", amount)
        if match:
            new_amount = round(float(match.group(1).replace(",", "."))*ratio, 2)
            amount = (str(int(new_amount)) if new_amount.is_integer() else str(new_amount).rstrip("0").rstrip(".")) + match.group(2)
        scaled.append({**item,"amount":amount})
    ratio_nutrition = {key: round(float(value or 0)*ratio,1) for key,value in recipe["nutrition"].items()}
    return {"recipeId":recipe_id,"originalServings":original,"targetServings":servings,"ingredients":scaled,"nutrition":ratio_nutrition}


_MATCH_PANTRY_STAPLES_ASCII = {
    "nuoc loc", "muoi", "tieu", "duong", "duong phen", "nuoc mam", "nuoc mam chay",
    "nuoc tuong", "dau an", "dau hao", "dau hao chay", "hanh tim", "toi", "hanh la",
    "ot", "giam", "hat nem", "hat nem nam huong", "da vien",
}

_SECONDARY_ING_WORDS_ASCII = {
    "bot bap", "bot ngo", "bot nang", "bot san", "bot mi", "bot gao", "bot nep",
    "bot chien xu", "bot ca ri", "bot rau cau", "gelatin", "nuoc mam", "nuoc tuong",
    "dau an", "dau hao", "dau me", "dau o liu", "mo ga", "bo lat", "duong", "duong phen",
    "muoi", "tieu", "toi", "hanh tim", "hanh la", "ot", "giam", "chanh", "tac",
    "me vat", "me chua", "mam tom", "mam ruoc hue", "mam nem", "tuong ot", "sa te",
    "ngu vi huong", "mac khen", "hat doi", "mat ong", "mat mia",
}

_FAMILY_EXPANSIONS_ASCII: dict[str, tuple[set[str], set[str]]] = {
    # trigger_ascii -> (allowed_member_substrings_ascii, excluded_substrings_ascii)
    "thit ga": ({"thit ga", "uc ga", "dui ga", "canh ga", "chan ga"}, {"trung ga", "nam dui ga", "nuoc dung ga", "long ga"}),
    "ga": ({"thit ga", "uc ga", "dui ga", "canh ga", "chan ga"}, {"trung ga", "nam dui ga", "nuoc dung ga", "long ga"}),
    "thit bo": ({"thit bo", "bap bo", "bo to", "bo kho"}, {"bo lat", "qua bo", "bo sap", "hanh boaro"}),
    "thit heo": ({"thit heo", "thit ba chi", "suon non", "suon cot let", "gio heo", "thit heo quay"}, {"suon chay"}),
    "thit lon": ({"thit heo", "thit ba chi", "suon non", "suon cot let", "gio heo", "thit heo quay"}, {"suon chay"}),
    "trung": ({"trung ga", "trung vit", "trung cut"}, set()),
    "trung ga": ({"trung ga"}, set()),
    "dau hu": ({"dau hu", "dau phu", "tau hu ky"}, set()),
    "dau phu": ({"dau hu", "dau phu", "tau hu ky"}, set()),
    "tom": ({"tom su", "tom tuoi", "tom dat", "tom kho"}, {"mam tom", "tom chua"}),
    "muc": ({"muc ong", "muc mot nang", "cha muc", "muc tuoi"}, set()),
    "ca loc": ({"ca loc", "phi le ca loc"}, {"nuoc mam"}),
    "ca qua": ({"ca loc", "phi le ca loc"}, {"nuoc mam"}),
    "ca chuoi": ({"ca loc", "phi le ca loc"}, {"nuoc mam"}),
    "ca": (
        {"ca basa", "ca loc", "ca thu", "ca hoi", "ca hu", "ca nuc", "ca bong", "ca chep", "ca dieu hong", "ca tram", "ca lang", "ca ngu", "cha ca"},
        {"nuoc mam", "ca chua", "ca tim", "ca rot", "ca phe", "ca ri"},
    ),
    "dua": ({"dua"}, {"dua leo", "dua hau", "dua cai", "nuoc dua", "nuoc cot dua", "dua non", "la dua"}),
    "thom": ({"dua"}, {"dua leo", "dua hau", "dua cai", "nuoc dua", "nuoc cot dua", "dua non", "la dua"}),
}


def _group_matches_ing(grp: dict[str, Any], ing_id: int | None, ing_name_nfc: str, ing_aliases_asc: set[str], synonyms: dict[str, str]) -> bool:
    if ing_id is not None and ing_id in grp["ids"]:
        return True
    ing_asc = _norm_ascii_search(ing_name_nfc)
    if grp["excl_asc"] and any(_has_whole_phrase(ing_asc, ex, is_ascii=True) for ex in grp["excl_asc"]):
        return False
    if ing_aliases_asc.intersection(grp["names_asc"]):
        return True
    for a in ing_aliases_asc:
        syn_canon = synonyms.get(a, "")
        if syn_canon and syn_canon in grp["names_asc"]:
            return True
    for fam_pat in grp["fam_asc"]:
        if _has_whole_phrase(ing_asc, fam_pat, is_ascii=True):
            return True
    return False


def match_dishes_detailed(ingredient_ids: list[int], ingredient_names: list[str]) -> dict[str, Any]:
    clean_ids = [int(v) for v in ingredient_ids if str(v).isdigit()]
    clean_names: list[str] = []
    seen_norm_in: set[str] = set()
    for raw_n in ingredient_names:
        s = " ".join(str(raw_n or "").strip().split())
        if not s:
            continue
        k = _norm_ascii_search(s)
        if k and k not in seen_norm_in:
            seen_norm_in.add(k)
            clean_names.append(s)

    if not clean_ids and not clean_names:
        return {"matches": [], "total": 0, "fullMatch": True, "selectedCount": 0, "notice": ""}

    synonyms = load_chatbot_synonyms()
    user_groups: list[dict[str, Any]] = []

    if clean_names:
        paired_ids = clean_ids if len(clean_ids) == len(clean_names) else []
        for idx, label in enumerate(clean_names):
            na = _norm_ascii_search(label)
            g_ids = {paired_ids[idx]} if paired_ids else set()
            g_names_asc = {na}
            if na in synonyms:
                g_names_asc.add(_norm_ascii_search(synonyms[na]))
            for al_nfc in _expand_ingredient_aliases_nfc(label):
                al_asc = _norm_ascii_search(al_nfc)
                # Keep specific cuts narrow unless user asked for generic family
                if na in ("thit ga", "ga", "thit heo", "thit lon", "thit bo", "dau hu", "dau phu") or al_asc == na:
                    g_names_asc.add(al_asc)
            fam_set, excl_set = _FAMILY_EXPANSIONS_ASCII.get(na, (set(), set()))
            is_secondary = na in _SECONDARY_ING_WORDS_ASCII or na in _MATCH_PANTRY_STAPLES_ASCII
            user_groups.append({
                "label": label,
                "ids": g_ids,
                "names_asc": g_names_asc,
                "fam_asc": set(fam_set),
                "excl_asc": set(excl_set),
                "group_weight": 1.0 if is_secondary else 5.0,
            })
    else:
        for cid in dict.fromkeys(clean_ids):
            user_groups.append({
                "label": f"Nguyên liệu #{cid}",
                "ids": {cid},
                "names_asc": set(),
                "fam_asc": set(),
                "excl_asc": set(),
                "group_weight": 5.0,
            })

    k_selected = len(user_groups)
    rows = fetch_all(
        "SELECT d.dish_id AS id,r.recipe_id AS recipeId,r.calories AS calories,r.servings AS servings,"
        "r.rating AS rating,d.dish_name AS name,d.slug,COALESCE(NULLIF(r.image_url,''),d.thumbnail_url) AS image,"
        "(r.prep_time+r.cook_time) AS cookTime,d.difficulty,d.category_id AS categoryId,"
        "u.ingredient_id AS ingredientId,u.ingredient_name AS ingredientName,u.ing_category AS ingredientCategory,"
        "u.is_required AS isRequired,u.weight_score AS weightScore "
        "FROM dishes d "
        "JOIN recipes r ON r.dish_id=d.dish_id AND r.status='APPROVED' "
        "JOIN ("
        "  SELECT di.dish_id,r0.recipe_id,di.ingredient_id,i.ingredient_name,i.category AS ing_category,"
        "         di.is_required,di.weight_score "
        "  FROM dish_ingredients di "
        "  JOIN recipes r0 ON r0.dish_id=di.dish_id AND r0.status='APPROVED' "
        "  JOIN ingredients i ON i.ingredient_id=di.ingredient_id "
        "  UNION "
        "  SELECT r1.dish_id,ri.recipe_id,ri.ingredient_id,ri.ingredient_name,COALESCE(i2.category,'Khác') AS ing_category,"
        "         CASE WHEN ri.sort_order < 3 THEN 1 ELSE 0 END AS is_required,"
        "         CASE WHEN ri.sort_order < 2 THEN 4.000 ELSE 1.500 END AS weight_score "
        "  FROM recipe_ingredients ri "
        "  JOIN recipes r1 ON r1.recipe_id=ri.recipe_id AND r1.status='APPROVED' "
        "  LEFT JOIN ingredients i2 ON i2.ingredient_id=ri.ingredient_id"
        ") u ON u.recipe_id=r.recipe_id "
        "ORDER BY d.dish_id"
    )

    dishes: dict[int, dict[str, Any]] = {}
    for row in rows:
        did = int(row["id"])
        dish = dishes.setdefault(did, {
            "id": did,
            "recipeId": row["recipeId"],
            "name": row["name"],
            "slug": row["slug"],
            "image": row["image"],
            "cookTime": int(row.get("cookTime") or 25),
            "difficulty": row.get("difficulty") or "Dễ",
            "categoryId": row.get("categoryId"),
            "calories": int(row.get("calories") or 0),
            "servings": int(row.get("servings") or 4),
            "rating": float(row.get("rating") or 0),
            "parts_by_key": {},
            "hit_groups": set(),
        })
        ing_name = str(row.get("ingredientName") or "").strip()
        if not ing_name:
            continue
        ing_asc = _norm_ascii_search(ing_name)
        ing_id = int(row["ingredientId"]) if row.get("ingredientId") is not None else None
        ing_aliases_nfc = _expand_ingredient_aliases_nfc(ing_name)
        ing_aliases_asc = {_norm_ascii_search(a) for a in ing_aliases_nfc if a}
        ing_aliases_asc.add(ing_asc)

        matched_any_group = False
        for g_idx, grp in enumerate(user_groups):
            if _group_matches_ing(grp, ing_id, ing_name, ing_aliases_asc, synonyms):
                dish["hit_groups"].add(g_idx)
                matched_any_group = True

        weight = float(row.get("weightScore") or 1.0)
        is_req = bool(row.get("isRequired"))
        prev = dish["parts_by_key"].get(ing_asc)
        if prev is None:
            dish["parts_by_key"][ing_asc] = [ing_name, is_req, matched_any_group, weight, ing_asc in _MATCH_PANTRY_STAPLES_ASCII]
        else:
            prev[1] = prev[1] or is_req
            prev[2] = prev[2] or matched_any_group
            prev[3] = max(prev[3], weight)

    has_animal_input = any(
        _query_requests_animal_without_vegan(_norm_nfc_words(n), _norm_ascii_search(n), _norm_nfc_words(n) != _norm_ascii_search(n))
        for n in clean_names
    )
    wants_vegan_input = any("chay" in _norm_ascii_search(n) for n in clean_names)

    full_candidates: list[dict[str, Any]] = []
    partial_candidates: list[tuple[float, dict[str, Any]]] = []

    for dish in dishes.values():
        if has_animal_input and not wants_vegan_input and int(dish.get("categoryId") or 0) == 5:
            continue
        hit_groups: set[int] = dish.pop("hit_groups")
        parts = list(dish.pop("parts_by_key").values())
        if not hit_groups:
            continue

        # Exclude basic pantry staples from core readiness denominator unless matched by user
        core_parts = [p for p in parts if (not p[4]) or p[2]]
        if not core_parts:
            core_parts = parts

        total_w = sum(p[3] for p in core_parts)
        matched_w = sum(p[3] for p in core_parts if p[2])
        readiness_pct = round(100 * matched_w / total_w) if total_w > 0 else 0
        missing_core = [p[0] for p in core_parts if p[1] and not p[2]]
        if not missing_core and readiness_pct < 100:
            missing_core = [p[0] for p in core_parts if not p[2]][:4]

        dish["score"] = readiness_pct
        dish["missing"] = missing_core
        dish["matchedIngredients"] = [p[0] for p in parts if p[2]]
        dish["matchedUserCount"] = len(hit_groups)
        dish["totalUserCount"] = k_selected
        dish["fullIngredientMatch"] = len(hit_groups) == k_selected

        if len(hit_groups) == k_selected:
            full_candidates.append(dish)
        else:
            weighted_user = sum(user_groups[idx]["group_weight"] for idx in hit_groups)
            partial_candidates.append((weighted_user, dish))

    if full_candidates:
        full_candidates.sort(
            key=lambda item: (item["score"], item.get("rating") or 0, -(item.get("cookTime") or 30)),
            reverse=True,
        )
        top_full = full_candidates[:12]
        return {
            "matches": top_full,
            "total": len(top_full),
            "fullMatch": True,
            "selectedCount": k_selected,
            "notice": "",
        }

    partial_candidates.sort(
        key=lambda pair: (pair[0], pair[1]["matchedUserCount"], pair[1]["score"], pair[1].get("rating") or 0),
        reverse=True,
    )
    top_partial = [pair[1] for pair in partial_candidates[:8]]
    joined_labels = " + ".join(g["label"] for g in user_groups)
    notice = (
        f"Chưa có món đơn lẻ nào kết hợp đồng thời cả [{joined_labels}]. "
        "Gợi ý các món khớp nhiều nguyên liệu chính nhất:"
        if top_partial and k_selected >= 2
        else ""
    )
    return {
        "matches": top_partial,
        "total": len(top_partial),
        "fullMatch": False,
        "selectedCount": k_selected,
        "notice": notice,
    }


def match_dishes(ingredient_ids: list[int], ingredient_names: list[str]) -> list[dict[str, Any]]:
    return match_dishes_detailed(ingredient_ids, ingredient_names)["matches"]


def list_favorites(user_id: int) -> list[int]:
    rows=fetch_all("SELECT recipe_id FROM favorites WHERE user_id=%s ORDER BY saved_at DESC",(user_id,))
    return [int(row["recipe_id"]) for row in rows]


def toggle_favorite(user_id: int, recipe_id: int) -> dict[str, Any]:
    with transaction() as (_, cur):
        cur.execute("SELECT fav_id FROM favorites WHERE user_id=%s AND recipe_id=%s",(user_id,recipe_id))
        existing=cur.fetchone()
        if existing:
            cur.execute("DELETE FROM favorites WHERE fav_id=%s",(existing["fav_id"],))
            return {"added":False,"recipeId":recipe_id}
        cur.execute("INSERT INTO favorites(user_id,recipe_id,saved_at) SELECT %s,%s,UTC_TIMESTAMP() "
                     "WHERE EXISTS(SELECT 1 FROM recipes WHERE recipe_id=%s AND status='APPROVED')",(user_id,recipe_id,recipe_id))
        if cur.rowcount == 0:
            raise ValueError("Không tìm thấy công thức công khai.")
        return {"added":True,"recipeId":recipe_id}


def list_favorite_recipes(user_id: int) -> list[dict[str, Any]]:
    ids=list_favorites(user_id)
    return [recipe for recipe_id in ids if (recipe:=get_recipe(recipe_id))]


def list_comments(recipe_id: int | None = None) -> list[dict[str, Any]]:
    if recipe_id:
        rows = fetch_all("SELECT comment_id AS id,recipe_id AS recipeId,user_id AS userId,user_name AS userName,"
                         "user_avatar AS userAvatar,rating,comment AS content,created_at AS createdAt FROM comments "
                         "WHERE recipe_id=%s ORDER BY created_at DESC",(recipe_id,))
    else:
        rows = fetch_all("SELECT comment_id AS id,recipe_id AS recipeId,user_id AS userId,user_name AS userName,"
                         "user_avatar AS userAvatar,rating,comment AS content,created_at AS createdAt FROM comments ORDER BY created_at DESC")
    for item in rows:
        item["createdAt"] = _format_utc_iso(item.get("createdAt"))
    return rows


def add_comment(recipe_id: int, user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    comment=clean_text(payload.get("comment") or payload.get("content"),maximum=2000,required=True)
    rating=_bounded_int(payload.get("rating",5),1,5,"rating")
    with transaction() as (_, cur):
        cur.execute("INSERT INTO comments(recipe_id,user_id,user_name,user_avatar,rating,comment,created_at) "
                    "SELECT %s,%s,%s,%s,%s,%s,UTC_TIMESTAMP() WHERE EXISTS(SELECT 1 FROM recipes WHERE recipe_id=%s AND status='APPROVED')",
                    (recipe_id,user["id"],user["name"],user.get("avatar") or "",rating,comment,recipe_id))
        if cur.rowcount == 0:
            raise ValueError("Không tìm thấy công thức công khai.")
        comment_id=int(cur.lastrowid)
        cur.execute("UPDATE recipes SET review_count=(SELECT COUNT(*) FROM comments WHERE recipe_id=%s), "
                    "rating=(SELECT AVG(rating) FROM comments WHERE recipe_id=%s) WHERE recipe_id=%s",
                    (recipe_id,recipe_id,recipe_id))
    return next((item for item in list_comments(recipe_id) if item["id"]==comment_id),{})


def delete_comment(comment_id: int, user_id: int | None = None, *, admin: bool = False) -> bool:
    with transaction() as (_, cur):
        cur.execute("SELECT recipe_id,user_id FROM comments WHERE comment_id=%s",(comment_id,))
        row=cur.fetchone()
        if not row:
            return False
        if not admin and (user_id is None or int(row["user_id"])!=int(user_id)):
            raise PermissionError("Bạn chỉ được xóa bình luận của chính mình.")
        recipe_id=row["recipe_id"]
        cur.execute("DELETE FROM comments WHERE comment_id=%s",(comment_id,))
        cur.execute("UPDATE recipes SET review_count=(SELECT COUNT(*) FROM comments WHERE recipe_id=%s), "
                    "rating=COALESCE((SELECT AVG(rating) FROM comments WHERE recipe_id=%s),0) WHERE recipe_id=%s",
                    (recipe_id,recipe_id,recipe_id))
        return True


def get_statistics() -> dict[str, Any]:
    row = fetch_one(
        "SELECT COUNT(*) AS totalRecipes,SUM(status='APPROVED') AS approvedRecipes,"
        "SUM(status='PENDING') AS pendingRecipes,SUM(status='REJECTED') AS rejectedRecipes,"
        "COALESCE(SUM(views),0) AS totalViews,COALESCE(AVG(rating),0) AS avgRating FROM recipes"
    ) or {}
    kb_count = 0
    learned_count = 0
    try:
        kb_count = int((fetch_one("SELECT COUNT(*) AS n FROM chatbot_knowledge_base WHERE is_active=1") or {}).get("n", 0))
        learned_count = int((fetch_one("SELECT COUNT(*) AS n FROM chatbot_learned_qa") or {}).get("n", 0))
    except Exception:
        pass
    row.update({
        "totalCategories": (fetch_one("SELECT COUNT(*) AS n FROM categories") or {}).get("n", 0),
        "totalIngredients": (fetch_one("SELECT COUNT(*) AS n FROM ingredients") or {}).get("n", 0),
        "totalUsers": (fetch_one("SELECT COUNT(*) AS n FROM users") or {}).get("n", 0),
        "totalComments": (fetch_one("SELECT COUNT(*) AS n FROM comments") or {}).get("n", 0),
        "totalFavorites": (fetch_one("SELECT COUNT(*) AS n FROM favorites") or {}).get("n", 0),
        "kbCount": kb_count,
        "learnedQaCount": learned_count,
        "topRecipes": _recipe_query("WHERE r.status='APPROVED'", (), 5, include_details=False),
    })
    return row


def get_bootstrap_payload(user_id: int | None = None) -> dict[str, Any]:
    payload = {
        "recipes": list_recipes({"limit": 500, "include_details": False}),
        "categories": list_categories(),
        "ingredients": list_ingredients(),
        "comments": list_comments(),
        "statistics": get_statistics(),
    }
    payload["favorites"] = list_favorites(user_id) if user_id else []
    return payload


def get_chat_history(session_id: str) -> list[dict[str, Any]]:
    return fetch_all("SELECT sender,message_text AS text,created_at AS createdAt FROM chat_messages "
                     "WHERE session_id=%s ORDER BY message_id",(session_id,))


def create_chat_session(session_id: str, user_id: int | None, recipe_id: int | None) -> None:
    with transaction() as (_, cur):
        cur.execute("INSERT INTO chat_sessions(session_id,user_id,context_recipe_id,started_at,status) "
                    "VALUES(%s,%s,%s,UTC_TIMESTAMP(),'OPEN')",(session_id,user_id,recipe_id))


def get_chat_session(session_id: str) -> dict[str, Any] | None:
    return fetch_one("SELECT session_id,user_id,context_recipe_id,status FROM chat_sessions WHERE session_id=%s",(session_id,))


def save_chat_messages(session_id: str, user_message: str, ai_message: str) -> None:
    with transaction() as (_, cur):
        cur.execute("INSERT INTO chat_messages(session_id,sender,message_text,created_at) VALUES(%s,'USER',%s,UTC_TIMESTAMP())",(session_id,user_message))
        cur.execute("INSERT INTO chat_messages(session_id,sender,message_text,created_at) VALUES(%s,'AI',%s,UTC_TIMESTAMP())",(session_id,ai_message))


def close_chat_session(session_id: str) -> None:
    with transaction() as (_, cur):
        cur.execute("UPDATE chat_sessions SET status='CLOSED' WHERE session_id=%s",(session_id,))


def get_search_cache(query: str) -> dict[str, Any] | None:
    row=fetch_one("SELECT normalized_json FROM ai_search_cache WHERE query_dish=%s AND expires_at>UTC_TIMESTAMP()",(query.lower().strip(),))
    return _json_value(row["normalized_json"],None) if row else None


def save_search_cache(query: str, result: dict[str, Any], recipe_rows: list[dict[str, Any]]) -> None:
    with transaction() as (_, cur):
        cur.execute("INSERT INTO ai_search_cache(query_dish,normalized_json,created_at,expires_at) "
                    "VALUES(%s,%s,UTC_TIMESTAMP(),DATE_ADD(UTC_TIMESTAMP(),INTERVAL 24 HOUR)) "
                    "ON DUPLICATE KEY UPDATE normalized_json=VALUES(normalized_json),created_at=VALUES(created_at),expires_at=VALUES(expires_at)",
                    (query.lower().strip(),json.dumps(result,ensure_ascii=False)))
        for recipe in recipe_rows:
            recipe_slug=f"{recipe.get('slug') or _slug_text(recipe['title'])}-{hashlib.sha256((query+recipe['title']).encode('utf-8')).hexdigest()[:8]}"
            cur.execute("SELECT recipe_id FROM recipes WHERE slug=%s LIMIT 1",(recipe_slug,))
            existing=cur.fetchone()
            if existing:
                recipe["id"]=int(existing["recipe_id"])
                recipe["image"]=recipe.get("image_url") or ""
                continue
            cur.execute("INSERT INTO recipes(dish_id,category_id,title,slug,description,image_url,servings,prep_time,cook_time,"
                        "difficulty,occasion,calories,protein,carbs,fat,fiber,source_type,created_by,status,tags_json,created_at,updated_at) "
                        "VALUES(NULL,NULL,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,'AI',NULL,'APPROVED','[]',UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                        (recipe["title"],recipe_slug,recipe.get("description") or "",
                         recipe.get("image_url") or "",recipe.get("servings",4),recipe.get("prep_time",0),recipe.get("cook_time",0),
                         recipe.get("difficulty") or "Dễ",recipe.get("calories",0),recipe.get("protein",0),recipe.get("carbs",0),
                         recipe.get("fat",0),recipe.get("fiber",0)))
            recipe_id=int(cur.lastrowid)
            recipe["id"]=recipe_id
            recipe["image"]=recipe.get("image_url") or ""
            for idx,item in enumerate(recipe.get("ingredients") or []):
                cur.execute("INSERT INTO recipe_ingredients(recipe_id,ingredient_id,ingredient_name,amount,unit,sort_order) "
                            "VALUES(%s,NULL,%s,%s,%s,%s)",(recipe_id,item.get("name", "Nguyên liệu"),str(item.get("amount", "")),item.get("unit", ""),idx))
            for idx,step in enumerate(recipe.get("steps") or [],1):
                cur.execute("INSERT INTO recipe_steps(recipe_id,step_order,title,instruction) VALUES(%s,%s,%s,%s)",
                            (recipe_id,idx,f"Bước {idx}",step))
            for source in recipe.get("sources") or []:
                if source.get("url", "").startswith(("https://", "http://")):
                    cur.execute("INSERT INTO recipe_sources(recipe_id,source_name,source_url,relevance_score,fetched_at) "
                                "VALUES(%s,%s,%s,%s,UTC_TIMESTAMP())",(recipe_id,source.get("name") or "Nguồn tham khảo",source["url"],source.get("relevance",0.5)))
        cur.execute("UPDATE ai_search_cache SET normalized_json=%s WHERE query_dish=%s",
                    (json.dumps(result,ensure_ascii=False),query.lower().strip()))


def delete_chat_session(session_id: str) -> None:
    with transaction() as (_, cur):
        cur.execute("DELETE FROM chat_sessions WHERE session_id=%s",(session_id,))


def _bounded_int(value: Any, minimum: int, maximum: int, field: str) -> int:
    try:
        parsed=int(value)
    except (TypeError,ValueError):
        raise ValueError(f"{field} must be an integer.")
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    return parsed


def _number(value: Any) -> float:
    try:
        result=float(value or 0)
    except (TypeError,ValueError):
        return 0.0
    return max(0.0,result)


def _slug_text(value: str) -> str:
    value = value.lower().replace("đ", "d")
    value = "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def _norm_ascii(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower().replace("đ", "d")
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def load_chatbot_synonyms(*, force_refresh: bool = False) -> dict[str, str]:
    now = time.monotonic()
    if not force_refresh and _SYNONYM_CACHE["expires_at"] > now and _SYNONYM_CACHE["mapping"]:
        return dict(_SYNONYM_CACHE["mapping"])
    try:
        rows = fetch_all("SELECT canonical_term, variant_term FROM chatbot_synonyms")
    except Exception:
        return dict(_SYNONYM_CACHE["mapping"])
    mapping: dict[str, str] = {}
    for row in rows:
        variant = _norm_ascii(str(row.get("variant_term") or ""))
        canonical = _norm_ascii(str(row.get("canonical_term") or ""))
        if variant and canonical and variant != canonical:
            mapping[variant] = canonical
    _SYNONYM_CACHE.update({"expires_at": now + 30.0, "mapping": mapping})
    return dict(mapping)


get_synonym_map = load_chatbot_synonyms


def search_knowledge_base(query_norm: str, tokens: list[str], limit: int = 4) -> list[dict[str, Any]]:
    try:
        rows = fetch_all(
            "SELECT kb_id,topic,category,title,keywords_text,content,substitution_json,priority "
            "FROM chatbot_knowledge_base WHERE is_active=1 ORDER BY priority DESC, kb_id ASC LIMIT 250"
        )
    except Exception:
        return []
    if not rows:
        return []
    token_set = {t for t in tokens if len(t) >= 2}
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        title_norm = _norm_ascii(str(row.get("title") or ""))
        kw_norm = _norm_ascii(str(row.get("keywords_text") or ""))
        content_norm = _norm_ascii(str(row.get("content") or ""))
        score = 0.0
        for kw in (part.strip() for part in kw_norm.split(",") if part.strip()):
            if kw in query_norm:
                score += 4.5 + len(kw.split()) * 1.2
        if title_norm and title_norm in query_norm:
            score += 6.0
        hay = f"{title_norm} {kw_norm} {content_norm[:260]}"
        hay_words = set(re.findall(r"[a-z0-9]+", hay))
        overlap = token_set.intersection(hay_words)
        if overlap:
            score += len(overlap) * 1.1
        if score >= 2.2:
            scored.append((score + float(row.get("priority") or 0) * 0.05, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    for score, row in scored[:max(1, limit)]:
        results.append({
            "id": int(row["kb_id"]),
            "topic": row.get("topic") or "general",
            "category": row.get("category") or "cooking_tip",
            "title": row["title"],
            "content": row["content"],
            "substitution": _json_value(row.get("substitution_json"), None),
            "score": round(score, 2),
        })
    return results


def find_learned_qa(normalized_question: str, tokens: list[str], limit: int = 3) -> dict[str, Any]:
    try:
        rows = fetch_all(
            "SELECT qa_id,normalized_question,question_text,intent,answer_text,keywords_text,matched_recipe_ids,"
            "model_used,quality_score,usage_count,is_verified,source_type "
            "FROM chatbot_learned_qa WHERE quality_score >= 0.45 "
            "ORDER BY is_verified DESC, quality_score DESC, usage_count DESC LIMIT 200"
        )
    except Exception:
        return {"exact": None, "similar": [], "few_shots": []}
    if not rows:
        return {"exact": None, "similar": [], "few_shots": []}

    q_words = set(re.findall(r"[a-z0-9]+", normalized_question))
    exact_row: dict[str, Any] | None = None
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        ans_low = str(row.get("answer_text") or "").lower()
        if "chưa có trong csdl" in ans_low or "gợi ý tự nấu" in ans_low or "tự nấu do" in ans_low:
            continue
        cand_norm = _norm_ascii(str(row.get("normalized_question") or ""))
        if cand_norm == normalized_question:
            exact_row = row
        cand_words = set(re.findall(r"[a-z0-9]+", f"{cand_norm} {_norm_ascii(str(row.get('keywords_text') or ''))}"))
        if not q_words or not cand_words:
            continue
        inter = len(q_words.intersection(cand_words))
        union = len(q_words.union(cand_words))
        sim = inter / union if union else 0.0
        if sim >= 0.35:
            scored.append((sim + float(row.get("quality_score") or 0) * 0.25 + (0.2 if row.get("is_verified") else 0.0), row))

    scored.sort(key=lambda item: item[0], reverse=True)
    similar = [
        {
            "qa_id": int(item[1]["qa_id"]),
            "question": item[1]["question_text"],
            "answer": item[1]["answer_text"],
            "intent": item[1].get("intent") or "cooking",
            "matched_recipe_ids": _json_value(item[1].get("matched_recipe_ids"), []),
            "quality_score": float(item[1].get("quality_score") or 0),
            "is_verified": bool(item[1].get("is_verified")),
            "source_type": item[1].get("source_type") or "AUTO_LEARNED",
            "similarity": round(item[0], 3),
        }
        for item in scored[:max(1, limit)]
    ]
    few_shots = [
        {"question": s["question"], "answer": s["answer"][:500]}
        for s in similar
        if s["quality_score"] >= 0.70 or s["is_verified"]
    ][:2]
    exact_formatted = None
    if exact_row:
        exact_formatted = {
            "qa_id": int(exact_row["qa_id"]),
            "question": exact_row["question_text"],
            "answer": exact_row["answer_text"],
            "matched_recipe_ids": _json_value(exact_row.get("matched_recipe_ids"), []),
            "quality_score": float(exact_row.get("quality_score") or 0),
            "is_verified": bool(exact_row.get("is_verified")),
            "source_type": exact_row.get("source_type") or "AUTO_LEARNED",
        }
    return {"exact": exact_formatted, "similar": similar, "few_shots": few_shots}


def save_or_update_learned_qa(
    question_text: str,
    normalized_question: str,
    intent: str,
    answer_text: str,
    keywords_text: str,
    model_used: str,
    *,
    matched_recipe_ids: list[int] | None = None,
    initial_score: float = 0.72,
    source_type: str = "AUTO_LEARNED",
    is_verified: bool = False,
) -> int | None:
    norm_key = _norm_ascii(normalized_question)[:250]
    ans_str = str(answer_text or "").strip()
    if not norm_key or not ans_str:
        return None
    ans_low = ans_str.lower()
    if "chưa có trong csdl" in ans_low or "gợi ý tự nấu" in ans_low:
        return None
    if source_type not in ("CURATED", "AUTO_LEARNED", "GEMINI_VERIFIED"):
        source_type = "AUTO_LEARNED"
    recipe_ids_json = json.dumps([int(x) for x in (matched_recipe_ids or []) if str(x).isdigit()])
    try:
        with transaction() as (_, cur):
            cur.execute("SELECT qa_id,is_verified,source_type FROM chatbot_learned_qa WHERE normalized_question=%s LIMIT 1", (norm_key,))
            existing = cur.fetchone()
            if existing:
                qa_id = int(existing["qa_id"])
                keep_verified = bool(existing.get("is_verified")) or is_verified
                cur.execute(
                    "UPDATE chatbot_learned_qa SET usage_count=usage_count+1, "
                    "answer_text=CASE WHEN is_verified=1 THEN answer_text ELSE %s END, "
                    "matched_recipe_ids=COALESCE(NULLIF(%s,'[]'),matched_recipe_ids), "
                    "model_used=%s, is_verified=%s, updated_at=UTC_TIMESTAMP() WHERE qa_id=%s",
                    (ans_str[:8000], recipe_ids_json, str(model_used)[:120], int(keep_verified), qa_id),
                )
                return qa_id
            cur.execute(
                "INSERT INTO chatbot_learned_qa(normalized_question,question_text,intent,answer_text,keywords_text,"
                "matched_recipe_ids,model_used,quality_score,usage_count,is_verified,source_type,created_at,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                (
                    norm_key,
                    str(question_text)[:1000],
                    str(intent or "cooking")[:80],
                    ans_str[:8000],
                    str(keywords_text)[:1000],
                    recipe_ids_json,
                    str(model_used)[:120],
                    round(max(0.1, min(5.0, initial_score)), 2),
                    int(bool(is_verified)),
                    source_type,
                ),
            )
            return int(cur.lastrowid)
    except Exception:
        return None


def record_chatbot_feedback(qa_id: int, rating: int) -> dict[str, Any] | None:
    if rating not in (1, -1):
        raise ValueError("rating must be 1 or -1.")
    try:
        with transaction() as (_, cur):
            cur.execute(
                "SELECT qa_id,quality_score,usage_count,is_verified FROM chatbot_learned_qa WHERE qa_id=%s",
                (int(qa_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            current_score = float(row.get("quality_score") or 0.70)
            delta = 0.15 if rating > 0 else -0.35
            new_score = round(max(0.0, min(5.0, current_score + delta)), 2)
            if rating > 0 and new_score >= 0.95:
                verified = True
            elif rating < 0 and new_score < 0.55:
                verified = False
            else:
                verified = bool(row.get("is_verified"))
            cur.execute(
                "UPDATE chatbot_learned_qa SET quality_score=%s,is_verified=%s,updated_at=UTC_TIMESTAMP() WHERE qa_id=%s",
                (new_score, int(verified), int(qa_id)),
            )
            return {
                "qaId": int(qa_id),
                "qualityScore": new_score,
                "isVerified": verified,
                "usageCount": int(row.get("usage_count") or 1),
            }
    except ValueError:
        raise
    except Exception:
        return None


def _hash_otp(user_id: int, otp: str, secret_key: str) -> str:
    salt = secrets.token_hex(16)
    digest = hmac.new(
        secret_key.encode("utf-8"),
        f"otp:{int(user_id)}:{salt}:{otp}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256${salt}${digest}"


def _verify_otp_hash(user_id: int, otp: str, stored_hash: str, secret_key: str) -> bool:
    parts = str(stored_hash or "").split("$")
    if len(parts) != 3 or parts[0] != "hmac-sha256":
        return False
    _, salt, expected_digest = parts
    if not salt or not expected_digest:
        return False
    candidate = hmac.new(
        secret_key.encode("utf-8"),
        f"otp:{int(user_id)}:{salt}:{otp}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(candidate, expected_digest)


def _generate_temporary_password(length: int = 16) -> str:
    target_len = max(16, int(length))
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digits = string.digits
    symbols = "!@#$%^&*-_=+"
    alphabet = upper + lower + digits + symbols
    chars = [
        secrets.choice(upper),
        secrets.choice(lower),
        secrets.choice(digits),
        secrets.choice(symbols),
    ]
    chars.extend(secrets.choice(alphabet) for _ in range(target_len - len(chars)))
    for idx in range(len(chars) - 1, 0, -1):
        swap_idx = secrets.randbelow(idx + 1)
        chars[idx], chars[swap_idx] = chars[swap_idx], chars[idx]
    return "".join(chars)


def create_password_reset_otp(
    email: str,
    *,
    secret_key: str,
    otp_length: int = 6,
    expiry_minutes: int = 5,
) -> dict[str, Any] | None:
    normalized_email = str(email or "").strip().lower()
    with transaction() as (_, cur):
        cur.execute(
            "SELECT user_id, email, status FROM users WHERE email=%s FOR UPDATE",
            (normalized_email,),
        )
        user_row = cur.fetchone()
        if not user_row or user_row.get("status") != "active":
            return None
        user_id = int(user_row["user_id"])

        cur.execute(
            "UPDATE password_reset_otps SET used_at=UTC_TIMESTAMP() "
            "WHERE user_id=%s AND used_at IS NULL",
            (user_id,),
        )

        digits = max(6, int(otp_length))
        otp = f"{secrets.randbelow(10 ** digits):0{digits}d}"
        otp_hash = _hash_otp(user_id, otp, secret_key)
        cur.execute(
            "INSERT INTO password_reset_otps (user_id, otp_hash, expires_at, attempts, created_at, used_at) "
            "VALUES (%s, %s, DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s MINUTE), 0, UTC_TIMESTAMP(), NULL)",
            (user_id, otp_hash, max(1, int(expiry_minutes))),
        )
        return {
            "user_id": user_id,
            "email": user_row["email"],
            "otp": otp,
            "expiry_minutes": max(1, int(expiry_minutes)),
        }


def verify_password_reset_otp(
    email: str,
    otp: str,
    *,
    secret_key: str,
    max_attempts: int = 5,
    temp_password_length: int = 16,
) -> dict[str, Any]:
    normalized_email = str(email or "").strip().lower()
    max_tries = max(1, int(max_attempts))

    with transaction() as (_, cur):
        cur.execute(
            "SELECT user_id, status FROM users WHERE email=%s FOR UPDATE",
            (normalized_email,),
        )
        user_row = cur.fetchone()
        if not user_row or user_row.get("status") != "active":
            return {"ok": False, "status": 400, "error": "Mã xác minh không hợp lệ hoặc đã được sử dụng."}
        user_id = int(user_row["user_id"])

        cur.execute(
            "SELECT id, otp_hash, attempts, used_at, (expires_at <= UTC_TIMESTAMP()) AS is_expired "
            "FROM password_reset_otps "
            "WHERE user_id=%s "
            "ORDER BY id DESC LIMIT 1 FOR UPDATE",
            (user_id,),
        )
        otp_row = cur.fetchone()
        if not otp_row:
            return {"ok": False, "status": 400, "error": "Mã xác minh không hợp lệ hoặc đã được sử dụng."}
        if int(otp_row["attempts"]) >= max_tries:
            return {"ok": False, "status": 429, "error": "Bạn đã nhập sai quá 5 lần. Mã xác minh đã bị vô hiệu hóa."}
        if otp_row["used_at"] is not None:
            return {"ok": False, "status": 400, "error": "Mã xác minh không hợp lệ hoặc đã được sử dụng."}
        if bool(otp_row["is_expired"]):
            return {"ok": False, "status": 400, "error": "Mã xác minh đã hết hạn. Vui lòng gửi lại mã."}

        if not _verify_otp_hash(user_id, otp, str(otp_row["otp_hash"]), secret_key):
            new_attempts = int(otp_row["attempts"]) + 1
            cur.execute(
                "UPDATE password_reset_otps "
                "SET attempts = %s, "
                "    used_at = CASE WHEN %s >= %s THEN UTC_TIMESTAMP() ELSE used_at END "
                "WHERE id=%s AND used_at IS NULL",
                (new_attempts, new_attempts, max_tries, int(otp_row["id"])),
            )
            if new_attempts >= max_tries:
                return {
                    "ok": False,
                    "status": 429,
                    "error": "Bạn đã nhập sai quá 5 lần. Mã xác minh đã bị vô hiệu hóa.",
                }
            return {"ok": False, "status": 400, "error": "Mã xác minh không đúng."}

        cur.execute(
            "UPDATE password_reset_otps "
            "SET used_at = UTC_TIMESTAMP() "
            "WHERE id=%s AND used_at IS NULL AND expires_at > UTC_TIMESTAMP() AND attempts < %s",
            (int(otp_row["id"]), max_tries),
        )
        if cur.rowcount != 1:
            return {"ok": False, "status": 400, "error": "Mã xác minh không hợp lệ hoặc đã được sử dụng."}

        cur.execute(
            "UPDATE password_reset_otps SET used_at = UTC_TIMESTAMP() "
            "WHERE user_id=%s AND used_at IS NULL",
            (user_id,),
        )
        temp_password = _generate_temporary_password(temp_password_length)
        cur.execute(
            "UPDATE users SET password_hash=%s, must_change_password=1 WHERE user_id=%s",
            (generate_password_hash(temp_password), user_id),
        )
        return {"ok": True, "temporary_password": temp_password}


def change_user_password(
    user_id: int,
    current_password: str,
    new_password: str,
    confirm_password: str,
) -> None:
    if not current_password or not current_password.strip():
        raise ValueError("Vui lòng nhập mật khẩu hiện tại.")
    if not new_password or not new_password.strip():
        raise ValueError("Vui lòng nhập mật khẩu mới.")
    if not confirm_password or not confirm_password.strip():
        raise ValueError("Vui lòng xác nhận mật khẩu mới.")
    if len(new_password) < 8:
        raise ValueError("Mật khẩu mới phải có ít nhất 8 ký tự.")
    if len(new_password) > 128:
        raise ValueError("Mật khẩu mới không được vượt quá 128 ký tự.")
    if new_password != confirm_password:
        raise ValueError("Mật khẩu xác nhận không khớp.")
    if new_password == current_password:
        raise ValueError("Mật khẩu mới phải khác mật khẩu hiện tại.")

    with transaction() as (_, cur):
        cur.execute(
            "SELECT user_id, password_hash, status FROM users WHERE user_id=%s FOR UPDATE",
            (int(user_id),),
        )
        row = cur.fetchone()
        if not row or row.get("status") != "active":
            raise PermissionError("Tài khoản đã bị vô hiệu hóa.")
        if not check_password_hash(row["password_hash"], current_password):
            raise ValueError("Mật khẩu hiện tại không đúng.")
        cur.execute(
            "UPDATE users SET password_hash=%s, must_change_password=0 WHERE user_id=%s",
            (generate_password_hash(new_password), int(user_id)),
        )


def force_change_user_password(
    user_id: int,
    new_password: str,
    confirm_password: str,
) -> dict[str, Any] | None:
    if not new_password or not new_password.strip():
        raise ValueError("Vui lòng nhập mật khẩu mới.")
    if not confirm_password or not confirm_password.strip():
        raise ValueError("Vui lòng xác nhận mật khẩu mới.")
    if len(new_password) < 8:
        raise ValueError("Mật khẩu mới phải có ít nhất 8 ký tự.")
    if len(new_password) > 128:
        raise ValueError("Mật khẩu mới không được vượt quá 128 ký tự.")
    if new_password != confirm_password:
        raise ValueError("Mật khẩu xác nhận không khớp.")

    with transaction() as (_, cur):
        cur.execute(
            "SELECT user_id, password_hash, status, must_change_password FROM users WHERE user_id=%s FOR UPDATE",
            (int(user_id),),
        )
        row = cur.fetchone()
        if not row or row.get("status") != "active":
            raise PermissionError("Tài khoản đã bị vô hiệu hóa.")
        if not int(row.get("must_change_password") or 0):
            raise ValueError("Tài khoản không ở trạng thái bắt buộc đổi mật khẩu.")
        if check_password_hash(row["password_hash"], new_password):
            raise ValueError("Mật khẩu mới phải khác mật khẩu tạm thời hiện tại.")
        cur.execute(
            "UPDATE users SET password_hash=%s, must_change_password=0 WHERE user_id=%s",
            (generate_password_hash(new_password), int(user_id)),
        )
    return get_user_by_id(int(user_id))

