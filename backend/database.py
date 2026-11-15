# -*- coding: utf-8 -*-
"""
CookMate Relational Database Layer (SQLite3)
============================================
Implements the 8 core entities from the CookMate architecture specification:
  1. users              (NGUOIDUNG)
  2. categories         (DANHMUC)
  3. ingredients        (NGUYENLIEU)
  4. recipes            (CONGTHUC)
  5. recipe_ingredients (CONGTHUC_NGUYENLIEU)
  6. recipe_steps       (BUOCLAM)
  7. comments           (BINHLUAN)
  8. favorites          (YEUTHICH)

Provides business logic for all 21 Use Cases (UC01 - UC21), including:
  - UC06-A: Dynamic portion scaling (scale_recipe)
  - UC06-B: Automatic nutrition estimation (estimate_nutrition)
  - UC18:   Recipe approval workflow (pending -> approved / rejected)
  - UC20:   Account status locking / unlocking
"""

import json
import math
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.flask_compat import check_password_hash, generate_password_hash
from backend.seed import seed_all_tables

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "database")
DEFAULT_DB_PATH = os.path.join(DB_DIR, "cookmate.db")


def get_db_path() -> str:
    return os.environ.get("COOKMATE_DB_PATH", DEFAULT_DB_PATH)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    avatar TEXT DEFAULT 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=200&h=200&fit=crop&crop=face',
    bio TEXT DEFAULT '',
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('user', 'member', 'admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    favorites_json TEXT DEFAULT '[]',
    joined_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    icon TEXT DEFAULT 'restaurant',
    description TEXT DEFAULT '',
    image TEXT DEFAULT '',
    recipe_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Khác',
    calories INTEGER DEFAULT 50,
    unit TEXT DEFAULT '100g',
    protein REAL DEFAULT 2.0,
    fat REAL DEFAULT 1.0,
    carbs REAL DEFAULT 5.0,
    fiber REAL DEFAULT 0.5,
    popular INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT NOT NULL,
    image TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    category_name TEXT NOT NULL DEFAULT '',
    cuisine TEXT NOT NULL DEFAULT 'Món Việt',
    prep_time INTEGER NOT NULL DEFAULT 15,
    cook_time INTEGER NOT NULL DEFAULT 30,
    total_time INTEGER NOT NULL DEFAULT 45,
    servings INTEGER NOT NULL DEFAULT 4,
    difficulty TEXT NOT NULL DEFAULT 'Dễ',
    calories INTEGER NOT NULL DEFAULT 350,
    rating REAL NOT NULL DEFAULT 5.0,
    review_count INTEGER NOT NULL DEFAULT 0,
    views INTEGER NOT NULL DEFAULT 0,
    featured INTEGER NOT NULL DEFAULT 0,
    holiday TEXT DEFAULT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    nutrition_json TEXT NOT NULL DEFAULT '{}',
    author_id INTEGER NOT NULL DEFAULT 1,
    author_name TEXT NOT NULL DEFAULT 'Đầu bếp CookMate',
    author_avatar TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected'))
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    amount TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recipe_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    step INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    time INTEGER NOT NULL DEFAULT 5,
    tip TEXT DEFAULT NULL,
    image TEXT DEFAULT NULL,
    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    user_avatar TEXT NOT NULL DEFAULT '',
    rating INTEGER NOT NULL DEFAULT 5 CHECK (rating >= 1 AND rating <= 5),
    comment TEXT NOT NULL,
    date TEXT NOT NULL,
    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER NOT NULL,
    recipe_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, recipe_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
);
"""


def init_db(db_path: Optional[str] = None, force_reset: bool = False) -> None:
    """Create all tables and seed initial data if empty (or when force_reset=True)."""
    conn = get_connection(db_path)
    try:
        if force_reset:
            conn.executescript(
                """
                DROP TABLE IF EXISTS favorites;
                DROP TABLE IF EXISTS comments;
                DROP TABLE IF EXISTS recipe_steps;
                DROP TABLE IF EXISTS recipe_ingredients;
                DROP TABLE IF EXISTS recipes;
                DROP TABLE IF EXISTS ingredients;
                DROP TABLE IF EXISTS categories;
                DROP TABLE IF EXISTS users;
                """
            )
        conn.executescript(SCHEMA_SQL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM recipes")
        recipe_count = cur.fetchone()[0]
        if user_count == 0 or recipe_count == 0:
            seed_all_tables(conn)
    finally:
        conn.close()


def slugify_vietnamese(text: str) -> str:
    """Convert Vietnamese text into a URL-friendly slug."""
    if not text:
        return "cong-thuc"
    s = text.lower().strip()
    replacements = {
        r"[àáạảãâầấậẩẫăằắặẳẵ]": "a",
        r"[èéẹẻẽêềếệểễ]": "e",
        r"[ìíịỉĩ]": "i",
        r"[òóọỏõôồốộổỗơờớợởỡ]": "o",
        r"[ùúụủũưừứựửữ]": "u",
        r"[ỳýỵỷỹ]": "y",
        r"đ": "d",
    }
    for pattern, repl in replacements.items():
        s = re.sub(pattern, repl, s)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return s or "cong-thuc"


# ============================================================
# UC06-A & UC06-B: PORTION SCALING & NUTRITION ESTIMATION
# ============================================================

def _parse_amount_value(amount_str: str) -> Optional[float]:
    if amount_str is None:
        return None
    s = str(amount_str).strip()
    if not s:
        return None
    # Handle fractions like "1/2", "1/4"
    frac_match = re.match(r"^(\d+)\s*/\s*(\d+)$", s)
    if frac_match:
        denom = float(frac_match.group(2))
        if denom != 0:
            return float(frac_match.group(1)) / denom
    # Handle plain numbers "500", "1.5"
    num_match = re.match(r"^(\d+(?:[.,]\d+)?)", s)
    if num_match:
        return float(num_match.group(1).replace(",", "."))
    return None


def _format_scaled_amount(val: float) -> str:
    if val <= 0:
        return "0"
    rounded = round(val * 10) / 10.0
    if abs(rounded - round(rounded)) < 1e-6:
        return str(int(round(rounded)))
    return f"{rounded:.1f}".rstrip("0").rstrip(".")


def estimate_nutrition(
    ingredients_list: List[Dict[str, Any]],
    servings: int = 2,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    UC06-B: Estimate nutritional values per serving from recipe ingredients
    against the master ingredients table (NGUYENLIEU).
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM ingredients").fetchall()
        master_ings = [dict(r) for r in rows]
    finally:
        conn.close()

    servings = max(1, int(servings or 2))
    total_cal = 0.0
    total_protein = 0.0
    total_fat = 0.0
    total_carbs = 0.0
    total_fiber = 0.0

    # Unit conversion multipliers to approximate 100g equivalents
    unit_to_100g = {
        "g": 0.01,
        "gram": 0.01,
        "gr": 0.01,
        "kg": 10.0,
        "ml": 0.01,
        "lít": 10.0,
        "lit": 10.0,
        "muỗng canh": 0.15,
        "thìa canh": 0.15,
        "muỗng cà phê": 0.05,
        "thìa cà phê": 0.05,
        "quả": 0.6,
        "trái": 0.8,
        "củ": 0.75,
        "bó": 1.5,
        "nhánh": 0.1,
        "tép": 0.05,
        "lá": 0.02,
        "miếng": 0.5,
        "lát": 0.25,
        "cây": 0.4,
        "gói": 1.0,
        "hộp": 1.5,
        "lon": 2.0,
        "chén": 1.5,
        "bát": 2.0,
        "tô": 3.0,
        "con": 1.5,
    }

    for item in ingredients_list or []:
        raw_name = str(item.get("name", "")).strip().lower()
        if not raw_name:
            continue
        amount_val = _parse_amount_value(str(item.get("amount", "")))
        if amount_val is None or amount_val <= 0:
            amount_val = 1.0
        unit_str = str(item.get("unit", "")).strip().lower()

        # Match ingredient from master database
        matched = None
        for m in master_ings:
            m_name = m["name"].lower()
            if m_name == raw_name or m_name in raw_name or raw_name in m_name:
                matched = m
                break

        factor = unit_to_100g.get(unit_str, 0.35) * amount_val
        if matched:
            cal_base = float(matched.get("calories") or 50)
            prot_base = float(matched.get("protein") or 2.0)
            fat_base = float(matched.get("fat") or 1.0)
            carb_base = float(matched.get("carbs") or 5.0)
            fib_base = float(matched.get("fiber") or 0.5)
        else:
            cal_base = 85.0
            prot_base = 4.0
            fat_base = 3.0
            carb_base = 10.0
            fib_base = 1.0

        total_cal += cal_base * factor
        total_protein += prot_base * factor
        total_fat += fat_base * factor
        total_carbs += carb_base * factor
        total_fiber += fib_base * factor

    per_cal = max(120, min(1200, int(round(total_cal / servings)))) if ingredients_list else 350
    per_prot = max(2, int(round(total_protein / servings))) if ingredients_list else 15
    per_fat = max(2, int(round(total_fat / servings))) if ingredients_list else 10
    per_carb = max(5, int(round(total_carbs / servings))) if ingredients_list else 40
    per_fib = max(1, int(round(total_fiber / servings))) if ingredients_list else 3

    return {
        "calories": per_cal,
        "protein": f"{per_prot}g",
        "fat": f"{per_fat}g",
        "carbs": f"{per_carb}g",
        "fiber": f"{per_fib}g",
    }


def scale_recipe(
    recipe_id: int, target_servings: int, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    UC06-A: Dynamically scale ingredient quantities and total nutrition for target_servings.
    """
    recipe = get_recipe_by_id(recipe_id, db_path=db_path)
    if not recipe:
        return None
    base_servings = max(1, int(recipe.get("servings") or 1))
    target_servings = max(1, min(50, int(target_servings or base_servings)))
    ratio = target_servings / float(base_servings)

    scaled_ingredients = []
    for ing in recipe.get("ingredients", []):
        raw_amount = str(ing.get("amount", "")).strip()
        num_val = _parse_amount_value(raw_amount)
        if num_val is not None:
            scaled_amount = _format_scaled_amount(num_val * ratio)
        else:
            scaled_amount = raw_amount
        scaled_ingredients.append(
            {
                "name": ing.get("name", ""),
                "amount": scaled_amount,
                "originalAmount": raw_amount,
                "unit": ing.get("unit", ""),
            }
        )

    base_nutrition = recipe.get("nutrition") or {}
    base_cal = int(base_nutrition.get("calories") or recipe.get("calories") or 350)

    return {
        "recipeId": recipe["id"],
        "baseServings": base_servings,
        "targetServings": target_servings,
        "scaleRatio": round(ratio, 3),
        "ingredients": scaled_ingredients,
        "caloriesPerServing": base_cal,
        "totalCaloriesForServings": int(round(base_cal * target_servings)),
        "nutritionPerServing": base_nutrition,
    }


