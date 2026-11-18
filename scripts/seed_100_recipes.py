#!/usr/bin/env python
"""Safely seed the 100 CookMate recipes into MySQL.

Run from the repository root:
    python scripts/seed_100_recipes.py                 # read-only dry run
    python scripts/seed_100_recipes.py --apply         # backup, insert, verify

No schema changes, deletes, fixed IDs, or updates to existing recipes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import Config  # noqa: E402
from recipes_100_data import RECIPES  # noqa: E402

EXPECTED_CATEGORY_COUNTS = {
    "mon-chinh": 24,
    "mon-canh-sup": 14,
    "mon-xao": 12,
    "mon-nuong-chien": 14,
    "mon-chay": 12,
    "mon-trang-mieng": 8,
    "do-uong": 6,
    "mon-khai-vi": 10,
}
ALIASES = {
    "hanh hoa": "Hành lá",
    "hanh xanh": "Hành lá",
    "hanh kho": "Hành tím",
    "nam dong co": "Nấm hương",
    "dau hu": "Đậu hũ",
}


def normalize(value: str) -> str:
    value = value.strip().lower().replace("đ", "d")
    value = "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")
    return " ".join(value.split())


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")


def canonical_name(value: str) -> str:
    return ALIASES.get(normalize(value), value.strip())


def parse_ingredients(spec: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order, raw in enumerate(spec.split(";")):
        fields = [part.strip() for part in raw.split("|")]
        if len(fields) != 3:
            raise ValueError(f"Ingredient must have name, amount and unit: {raw!r}")
        marked_name, amount, unit = fields
        core = marked_name.endswith("*")
        optional = marked_name.endswith("?")
        name = canonical_name(marked_name[:-1] if core or optional else marked_name)
        if not name or not amount or not unit:
            raise ValueError(f"Ingredient fields cannot be blank: {raw!r}")
        key = normalize(name)
        if key in seen:
            raise ValueError(f"Duplicate ingredient in one recipe: {name}")
        seen.add(key)
        result.append({
            "name": name,
            "amount": amount,
            "unit": unit,
            "core": core,
            "optional": optional,
            "sort_order": order,
        })
    return result


def validate_collection() -> None:
    if len(RECIPES) != 100:
        raise ValueError(f"Expected 100 recipes, found {len(RECIPES)}.")
    counts = Counter(item["category"] for item in RECIPES)
    if dict(counts) != EXPECTED_CATEGORY_COUNTS:
        raise ValueError(f"Wrong category distribution: {dict(counts)}")
    slugs = [slugify(item["name"]) for item in RECIPES]
    if len(set(slugs)) != 100:
        raise ValueError("Recipe names do not produce 100 unique slugs.")
    for item in RECIPES:
        ingredients = parse_ingredients(item["ingredients"])
        core_count = sum(part["core"] for part in ingredients)
        if not 5 <= len(ingredients) <= 10:
            raise ValueError(f"{item['name']}: expected 5–10 ingredients, found {len(ingredients)}.")
        if not 3 <= core_count <= 7:
            raise ValueError(f"{item['name']}: expected 3–7 core ingredients, found {core_count}.")
        if not 4 <= len(item["steps"]) <= 7:
            raise ValueError(f"{item['name']}: expected 4–7 steps, found {len(item['steps'])}.")
        if item["difficulty"] not in {"Dễ", "Trung bình", "Khó"}:
            raise ValueError(f"{item['name']}: unsupported difficulty {item['difficulty']!r}.")
        if any("|" not in step or not step.split("|", 1)[1].strip() for step in item["steps"]):
            raise ValueError(f"{item['name']}: every step needs a title and instruction.")
        if item["category"] == "mon-chay":
            for part in ingredients:
                name = part["name"].lower()
                if any(term in name for term in (
                    "thịt ", "gà ", "bò ", "cá ", "tôm", "mực", "cua", "tép",
                    "trứng", "sữa", "phô mai", "mật ong", "nước mắm",
                )):
                    raise ValueError(f"Animal ingredient in vegetarian recipe {item['name']}: {part['name']}")


def ingredient_category(name: str) -> str:
    # Classify seafood using the original accents so "Cá" and "Cà" stay distinct.
    lower = name.lower().strip()
    if lower.startswith(("cá ", "tôm", "mực", "cua", "tép", "chả cá", "thịt cua")):
        return "Hải sản"
    if lower.startswith(("thịt ", "gà ", "đùi gà", "cánh gà", "sườn", "vịt ", "giò sống", "lạp xưởng", "bò khô")):
        return "Thịt"
    if lower.startswith(("dứa", "cam", "chanh", "xoài", "chuối", "tắc", "vải", "quả sấu", "me vắt", "nước dừa tươi", "đu đủ", "đào ngâm")):
        return "Trái cây"
    if lower.startswith("khoai tây"):
        return "Rau củ"
    if lower.startswith(("bắp ngọt", "ngô non")):
        return "Ngũ cốc"
    if lower.startswith("đậu hà lan"):
        return "Đậu"
    if lower.startswith(("dưa ", "cà tím", "cà chua", "cà rốt", "đậu bắp", "đậu que", "bắp cải", "bông cải", "cải ", "cần tây", "bí ", "khoai ", "ngó sen", "dọc mùng", "mồng tơi", "tía tô", "thì là", "húng quế", "xà lách", "củ sắn", "giá đỗ", "rau ", "hành lá", "hành tây", "lá lốt", "lá sen", "kim chi", "mướp", "ớt chuông")):
        return "Rau"
    key = normalize(name)
    if key.startswith("nam "):
        return "Nấm"
    if key.startswith(("dau hu", "dau nanh", "dau den", "dau xanh", "dau ga")):
        return "Đậu"
    if key.startswith("mi can"):
        return "Ngũ cốc"
    if key.startswith(("sua ", "sua chua", "kem tuoi", "trung", "bo lat", "pho mai")):
        return "Trứng sữa"
    if key.startswith(("dau an", "dau o liu", "dau me")):
        return "Dầu mỡ"
    if key.startswith("nuoc cot dua"):
        return "Nước"
    if key.startswith(("dau hao", "nuoc mam", "nuoc tuong", "sa te", "giam", "muoi", "duong", "bot ca ri", "tieu", "hanh tim", "hanh phi", "toi", "sa", "gung", "nghe", "mat ong", "tinh chat", "la dua", "nuoc cot dua", "nuoc sot me", "nuoc dung ga", "ruou vang", "tuong ca", "tuong ot")):
        return "Gia vị"
    if key.startswith(("dau phong", "hanh nhan", "me trang", "me den", "me rang")):
        return "Hạt"
    if key.startswith("bot "):
        return "Bột"
    if key.startswith(("mi ", "bun ", "mien ", "gao ", "nep ", "com ", "banh trang", "banh mi", "nui", "com nguoi", "com tam", "com", "co m")):
        return "Ngũ cốc"
    if lower.startswith(("ớt",)) and "chuông" not in lower:
        return "Gia vị"
    if key.startswith(("nuoc loc", "tra ", "da vien")):
        return "Đồ uống"
    if key == "gelatin":
        return "Khác"
    if key.startswith(("chanh", "cam", "xoai", "chuoi", "vai ", "tac", "qua sau", "tao", "me vat", "du du", "dao ngam")):
        return "Trái cây"
    if key.startswith(("bap cai", "ngo ", "cu san", "ngo sen", "doc mung", "mong toi", "rau ram", "tia to", "hung que", "thi la", "mui tay", "dua leo", "ca chua", "ca rot", "ca tim", "rau song", "hanh la", "hanh tay", "hanh phi", "kim chi", "ot chuong")):
        return "Rau"
    return "Khác"


def ingredient_catalog_unit(name: str) -> str:
    key = normalize(name)
    if key.startswith(("nuoc ", "sua tuoi", "sua chua", "dau an", "dau me", "dau o liu", "dau hao", "nuoc mam", "nuoc tuong", "giam", "mat ong", "kem tuoi")):
        return "100ml"
    return "100g"


def connect():
    try:
        from mysql.connector import connect as mysql_connect
    except ImportError as exc:
        raise RuntimeError("Thiếu mysql-connector-python. Hãy cài dependencies trong requirements.txt.") from exc
    return mysql_connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        use_unicode=True,
        autocommit=False,
        connection_timeout=5,
    )


def table_counts(cur) -> dict[str, int]:
    result = {}
    for table in ("categories", "ingredients", "dishes", "recipes", "recipe_ingredients", "recipe_steps", "recipe_sources"):
        cur.execute("SELECT COUNT(*) AS n FROM " + table)
        result[table] = int(cur.fetchone()["n"])
    return result


def print_snapshot(cur) -> dict[str, int]:
    cur.execute("SELECT DATABASE() AS db, VERSION() AS version")
    meta = cur.fetchone()
    print(f"Database: {meta['db']} | Server: {meta['version']}")
    if meta["db"] != "cookmate":
        raise RuntimeError("Từ chối ghi: MYSQL_DATABASE hiện tại không phải cookmate.")
    counts = table_counts(cur)
    for table, count in counts.items():
        print(f"  {table}: {count}")
    cur.execute("SELECT name,slug FROM categories ORDER BY category_id")
    print("Danh mục:", ", ".join(f"{row['slug']} ({row['name']})" for row in cur.fetchall()))
    cur.execute("SELECT category_id,COUNT(*) AS n FROM dishes GROUP BY category_id")
    print("Số món hiện có theo category_id:", ", ".join(f"{row['category_id']}={row['n']}" for row in cur.fetchall()))
    return counts


def resolve_categories(cur) -> dict[str, int]:
    cur.execute("SELECT category_id,slug FROM categories")
    result = {row["slug"]: int(row["category_id"]) for row in cur.fetchall()}
    missing = set(EXPECTED_CATEGORY_COUNTS) - set(result)
    if missing:
        raise RuntimeError(f"Thiếu category slug: {', '.join(sorted(missing))}")
    return result


def existing_dishes(cur) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    cur.execute("SELECT dish_id,dish_name,slug FROM dishes")
    rows = cur.fetchall()
    return (
        {str(row["slug"]).lower(): row for row in rows},
        {normalize(row["dish_name"]): row for row in rows},
    )


def find_plan(cur) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_slug, by_name = existing_dishes(cur)
    all_rows = []
    for source in RECIPES:
        target = dict(source)
        target["slug"] = slugify(source["name"])
        target["parsed_ingredients"] = parse_ingredients(source["ingredients"])
        target["existing_dish"] = by_slug.get(target["slug"]) or by_name.get(normalize(source["name"]))
        all_rows.append(target)
    pending = [row for row in all_rows if row["existing_dish"] is None]
    return all_rows, pending


def find_existing_ingredients(cur) -> dict[str, dict[str, Any]]:
    cur.execute("SELECT ingredient_id,ingredient_name,category,unit FROM ingredients")
    return {normalize(row["ingredient_name"]): row for row in cur.fetchall()}


def create_backup() -> Path:
    executable = shutil.which("mysqldump")
    if not executable:
        raise RuntimeError("Không tìm thấy mysqldump; chưa ghi dữ liệu. Hãy tạo bản sao lưu database trước khi dùng --apply.")
    backup_dir = Path(tempfile.gettempdir()) / "cookmate-db-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"cookmate-before-seed-100-{stamp}.sql"
    env = os.environ.copy()
    env["MYSQL_PWD"] = Config.MYSQL_PASSWORD
    command = [
        executable,
        "--no-defaults",
        f"--host={Config.MYSQL_HOST}",
        f"--port={Config.MYSQL_PORT}",
        f"--user={Config.MYSQL_USER}",
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--events",
        "--default-character-set=utf8mb4",
        f"--result-file={backup_path}",
        "cookmate",
    ]
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not backup_path.exists() or backup_path.stat().st_size == 0:
        backup_path.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout or "mysqldump returned no details").strip()
        raise RuntimeError(f"Sao lưu thất bại; database chưa được thay đổi. {detail}")
    return backup_path


def ensure_ingredient(cur, lookup: dict[str, dict[str, Any]], item: dict[str, Any], usage_counts: Counter) -> tuple[int, bool]:
    key = normalize(item["name"])
    if key in lookup:
        return int(lookup[key]["ingredient_id"]), False
    name = item["name"]
    category = ingredient_category(name)
    unit = ingredient_catalog_unit(name)
    cur.execute(
        "INSERT INTO ingredients(ingredient_name,category,unit,calories,protein,fat,carbs,fiber,is_popular) "
        "VALUES(%s,%s,%s,0,0,0,0,0,%s)",
        (name, category, unit, usage_counts[key] >= 8),
    )
    ingredient_id = int(cur.lastrowid)
    lookup[key] = {"ingredient_id": ingredient_id, "ingredient_name": name, "category": category, "unit": unit}
    return ingredient_id, True


def step_durations(prep: int, cook: int) -> tuple[int | None, int | None, int | None, int | None]:
    prep_first = (prep + 1) // 2
    cook_first = (cook * 2 + 2) // 3
    return (
        prep_first or None,
        (prep - prep_first) or None,
        cook_first or None,
        (cook - cook_first) or None,
    )


def verify_target(cur, target_slugs: list[str]) -> dict[str, Any]:
    placeholders = ",".join(["%s"] * len(target_slugs))
    cur.execute(
        "SELECT d.slug,d.dish_id,d.dish_name,d.category_id,r.recipe_id,r.status,r.source_type,"
        "COUNT(DISTINCT ri.id) AS ingredient_count,COUNT(DISTINCT rs.step_id) AS step_count,"
        "COUNT(DISTINCT di.id) AS dish_ingredient_count "
        "FROM dishes d LEFT JOIN recipes r ON r.dish_id=d.dish_id "
        "LEFT JOIN recipe_ingredients ri ON ri.recipe_id=r.recipe_id "
        "LEFT JOIN recipe_steps rs ON rs.recipe_id=r.recipe_id "
        "LEFT JOIN dish_ingredients di ON di.dish_id=d.dish_id "
        f"WHERE d.slug IN ({placeholders}) GROUP BY d.slug,d.dish_id,d.dish_name,d.category_id,r.recipe_id,r.status,r.source_type",
        tuple(target_slugs),
    )
    rows = cur.fetchall()
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_slug.setdefault(str(row["slug"]), []).append(row)
    missing = sorted(set(target_slugs) - set(by_slug))
    issues = []
    for slug, group in by_slug.items():
        if len(group) != 1:
            issues.append(f"{slug}: expected one recipe row, found {len(group)}")
            continue
        row = group[0]
        if row["recipe_id"] is None:
            issues.append(f"{slug}: no recipe")
        if not 5 <= int(row["ingredient_count"]) <= 10:
            issues.append(f"{slug}: {row['ingredient_count']} recipe ingredients")
        if not 4 <= int(row["step_count"]) <= 7:
            issues.append(f"{slug}: {row['step_count']} steps")
        if not 3 <= int(row["dish_ingredient_count"]) <= 7:
            issues.append(f"{slug}: {row['dish_ingredient_count']} dish ingredient links")
        if row["status"] != "APPROVED" or row["source_type"] != "DB":
            issues.append(f"{slug}: unexpected recipe status/source")
    if missing:
        issues.append("Missing dishes: " + ", ".join(missing))
    cur.execute(
        "SELECT COUNT(*) AS n FROM dish_ingredients di LEFT JOIN dishes d ON d.dish_id=di.dish_id "
        "LEFT JOIN ingredients i ON i.ingredient_id=di.ingredient_id "
        f"WHERE d.slug IN ({placeholders}) AND (d.dish_id IS NULL OR i.ingredient_id IS NULL)",
        tuple(target_slugs),
    )
    invalid_dish_links = int(cur.fetchone()["n"])
    cur.execute(
        "SELECT COUNT(*) AS n FROM recipe_ingredients ri LEFT JOIN recipes r ON r.recipe_id=ri.recipe_id "
        "LEFT JOIN ingredients i ON i.ingredient_id=ri.ingredient_id "
        f"WHERE r.slug IN ({placeholders}) AND (r.recipe_id IS NULL OR ri.ingredient_id IS NULL OR i.ingredient_id IS NULL)",
        tuple(target_slugs),
    )
    invalid_recipe_links = int(cur.fetchone()["n"])
    if invalid_dish_links or invalid_recipe_links:
        issues.append(f"Invalid ingredient foreign keys: dish={invalid_dish_links}, recipe={invalid_recipe_links}")
    return {"rows": rows, "missing": missing, "issues": issues}


def category_counts(cur) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT c.name,c.slug,COUNT(DISTINCT d.dish_id) AS total_dishes "
        "FROM categories c LEFT JOIN dishes d ON d.category_id=c.category_id "
        "GROUP BY c.category_id,c.name,c.slug ORDER BY c.category_id"
    )
    return cur.fetchall()


def print_plan(cur, all_rows: list[dict[str, Any]], pending: list[dict[str, Any]], before: dict[str, int]) -> None:
    ingredient_lookup = find_existing_ingredients(cur)
    names = {normalize(item["name"]) for row in pending for item in row["parsed_ingredients"]}
    new_ingredients = names - set(ingredient_lookup)
    print(f"Món mục tiêu: {len(all_rows)} | Đã có cùng slug/tên: {len(all_rows) - len(pending)} | Sẽ thêm: {len(pending)}")
    print(f"Nguyên liệu hiện có: {before['ingredients']} | Nguyên liệu chuẩn hóa mới dự kiến: {len(new_ingredients)}")
    print(f"Recipe ingredients dự kiến: {sum(len(row['parsed_ingredients']) for row in pending)}")
    print(f"Recipe steps dự kiến: {sum(len(row['steps']) for row in pending)}")
    for slug, expected in EXPECTED_CATEGORY_COUNTS.items():
        actual = sum(row["category"] == slug for row in pending)
        print(f"  {slug}: {actual} món mới (danh sách yêu cầu {expected})")


def apply_seed(cur, categories: dict[str, int], pending: list[dict[str, Any]]) -> tuple[int, int]:
    ingredient_lookup = find_existing_ingredients(cur)
    usage_counts = Counter(normalize(item["name"]) for row in pending for item in row["parsed_ingredients"])
    new_ingredients = 0
    new_dishes = 0
    for row in pending:
        category_id = categories[row["category"]]
        ingredient_ids: dict[str, int] = {}
        for item in row["parsed_ingredients"]:
            ingredient_id, created = ensure_ingredient(cur, ingredient_lookup, item, usage_counts)
            ingredient_ids[normalize(item["name"])] = ingredient_id
            new_ingredients += int(created)

        cur.execute(
            "INSERT INTO dishes(dish_name,slug,thumbnail_url,cook_time_mins,difficulty,category_id) "
            "VALUES(%s,%s,'',%s,%s,%s)",
            (row["name"], row["slug"], row["prep"] + row["cook"], row["difficulty"], category_id),
        )
        dish_id = int(cur.lastrowid)
        cur.execute(
            "INSERT INTO recipes(dish_id,category_id,title,slug,description,image_url,cuisine,servings,prep_time,cook_time,"
            "difficulty,occasion,calories,protein,carbs,fat,fiber,rating,review_count,views,is_featured,is_new,tags_json,source_type,status) "
            "VALUES(%s,%s,%s,%s,%s,'',%s,%s,%s,%s,%s,%s,0,0,0,0,0,0,0,0,0,1,%s,'DB','APPROVED')",
            (
                dish_id, category_id, row["name"], row["slug"], row["description"], row["cuisine"],
                row["servings"], row["prep"], row["cook"], row["difficulty"],
                row["occasion"] or "Bữa cơm gia đình",
                json.dumps(list(row["tags"]), ensure_ascii=False),
            ),
        )
        recipe_id = int(cur.lastrowid)
        durations = step_durations(row["prep"], row["cook"])
        for order, raw_step in enumerate(row["steps"], start=1):
            title, instruction = raw_step.split("|", 1)
            cur.execute(
                "INSERT INTO recipe_steps(recipe_id,step_order,title,instruction,duration_mins,tip_note) "
                "VALUES(%s,%s,%s,%s,%s,NULL)",
                (recipe_id, order, title.strip(), instruction.strip(), durations[order - 1]),
            )
        for item in row["parsed_ingredients"]:
            name = item["name"]
            note = (
                "Nguyên liệu chính, bắt buộc."
                if item["core"]
                else "Nguyên liệu tùy chọn."
                if item["optional"]
                else "Gia vị hoặc nguyên liệu bổ trợ."
            )
            cur.execute(
                "INSERT INTO recipe_ingredients(recipe_id,ingredient_id,ingredient_name,amount,unit,sort_order,note) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (recipe_id, ingredient_ids[normalize(name)], name, item["amount"], item["unit"], item["sort_order"], note),
            )
            if item["core"] or item["optional"]:
                weight = 1.35 if item["core"] and ingredient_category(name) in {"Thịt", "Hải sản", "Đậu", "Ngũ cốc"} else 1.0
                if item["optional"]:
                    weight = 0.35
                cur.execute(
                    "INSERT INTO dish_ingredients(dish_id,ingredient_id,is_required,weight_score) VALUES(%s,%s,%s,%s)",
                    (dish_id, ingredient_ids[normalize(name)], int(item["core"]), weight),
                )
        new_dishes += 1
    return new_dishes, new_ingredients


def run() -> int:
    parser = argparse.ArgumentParser(description="Thêm 100 công thức đầy đủ vào MySQL CookMate.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Chỉ khảo sát và kiểm tra, không ghi dữ liệu (mặc định).")
    mode.add_argument("--apply", action="store_true", help="Sao lưu toàn database, thêm dữ liệu bằng transaction và kiểm tra.")
    args = parser.parse_args()

    validate_collection()
    connection = connect()
    try:
        cur = connection.cursor(dictionary=True)
        before = print_snapshot(cur)
        categories = resolve_categories(cur)
        all_rows, pending = find_plan(cur)
        print_plan(cur, all_rows, pending, before)
        if not args.apply:
            if not pending:
                verification = verify_target(cur, [row["slug"] for row in all_rows])
                if verification["issues"]:
                    raise RuntimeError("Kiểm tra dữ liệu đã có thất bại: " + "; ".join(verification["issues"]))
                print("Kiểm tra 100 công thức hiện có: một recipe/món, số lượng nguyên liệu và bước hợp lệ, khóa ngoại hợp lệ.")
            print("Chế độ dry-run: database chưa bị thay đổi. Dùng --apply để sao lưu và ghi dữ liệu.")
            return 0
        if not pending:
            print("Cả 100 slug mục tiêu đã tồn tại; không có thay đổi nào được ghi.")
            return 0
        if len(pending) != 100:
            collisions = [row["name"] for row in all_rows if row["existing_dish"] is not None]
            raise RuntimeError(
                "Một phần tên/slug mục tiêu đã tồn tại. Không ghi một phần để tránh thiếu 100 món. "
                "Các món trùng: " + ", ".join(collisions)
            )

        backup_path = create_backup()
        print(f"Bản sao lưu toàn database đã tạo: {backup_path}")
        connection.rollback()
        connection.start_transaction()
        new_dishes, new_ingredients = apply_seed(cur, categories, pending)
        target_slugs = [row["slug"] for row in pending]
        verification = verify_target(cur, target_slugs)
        if verification["issues"]:
            raise RuntimeError("Kiểm tra trước commit thất bại: " + "; ".join(verification["issues"]))
        connection.commit()
        print(f"Đã commit: {new_dishes} món, {new_ingredients} nguyên liệu mới.")
        print(f"Recipe ingredients mới: {sum(len(row['parsed_ingredients']) for row in pending)}")
        print(f"Recipe steps mới: {sum(len(row['steps']) for row in pending)}")

        after = table_counts(cur)
        print(f"Tổng dishes: {before['dishes']} -> {after['dishes']}")
        print(f"Tổng recipes: {before['recipes']} -> {after['recipes']}")
        print(f"Tổng ingredients: {before['ingredients']} -> {after['ingredients']}")
        print(f"Tổng recipe_ingredients: {before['recipe_ingredients']} -> {after['recipe_ingredients']}")
        print(f"Tổng recipe_steps: {before['recipe_steps']} -> {after['recipe_steps']}")
        print("Món theo danh mục:")
        for row in category_counts(cur):
            print(f"  {row['slug']}: {row['total_dishes']} ({row['name']})")
        print("Toàn vẹn dữ liệu: 100/100 món có đúng một recipe, đủ nguyên liệu và bước; khóa ngoại hợp lệ.")
        print("Dinh dưỡng: chưa có số liệu đáng tin cậy nên không tự gán ước tính.")
        print("Ảnh: để trống để giao diện dùng ảnh mặc định.")
        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        raise SystemExit(1)