# ============================================================
# SERIALIZATION HELPERS
# ============================================================

def _row_to_user(row: sqlite3.Row, include_sensitive: bool = False) -> Dict[str, Any]:
    favs = []
    try:
        favs = json.loads(row["favorites_json"] or "[]")
    except Exception:
        favs = []
    user = {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "avatar": row["avatar"],
        "bio": row["bio"] or "",
        "role": row["role"],
        "status": row["status"],
        "favorites": favs,
        "joinedAt": row["joined_at"],
    }
    if include_sensitive:
        user["password_hash"] = row["password_hash"]
    return user


def _hydrate_recipes(conn: sqlite3.Connection, recipe_rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    if not recipe_rows:
        return []
    recipe_ids = [r["id"] for r in recipe_rows]
    placeholders = ",".join(["?"] * len(recipe_ids))

    ing_rows = conn.execute(
        f"SELECT * FROM recipe_ingredients WHERE recipe_id IN ({placeholders}) ORDER BY recipe_id, sort_order, id",
        recipe_ids,
    ).fetchall()
    step_rows = conn.execute(
        f"SELECT * FROM recipe_steps WHERE recipe_id IN ({placeholders}) ORDER BY recipe_id, step, id",
        recipe_ids,
    ).fetchall()
    comment_rows = conn.execute(
        f"SELECT * FROM comments WHERE recipe_id IN ({placeholders}) ORDER BY id DESC",
        recipe_ids,
    ).fetchall()

    ings_by_recipe: Dict[int, List[Dict[str, Any]]] = {rid: [] for rid in recipe_ids}
    for r in ing_rows:
        ings_by_recipe[r["recipe_id"]].append(
            {"name": r["name"], "amount": r["amount"], "unit": r["unit"]}
        )

    steps_by_recipe: Dict[int, List[Dict[str, Any]]] = {rid: [] for rid in recipe_ids}
    for r in step_rows:
        step_obj: Dict[str, Any] = {
            "step": r["step"],
            "title": r["title"],
            "description": r["description"],
            "time": r["time"],
        }
        if r["tip"]:
            step_obj["tip"] = r["tip"]
        if r["image"]:
            step_obj["image"] = r["image"]
        steps_by_recipe[r["recipe_id"]].append(step_obj)

    comments_by_recipe: Dict[int, List[Dict[str, Any]]] = {rid: [] for rid in recipe_ids}
    for r in comment_rows:
        comments_by_recipe[r["recipe_id"]].append(
            {
                "id": r["id"],
                "recipeId": r["recipe_id"],
                "userId": r["user_id"],
                "userName": r["user_name"],
                "userAvatar": r["user_avatar"],
                "rating": r["rating"],
                "comment": r["comment"],
                "date": r["date"],
            }
        )

    results = []
    for r in recipe_rows:
        rid = r["id"]
        try:
            tags = json.loads(r["tags_json"] or "[]")
        except Exception:
            tags = []
        try:
            nutrition = json.loads(r["nutrition_json"] or "{}")
        except Exception:
            nutrition = {}
        if not nutrition:
            nutrition = {
                "calories": r["calories"],
                "protein": "15g",
                "fat": "10g",
                "carbs": "40g",
                "fiber": "3g",
            }
        comments_list = comments_by_recipe.get(rid, [])
        results.append(
            {
                "id": rid,
                "title": r["title"],
                "slug": r["slug"],
                "description": r["description"],
                "image": r["image"],
                "categoryId": r["category_id"],
                "categoryName": r["category_name"],
                "cuisine": r["cuisine"],
                "prepTime": r["prep_time"],
                "cookTime": r["cook_time"],
                "totalTime": r["total_time"],
                "servings": r["servings"],
                "difficulty": r["difficulty"],
                "calories": r["calories"],
                "rating": round(float(r["rating"] or 5.0), 1),
                "reviewCount": r["review_count"],
                "views": r["views"],
                "featured": bool(r["featured"]),
                "holiday": r["holiday"],
                "tags": tags,
                "ingredients": ings_by_recipe.get(rid, []),
                "steps": steps_by_recipe.get(rid, []),
                "nutrition": nutrition,
                "author": {
                    "id": r["author_id"],
                    "name": r["author_name"],
                    "avatar": r["author_avatar"],
                },
                "createdAt": r["created_at"],
                "status": r["status"],
                "comments": comments_list,
            }
        )
    return results


# ============================================================
# USERS & AUTHENTICATION (UC11, UC12, UC14, UC20)
# ============================================================

def get_all_users(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
        return [_row_to_user(r) for r in rows]
    finally:
        conn.close()


def get_user_by_id(user_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        conn.close()


def authenticate_user(
    email: str, password: str, db_path: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    UC12: Authenticate user by email & password.
    Returns (user_dict, error_message). Checks locked status (UC20).
    """
    if not email or not password:
        return None, "Vui lòng nhập đầy đủ email và mật khẩu."
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email.strip(),)
        ).fetchone()
        if not row:
            return None, "Email hoặc mật khẩu không chính xác."
        if not check_password_hash(row["password_hash"], password):
            return None, "Email hoặc mật khẩu không chính xác."
        if row["status"] == "inactive":
            return None, "Tài khoản của bạn đã bị tạm khóa bởi Quản trị viên."
        return _row_to_user(row), None
    finally:
        conn.close()


def register_user(
    name: str,
    email: str,
    password: str,
    avatar: Optional[str] = None,
    bio: str = "",
    db_path: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """UC11: Register a new user account with hashed password."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name or not email or not password:
        return None, "Vui lòng điền đầy đủ họ tên, email và mật khẩu."
    if len(password) < 6:
        return None, "Mật khẩu phải có ít nhất 6 ký tự."

    default_avatar = (
        avatar
        or "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=200&h=200&fit=crop&crop=face"
    )
    joined_at = datetime.now().strftime("%Y-%m-%d")
    pw_hash = generate_password_hash(password)

    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?)", (email,)
        ).fetchone()
        if existing:
            return None, "Email này đã được sử dụng. Vui lòng chọn email khác."
        cur = conn.execute(
            """
            INSERT INTO users (name, email, password_hash, avatar, bio, role, status, favorites_json, joined_at)
            VALUES (?, ?, ?, ?, ?, 'user', 'active', '[]', ?)
            """,
            (name, email, pw_hash, default_avatar, bio or "Thành viên mới của cộng đồng CookMate.", joined_at),
        )
        conn.commit()
        user_id = cur.lastrowid
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row), None
    finally:
        conn.close()


def update_user_profile(
    user_id: int, updates: Dict[str, Any], db_path: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """UC14: Update user profile (name, email, bio, avatar, password)."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        if not row:
            return None, "Không tìm thấy người dùng."

        new_name = str(updates.get("name", row["name"])).strip() or row["name"]
        new_email = str(updates.get("email", row["email"])).strip().lower() or row["email"]
        new_bio = str(updates.get("bio", row["bio"] or "")).strip()
        new_avatar = str(updates.get("avatar", row["avatar"])).strip() or row["avatar"]

        if new_email.lower() != row["email"].lower():
            dup = conn.execute(
                "SELECT id FROM users WHERE LOWER(email) = LOWER(?) AND id != ?",
                (new_email, int(user_id)),
            ).fetchone()
            if dup:
                return None, "Email này đã được tài khoản khác sử dụng."

        pw_hash = row["password_hash"]
        if updates.get("newPassword"):
            new_pw = str(updates["newPassword"])
            if len(new_pw) < 6:
                return None, "Mật khẩu mới phải từ 6 ký tự trở lên."
            pw_hash = generate_password_hash(new_pw)

        conn.execute(
            """
            UPDATE users
            SET name = ?, email = ?, bio = ?, avatar = ?, password_hash = ?
            WHERE id = ?
            """,
            (new_name, new_email, new_bio, new_avatar, pw_hash, int(user_id)),
        )
        # Keep denormalized author_name & comment user_name in sync
        conn.execute(
            "UPDATE recipes SET author_name = ?, author_avatar = ? WHERE author_id = ?",
            (new_name, new_avatar, int(user_id)),
        )
        conn.execute(
            "UPDATE comments SET user_name = ?, user_avatar = ? WHERE user_id = ?",
            (new_name, new_avatar, int(user_id)),
        )
        conn.commit()
        updated_row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        return _row_to_user(updated_row), None
    finally:
        conn.close()


def set_user_status(
    user_id: int, status: str, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """UC20: Lock or unlock a user account ('active' | 'inactive')."""
    if status not in ("active", "inactive"):
        return None
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE users SET status = ? WHERE id = ?", (status, int(user_id))
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        return _row_to_user(row) if row else None
    finally:
        conn.close()


# ============================================================
# RECIPES CRUD & APPROVAL WORKFLOW (UC01-UC10, UC16-UC18)
# ============================================================

def _recalculate_category_counts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE categories
        SET recipe_count = (
            SELECT COUNT(*) FROM recipes
            WHERE recipes.category_id = categories.id
              AND recipes.status = 'approved'
        )
        """
    )


def get_all_recipes(
    status: Optional[str] = None,
    category_id: Optional[int] = None,
    author_id: Optional[int] = None,
    featured: Optional[bool] = None,
    holiday: Optional[str] = None,
    search: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        clauses = []
        params: List[Any] = []
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if category_id is not None:
            clauses.append("category_id = ?")
            params.append(int(category_id))
        if author_id is not None:
            clauses.append("author_id = ?")
            params.append(int(author_id))
        if featured is not None:
            clauses.append("featured = ?")
            params.append(1 if featured else 0)
        if holiday:
            clauses.append("holiday = ?")
            params.append(holiday)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM recipes {where_sql} ORDER BY id ASC", params
        ).fetchall()
        recipes = _hydrate_recipes(conn, rows)

        if search:
            q_norm = slugify_vietnamese(search).replace("-", " ")
            q_lower = search.strip().lower()
            synonym_groups = [
                ["uc ga", "ức gà", "dui ga", "đùi gà", "canh ga", "thit ga", "thịt gà", "ga ta"],
                ["thit lon", "thịt lợn", "thit heo", "thịt heo", "ba chi", "ba roi", "suon"],
                ["than bo", "bap bo", "nam bo", "thit bo", "thịt bò"],
                ["dau phu", "đậu phụ", "dau hu", "đậu hũ", "tau hu"],
            ]
            search_terms = [q_lower, q_norm]
            for grp in synonym_groups:
                if any(s in q_lower or s in q_norm for s in grp):
                    search_terms.extend(grp)

            filtered = []
            for r in recipes:
                haystack = " ".join(
                    [
                        r["title"],
                        r["description"],
                        r["categoryName"],
                        " ".join(r.get("tags", [])),
                        " ".join(i["name"] for i in r.get("ingredients", [])),
                    ]
                )
                h_lower = haystack.lower()
                h_norm = slugify_vietnamese(haystack).replace("-", " ")
                if any(t in h_lower or t in h_norm for t in search_terms if t):
                    filtered.append(r)
            return filtered
        return recipes
    finally:
        conn.close()


def get_recipe_by_id(
    recipe_id: int, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM recipes WHERE id = ?", (int(recipe_id),)
        ).fetchone()
        if not row:
            return None
        hydrated = _hydrate_recipes(conn, [row])
        return hydrated[0] if hydrated else None
    finally:
        conn.close()


def create_recipe(
    data: Dict[str, Any],
    actor_role: str = "user",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    UC08 / UC16: Create a new recipe.
    - User submissions default to 'pending' (awaiting Admin approval in UC18).
    - Admin submissions default to 'approved' (or explicit data['status']).
    """
    conn = get_connection(db_path)
    try:
        title = str(data.get("title", "Công thức mới")).strip() or "Công thức mới"
        slug = data.get("slug") or slugify_vietnamese(title)
        description = str(data.get("description", "")).strip()
        image = (
            str(data.get("image", "")).strip()
            or "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=800&h=600&fit=crop"
        )
        category_id = int(data.get("categoryId") or 3)
        cat_row = conn.execute(
            "SELECT name FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        category_name = data.get("categoryName") or (cat_row["name"] if cat_row else "Món chính")

        cuisine = str(data.get("cuisine") or "Món Việt")
        prep_time = int(data.get("prepTime") or 15)
        cook_time = int(data.get("cookTime") or 20)
        total_time = int(data.get("totalTime") or (prep_time + cook_time))
        servings = max(1, int(data.get("servings") or 2))
        difficulty = str(data.get("difficulty") or "Dễ")
        featured = 1 if data.get("featured") else 0
        holiday = data.get("holiday") or None
        tags = data.get("tags") if isinstance(data.get("tags"), list) else []
        ingredients = data.get("ingredients") if isinstance(data.get("ingredients"), list) else []
        steps = data.get("steps") if isinstance(data.get("steps"), list) else []

        # Calculate nutrition automatically if not provided
        nutrition = data.get("nutrition")
        if not isinstance(nutrition, dict) or not nutrition.get("calories"):
            nutrition = estimate_nutrition(ingredients, servings=servings, db_path=db_path)

        calories = int(data.get("calories") or nutrition.get("calories") or 350)
        nutrition["calories"] = calories

        author_obj = data.get("author") if isinstance(data.get("author"), dict) else {}
        author_id = int(author_obj.get("id") or data.get("authorId") or 1)
        author_name = str(author_obj.get("name") or data.get("authorName") or "Thành viên CookMate")
        author_avatar = str(
            author_obj.get("avatar")
            or data.get("authorAvatar")
            or "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=200&h=200&fit=crop&crop=face"
        )

        # Role-based approval rule (AI_RULES.md & PROJECT_STATUS.md)
        if actor_role == "admin":
            status = data.get("status") if data.get("status") in ("pending", "approved", "rejected") else "approved"
        else:
            status = data.get("status") if data.get("status") in ("pending", "approved", "rejected") else "pending"

        created_at = str(data.get("createdAt") or datetime.now().strftime("%Y-%m-%d"))
        rating = float(data.get("rating") or 5.0)
        review_count = int(data.get("reviewCount") or 0)
        views = int(data.get("views") or 1)

        explicit_id = data.get("id")
        if explicit_id is not None:
            existing = conn.execute("SELECT id FROM recipes WHERE id = ?", (int(explicit_id),)).fetchone()
            if existing:
                explicit_id = None

        if explicit_id is not None:
            cur = conn.execute(
                """
                INSERT INTO recipes (
                    id, title, slug, description, image, category_id, category_name,
                    cuisine, prep_time, cook_time, total_time, servings, difficulty,
                    calories, rating, review_count, views, featured, holiday,
                    tags_json, nutrition_json, author_id, author_name, author_avatar,
                    created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(explicit_id),
                    title,
                    slug,
                    description,
                    image,
                    category_id,
                    category_name,
                    cuisine,
                    prep_time,
                    cook_time,
                    total_time,
                    servings,
                    difficulty,
                    calories,
                    rating,
                    review_count,
                    views,
                    featured,
                    holiday,
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(nutrition, ensure_ascii=False),
                    author_id,
                    author_name,
                    author_avatar,
                    created_at,
                    status,
                ),
            )
            recipe_id = int(explicit_id)
        else:
            cur = conn.execute(
                """
                INSERT INTO recipes (
                    title, slug, description, image, category_id, category_name,
                    cuisine, prep_time, cook_time, total_time, servings, difficulty,
                    calories, rating, review_count, views, featured, holiday,
                    tags_json, nutrition_json, author_id, author_name, author_avatar,
                    created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    slug,
                    description,
                    image,
                    category_id,
                    category_name,
                    cuisine,
                    prep_time,
                    cook_time,
                    total_time,
                    servings,
                    difficulty,
                    calories,
                    rating,
                    review_count,
                    views,
                    featured,
                    holiday,
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(nutrition, ensure_ascii=False),
                    author_id,
                    author_name,
                    author_avatar,
                    created_at,
                    status,
                ),
            )
            recipe_id = cur.lastrowid

        for idx, ing in enumerate(ingredients):
            conn.execute(
                """
                INSERT INTO recipe_ingredients (recipe_id, sort_order, name, amount, unit)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    recipe_id,
                    idx,
                    str(ing.get("name", "")).strip(),
                    str(ing.get("amount", "")).strip(),
                    str(ing.get("unit", "")).strip(),
                ),
            )

        for idx, step in enumerate(steps):
            conn.execute(
                """
                INSERT INTO recipe_steps (recipe_id, step, title, description, time, tip, image)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recipe_id,
                    int(step.get("step") or (idx + 1)),
                    str(step.get("title") or f"Bước {idx + 1}").strip(),
                    str(step.get("description") or "").strip(),
                    int(step.get("time") or 5),
                    step.get("tip"),
                    step.get("image"),
                ),
            )

        _recalculate_category_counts(conn)
        conn.commit()
    finally:
        conn.close()

    return get_recipe_by_id(recipe_id, db_path=db_path)


def update_recipe(
    recipe_id: int, updates: Dict[str, Any], db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """UC09 / UC16: Update an existing recipe (works for both static 1-16 and user recipes)."""
    existing = get_recipe_by_id(recipe_id, db_path=db_path)
    if not existing:
        return None

    conn = get_connection(db_path)
    try:
        title = str(updates.get("title", existing["title"])).strip() or existing["title"]
        slug = updates.get("slug") or slugify_vietnamese(title)
        description = str(updates.get("description", existing["description"])).strip()
        image = str(updates.get("image", existing["image"])).strip() or existing["image"]
        category_id = int(updates.get("categoryId", existing["categoryId"]))
        cat_row = conn.execute(
            "SELECT name FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        category_name = updates.get("categoryName") or (
            cat_row["name"] if cat_row else existing["categoryName"]
        )
        cuisine = str(updates.get("cuisine", existing["cuisine"]))
        prep_time = int(updates.get("prepTime", existing["prepTime"]))
        cook_time = int(updates.get("cookTime", existing["cookTime"]))
        total_time = int(updates.get("totalTime", prep_time + cook_time))
        servings = max(1, int(updates.get("servings", existing["servings"])))
        difficulty = str(updates.get("difficulty", existing["difficulty"]))
        featured = 1 if updates.get("featured", existing["featured"]) else 0
        holiday = updates.get("holiday", existing["holiday"])
        status = updates.get("status", existing["status"])
        if status not in ("pending", "approved", "rejected"):
            status = existing["status"]

        tags = updates.get("tags") if isinstance(updates.get("tags"), list) else existing["tags"]
        ingredients = (
            updates.get("ingredients")
            if isinstance(updates.get("ingredients"), list)
            else existing["ingredients"]
        )
        steps = (
            updates.get("steps")
            if isinstance(updates.get("steps"), list)
            else existing["steps"]
        )

        if "ingredients" in updates and "nutrition" not in updates:
            nutrition = estimate_nutrition(ingredients, servings=servings, db_path=db_path)
        else:
            nutrition = updates.get("nutrition") or existing["nutrition"]

        calories = int(updates.get("calories") or nutrition.get("calories") or existing["calories"])
        nutrition["calories"] = calories

        conn.execute(
            """
            UPDATE recipes
            SET title = ?, slug = ?, description = ?, image = ?,
                category_id = ?, category_name = ?, cuisine = ?,
                prep_time = ?, cook_time = ?, total_time = ?,
                servings = ?, difficulty = ?, calories = ?,
                featured = ?, holiday = ?, tags_json = ?,
                nutrition_json = ?, status = ?
            WHERE id = ?
            """,
            (
                title,
                slug,
                description,
                image,
                category_id,
                category_name,
                cuisine,
                prep_time,
                cook_time,
                total_time,
                servings,
                difficulty,
                calories,
                featured,
                holiday,
                json.dumps(tags, ensure_ascii=False),
                json.dumps(nutrition, ensure_ascii=False),
                status,
                int(recipe_id),
            ),
        )

        if "ingredients" in updates and isinstance(updates["ingredients"], list):
            conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (int(recipe_id),))
            for idx, ing in enumerate(ingredients):
                conn.execute(
                    """
                    INSERT INTO recipe_ingredients (recipe_id, sort_order, name, amount, unit)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        int(recipe_id),
                        idx,
                        str(ing.get("name", "")).strip(),
                        str(ing.get("amount", "")).strip(),
                        str(ing.get("unit", "")).strip(),
                    ),
                )

        if "steps" in updates and isinstance(updates["steps"], list):
            conn.execute("DELETE FROM recipe_steps WHERE recipe_id = ?", (int(recipe_id),))
            for idx, step in enumerate(steps):
                conn.execute(
                    """
                    INSERT INTO recipe_steps (recipe_id, step, title, description, time, tip, image)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(recipe_id),
                        int(step.get("step") or (idx + 1)),
                        str(step.get("title") or f"Bước {idx + 1}").strip(),
                        str(step.get("description") or "").strip(),
                        int(step.get("time") or 5),
                        step.get("tip"),
                        step.get("image"),
                    ),
                )

        _recalculate_category_counts(conn)
        conn.commit()
    finally:
        conn.close()

    return get_recipe_by_id(recipe_id, db_path=db_path)


def delete_recipe(recipe_id: int, db_path: Optional[str] = None) -> bool:
    """UC10 / UC16: Delete a recipe and cascade its ingredients, steps, comments, favorites."""
    conn = get_connection(db_path)
    try:
        cur = conn.execute("DELETE FROM recipes WHERE id = ?", (int(recipe_id),))
        _recalculate_category_counts(conn)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_recipe_status(
    recipe_id: int, status: str, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """UC18: Approve ('approved') or Reject ('rejected') a recipe."""
    if status not in ("pending", "approved", "rejected"):
        return None
    return update_recipe(recipe_id, {"status": status}, db_path=db_path)


def increment_recipe_views(recipe_id: int, db_path: Optional[str] = None) -> int:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE recipes SET views = views + 1 WHERE id = ?", (int(recipe_id),)
        )
        conn.commit()
        row = conn.execute(
            "SELECT views FROM recipes WHERE id = ?", (int(recipe_id),)
        ).fetchone()
        return int(row["views"]) if row else 0
    finally:
        conn.close()


# ============================================================
# CATEGORIES CRUD (UC04, UC17)
# ============================================================

def get_all_categories(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        _recalculate_category_counts(conn)
        conn.commit()
        rows = conn.execute("SELECT * FROM categories ORDER BY id ASC").fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "slug": r["slug"],
                "icon": r["icon"],
                "description": r["description"],
                "image": r["image"],
                "recipeCount": r["recipe_count"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def create_category(
    data: Dict[str, Any], db_path: Optional[str] = None
) -> Dict[str, Any]:
    name = str(data.get("name", "Danh mục mới")).strip() or "Danh mục mới"
    slug = data.get("slug") or slugify_vietnamese(name)
    icon = str(data.get("icon") or "restaurant").strip()
    description = str(data.get("description") or "").strip()
    image = (
        str(data.get("image") or "").strip()
        or "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=600&h=400&fit=crop"
    )
    conn = get_connection(db_path)
    try:
        # Ensure unique slug
        base_slug = slug
        counter = 1
        while conn.execute("SELECT id FROM categories WHERE slug = ?", (slug,)).fetchone():
            counter += 1
            slug = f"{base_slug}-{counter}"
        cur = conn.execute(
            """
            INSERT INTO categories (name, slug, icon, description, image, recipe_count)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (name, slug, icon, description, image),
        )
        conn.commit()
        cid = cur.lastrowid
        row = conn.execute("SELECT * FROM categories WHERE id = ?", (cid,)).fetchone()
        return {
            "id": row["id"],
            "name": row["name"],
            "slug": row["slug"],
            "icon": row["icon"],
            "description": row["description"],
            "image": row["image"],
            "recipeCount": row["recipe_count"],
        }
    finally:
        conn.close()


def update_category(
    cat_id: int, updates: Dict[str, Any], db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM categories WHERE id = ?", (int(cat_id),)).fetchone()
        if not row:
            return None
        name = str(updates.get("name", row["name"])).strip() or row["name"]
        slug = str(updates.get("slug") or slugify_vietnamese(name))
        icon = str(updates.get("icon", row["icon"])).strip() or row["icon"]
        description = str(updates.get("description", row["description"])).strip()
        image = str(updates.get("image", row["image"])).strip() or row["image"]
        conn.execute(
            """
            UPDATE categories
            SET name = ?, slug = ?, icon = ?, description = ?, image = ?
            WHERE id = ?
            """,
            (name, slug, icon, description, image, int(cat_id)),
        )
        conn.execute(
            "UPDATE recipes SET category_name = ? WHERE category_id = ?",
            (name, int(cat_id)),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM categories WHERE id = ?", (int(cat_id),)).fetchone()
        return {
            "id": updated["id"],
            "name": updated["name"],
            "slug": updated["slug"],
            "icon": updated["icon"],
            "description": updated["description"],
            "image": updated["image"],
            "recipeCount": updated["recipe_count"],
        }
    finally:
        conn.close()


def delete_category(cat_id: int, db_path: Optional[str] = None) -> bool:
    conn = get_connection(db_path)
    try:
        cur = conn.execute("DELETE FROM categories WHERE id = ?", (int(cat_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def sync_categories(
    categories_list: List[Dict[str, Any]], db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Sync full categories list from Admin SPA (UC17)."""
    if not isinstance(categories_list, list):
        return get_all_categories(db_path=db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM categories")
        for idx, c in enumerate(categories_list):
            cid = int(c.get("id") or (idx + 1))
            name = str(c.get("name") or "Danh mục").strip()
            slug = str(c.get("slug") or slugify_vietnamese(name))
            # Avoid duplicate slug constraint violations
            if conn.execute("SELECT id FROM categories WHERE slug = ?", (slug,)).fetchone():
                slug = f"{slug}-{cid}"
            conn.execute(
                """
                INSERT INTO categories (id, name, slug, icon, description, image, recipe_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    name,
                    slug,
                    str(c.get("icon") or "restaurant"),
                    str(c.get("description") or ""),
                    str(c.get("image") or ""),
                    int(c.get("recipeCount") or 0),
                ),
            )
        _recalculate_category_counts(conn)
        conn.commit()
    finally:
        conn.close()
    return get_all_categories(db_path=db_path)


# ============================================================
# INGREDIENTS CRUD (UC03, UC19)
# ============================================================

def get_all_ingredients(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM ingredients ORDER BY id ASC").fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "category": r["category"],
                "calories": r["calories"],
                "unit": r["unit"],
                "protein": r["protein"],
                "fat": r["fat"],
                "carbs": r["carbs"],
                "fiber": r["fiber"],
                "popular": bool(r["popular"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def create_ingredient(
    data: Dict[str, Any], db_path: Optional[str] = None
) -> Dict[str, Any]:
    name = str(data.get("name", "Nguyên liệu mới")).strip() or "Nguyên liệu mới"
    category = str(data.get("category") or "Khác").strip()
    calories = int(data.get("calories") or 50)
    unit = str(data.get("unit") or "100g").strip()
    protein = float(data.get("protein") or 2.0)
    fat = float(data.get("fat") or 1.0)
    carbs = float(data.get("carbs") or 5.0)
    fiber = float(data.get("fiber") or 0.5)
    popular = 1 if data.get("popular") else 0

    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO ingredients (name, category, calories, unit, protein, fat, carbs, fiber, popular)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, category, calories, unit, protein, fat, carbs, fiber, popular),
        )
        conn.commit()
        iid = cur.lastrowid
        row = conn.execute("SELECT * FROM ingredients WHERE id = ?", (iid,)).fetchone()
        return {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "calories": row["calories"],
            "unit": row["unit"],
            "protein": row["protein"],
            "fat": row["fat"],
            "carbs": row["carbs"],
            "fiber": row["fiber"],
            "popular": bool(row["popular"]),
        }
    finally:
        conn.close()


def update_ingredient(
    ing_id: int, updates: Dict[str, Any], db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM ingredients WHERE id = ?", (int(ing_id),)).fetchone()
        if not row:
            return None
        name = str(updates.get("name", row["name"])).strip() or row["name"]
        category = str(updates.get("category", row["category"])).strip() or row["category"]
        calories = int(updates.get("calories", row["calories"]))
        unit = str(updates.get("unit", row["unit"])).strip() or row["unit"]
        protein = float(updates.get("protein", row["protein"]))
        fat = float(updates.get("fat", row["fat"]))
        carbs = float(updates.get("carbs", row["carbs"]))
        fiber = float(updates.get("fiber", row["fiber"]))
        popular = 1 if updates.get("popular", bool(row["popular"])) else 0

        conn.execute(
            """
            UPDATE ingredients
            SET name = ?, category = ?, calories = ?, unit = ?,
                protein = ?, fat = ?, carbs = ?, fiber = ?, popular = ?
            WHERE id = ?
            """,
            (name, category, calories, unit, protein, fat, carbs, fiber, popular, int(ing_id)),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM ingredients WHERE id = ?", (int(ing_id),)).fetchone()
        return {
            "id": updated["id"],
            "name": updated["name"],
            "category": updated["category"],
            "calories": updated["calories"],
            "unit": updated["unit"],
            "protein": updated["protein"],
            "fat": updated["fat"],
            "carbs": updated["carbs"],
            "fiber": updated["fiber"],
            "popular": bool(updated["popular"]),
        }
    finally:
        conn.close()


def delete_ingredient(ing_id: int, db_path: Optional[str] = None) -> bool:
    conn = get_connection(db_path)
    try:
        cur = conn.execute("DELETE FROM ingredients WHERE id = ?", (int(ing_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def sync_ingredients(
    ingredients_list: List[Dict[str, Any]], db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Sync full ingredients list from Admin SPA (UC19)."""
    if not isinstance(ingredients_list, list):
        return get_all_ingredients(db_path=db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM ingredients")
        for idx, ing in enumerate(ingredients_list):
            iid = int(ing.get("id") or (idx + 1))
            conn.execute(
                """
                INSERT INTO ingredients (id, name, category, calories, unit, protein, fat, carbs, fiber, popular)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iid,
                    str(ing.get("name") or "Nguyên liệu").strip(),
                    str(ing.get("category") or "Khác").strip(),
                    int(ing.get("calories") or 50),
                    str(ing.get("unit") or "100g").strip(),
                    float(ing.get("protein") or 2.0),
                    float(ing.get("fat") or 1.0),
                    float(ing.get("carbs") or 5.0),
                    float(ing.get("fiber") or 0.5),
                    1 if ing.get("popular") else 0,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return get_all_ingredients(db_path=db_path)


# ============================================================
# COMMENTS & RATINGS (UC07, UC21)
# ============================================================

def _recalculate_recipe_rating(conn: sqlite3.Connection, recipe_id: int) -> None:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt, AVG(rating) AS avg_rating FROM comments WHERE recipe_id = ?",
        (int(recipe_id),),
    ).fetchone()
    cnt = int(row["cnt"] or 0)
    if cnt > 0 and row["avg_rating"] is not None:
        avg_r = round(float(row["avg_rating"]), 1)
        conn.execute(
            "UPDATE recipes SET rating = ?, review_count = ? WHERE id = ?",
            (avg_r, cnt, int(recipe_id)),
        )


def get_comments_for_recipe(
    recipe_id: int, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM comments WHERE recipe_id = ? ORDER BY id DESC",
            (int(recipe_id),),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "recipeId": r["recipe_id"],
                "userId": r["user_id"],
                "userName": r["user_name"],
                "userAvatar": r["user_avatar"],
                "rating": r["rating"],
                "comment": r["comment"],
                "date": r["date"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_all_comments(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT c.*, r.title AS recipe_title, r.image AS recipe_image
            FROM comments c
            LEFT JOIN recipes r ON c.recipe_id = r.id
            ORDER BY c.id DESC
            """
        ).fetchall()
        return [
            {
                "id": r["id"],
                "recipeId": r["recipe_id"],
                "recipeTitle": r["recipe_title"] or f"Công thức #{r['recipe_id']}",
                "recipeImage": r["recipe_image"] or "",
                "userId": r["user_id"],
                "userName": r["user_name"],
                "userAvatar": r["user_avatar"],
                "rating": r["rating"],
                "comment": r["comment"],
                "date": r["date"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def add_comment(
    recipe_id: int, data: Dict[str, Any], db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """UC07: Add a rating & comment to a recipe and recalculate its average rating."""
    comment_text = str(data.get("comment") or "").strip()
    if not comment_text:
        return None
    rating = max(1, min(5, int(data.get("rating") or 5)))
    user_id = int(data.get("userId") or 1)
    user_name = str(data.get("userName") or "Người dùng CookMate").strip()
    user_avatar = str(
        data.get("userAvatar")
        or "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=100&h=100&fit=crop&crop=face"
    ).strip()
    date_str = str(data.get("date") or datetime.now().strftime("%Y-%m-%d"))

    conn = get_connection(db_path)
    try:
        recipe_row = conn.execute(
            "SELECT id, title, image FROM recipes WHERE id = ?", (int(recipe_id),)
        ).fetchone()
        if not recipe_row:
            return None
        cur = conn.execute(
            """
            INSERT INTO comments (recipe_id, user_id, user_name, user_avatar, rating, comment, date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (int(recipe_id), user_id, user_name, user_avatar, rating, comment_text, date_str),
        )
        cid = cur.lastrowid
        _recalculate_recipe_rating(conn, int(recipe_id))
        conn.commit()
        return {
            "id": cid,
            "recipeId": int(recipe_id),
            "recipeTitle": recipe_row["title"],
            "recipeImage": recipe_row["image"],
            "userId": user_id,
            "userName": user_name,
            "userAvatar": user_avatar,
            "rating": rating,
            "comment": comment_text,
            "date": date_str,
        }
    finally:
        conn.close()


def delete_comment(comment_id: int, db_path: Optional[str] = None) -> bool:
    """UC21: Delete a comment (works for both static seed comments and user comments)."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT recipe_id FROM comments WHERE id = ?", (int(comment_id),)
        ).fetchone()
        if not row:
            return False
        recipe_id = row["recipe_id"]
        cur = conn.execute("DELETE FROM comments WHERE id = ?", (int(comment_id),))
        _recalculate_recipe_rating(conn, recipe_id)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ============================================================
# FAVORITES (UC13)
# ============================================================

def get_user_favorites(user_id: int, db_path: Optional[str] = None) -> List[int]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT recipe_id FROM favorites WHERE user_id = ? ORDER BY created_at DESC",
            (int(user_id),),
        ).fetchall()
        return [int(r["recipe_id"]) for r in rows]
    finally:
        conn.close()


def toggle_favorite(
    user_id: int, recipe_id: int, db_path: Optional[str] = None
) -> Dict[str, Any]:
    """UC13: Toggle favorite recipe for user_id and sync users.favorites_json."""
    conn = get_connection(db_path)
    try:
        existing = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND recipe_id = ?",
            (int(user_id), int(recipe_id)),
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM favorites WHERE user_id = ? AND recipe_id = ?",
                (int(user_id), int(recipe_id)),
            )
            added = False
        else:
            conn.execute(
                "INSERT INTO favorites (user_id, recipe_id, created_at) VALUES (?, ?, ?)",
                (int(user_id), int(recipe_id), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            added = True

        fav_rows = conn.execute(
            "SELECT recipe_id FROM favorites WHERE user_id = ? ORDER BY recipe_id ASC",
            (int(user_id),),
        ).fetchall()
        fav_ids = [int(r["recipe_id"]) for r in fav_rows]
        conn.execute(
            "UPDATE users SET favorites_json = ? WHERE id = ?",
            (json.dumps(fav_ids), int(user_id)),
        )
        conn.commit()
        return {"added": added, "favorites": fav_ids, "count": len(fav_ids)}
    finally:
        conn.close()


# ============================================================
# ADMIN STATISTICS & BOOTSTRAP PAYLOAD (UC15)
# ============================================================

def get_statistics(db_path: Optional[str] = None) -> Dict[str, Any]:
    """UC15: Aggregate real-time dashboard & statistics metrics."""
    conn = get_connection(db_path)
    try:
        total_recipes = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        approved_recipes = conn.execute(
            "SELECT COUNT(*) FROM recipes WHERE status = 'approved'"
        ).fetchone()[0]
        pending_recipes = conn.execute(
            "SELECT COUNT(*) FROM recipes WHERE status = 'pending'"
        ).fetchone()[0]
        rejected_recipes = conn.execute(
            "SELECT COUNT(*) FROM recipes WHERE status = 'rejected'"
        ).fetchone()[0]
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status = 'active'"
        ).fetchone()[0]
        total_categories = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        total_ingredients = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
        total_comments = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        total_views = (
            conn.execute("SELECT SUM(views) FROM recipes").fetchone()[0] or 0
        )
        avg_rating_row = conn.execute(
            "SELECT AVG(rating) FROM recipes WHERE status = 'approved'"
        ).fetchone()[0]
        avg_rating = round(float(avg_rating_row or 4.8), 2)

        top_recipes_rows = conn.execute(
            "SELECT id, title, views, rating, review_count, category_name, image FROM recipes WHERE status = 'approved' ORDER BY views DESC LIMIT 5"
        ).fetchall()
        top_recipes = [
            {
                "id": r["id"],
                "title": r["title"],
                "views": r["views"],
                "rating": r["rating"],
                "reviewCount": r["review_count"],
                "categoryName": r["category_name"],
                "image": r["image"],
            }
            for r in top_recipes_rows
        ]

        return {
            "totalRecipes": total_recipes,
            "approvedRecipes": approved_recipes,
            "pendingRecipes": pending_recipes,
            "rejectedRecipes": rejected_recipes,
            "totalUsers": total_users,
            "activeUsers": active_users,
            "lockedUsers": total_users - active_users,
            "totalCategories": total_categories,
            "totalIngredients": total_ingredients,
            "totalComments": total_comments,
            "totalViews": total_views,
            "averageRating": avg_rating,
            "topRecipes": top_recipes,
        }
    finally:
        conn.close()


def get_bootstrap_payload(
    current_user_id: Optional[int] = None, db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Returns complete state snapshot so Frontend CookMateStorage can synchronize
    seamlessly on page load.
    """
    recipes = get_all_recipes(status="all", db_path=db_path)
    categories = get_all_categories(db_path=db_path)
    ingredients = get_all_ingredients(db_path=db_path)
    users = get_all_users(db_path=db_path)
    comments = get_all_comments(db_path=db_path)
    favorites = (
        get_user_favorites(current_user_id, db_path=db_path)
        if current_user_id
        else []
    )
    return {
        "recipes": recipes,
        "categories": categories,
        "ingredients": ingredients,
        "users": users,
        "comments": comments,
        "favorites": favorites,
        "statistics": get_statistics(db_path=db_path),
    }
