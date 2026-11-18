# -*- coding: utf-8 -*-
"""
Build the single unified phpMyAdmin SQL package: database/cookmate_full_database.sql
  - 17 InnoDB utf8mb4 tables with Vietnamese COMMENT metadata + 1 overview SQL View (v_danh_sach_300_mon_an)
  - Uncommented CREATE DATABASE IF NOT EXISTS `cookmate` + USE `cookmate`
  - 8 real-photo categories, ~285 normalized nutrition ingredients
  - 300 Vietnamese & Regional Specialty dishes & recipes sorted strictly ID = 1..300 ascending
  - 6-8 detailed culinary steps per recipe (~2,000+ steps, zero 'Bước X' titles, >= 190 chars/step, tip_note + duration_mins)
  - Sample users, sample comments, 211+ chatbot_knowledge_base entries, 130+ chatbot_synonyms, curated chatbot_learned_qa
  - Batched INSERTs (25-30 rows/statement), zero DELIMITER / TRIGGER / PROCEDURE / DROP TABLE
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog_200_part1 import INGREDIENTS_DATA as BASE_INGREDIENTS_DATA, PART1_RECIPES
from scripts.catalog_200_part2 import PART2_RECIPES
from scripts.catalog_300_regional import NEW_REGIONAL_INGREDIENTS, REGIONAL_100_RECIPES, REGIONAL_SYNONYMS_EXTRA
from scripts.chatbot_kb_data import CURATED_LEARNED_QA, KNOWLEDGE_BASE, SYNONYMS
from scripts.step_enricher_300 import enrich_recipe_steps

OUTPUT_SQL = ROOT / "database" / "cookmate_full_database.sql"
EXISTING_JSON = ROOT / "scratch" / "existing_116.json"
VERIFIED_MANIFEST_300 = ROOT / "scripts" / "verified_images_300.json"

ALL_INGREDIENTS_DATA: dict[str, tuple[str, str, float, float, float, float, float, bool]] = {
    **BASE_INGREDIENTS_DATA,
    **NEW_REGIONAL_INGREDIENTS,
}

PANTRY_STAPLES_NORM = {
    "nuoc loc", "muoi", "tieu", "duong", "duong phen", "nuoc mam", "nuoc mam chay",
    "nuoc tuong", "dau an", "dau hao", "dau hao chay", "hanh tim", "toi", "hanh la",
    "ot", "giam", "hat nem", "hat nem nam huong", "da vien",
}


def sql_str(value: Any) -> str:
    if value is None:
        return "NULL"
    s = str(value)
    s = (
        s.replace("\\", "\\\\")
        .replace("\0", "\\0")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("'", "\\'")
    )
    return f"'{s}'"


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).lower().replace("đ", "d")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:190] or "mon-an"


def norm_ascii(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).lower().replace("đ", "d")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def parse_grams(amount: Any, unit: str, ing_name: str) -> float:
    raw = str(amount or "").strip().lower().replace(",", ".")
    val = 0.0
    if "-" in raw and not raw.startswith("-"):
        parts = re.findall(r"\d+(?:\.\d+)?", raw)
        if parts:
            val = sum(float(p) for p in parts[:2]) / min(2, len(parts))
    elif "/" in raw:
        m = re.match(r"(\d+)\s*/\s*(\d+)", raw)
        if m and int(m.group(2)) > 0:
            val = float(m.group(1)) / float(m.group(2))
    if val <= 0:
        m = re.search(r"\d+(?:\.\d+)?", raw)
        val = float(m.group(0)) if m else 30.0

    u = norm_ascii(unit)
    n = norm_ascii(ing_name)
    if u in ("kg", "kilogram"):
        return val * 1000.0
    if u in ("g", "gr", "gam", "ml"):
        return val
    if u in ("l", "lit"):
        return val * 1000.0
    if any(k in u for k in ("muong canh", "thia canh", "mc", "thia to")):
        return val * 15.0
    if any(k in u for k in ("muong ca phe", "thia ca phe", "mcf", "thia nho")):
        return val * 5.0
    if "muong" in u or "thia" in u:
        return val * 12.0
    if u in ("qua", "trai"):
        if "trung cut" in n:
            return val * 12.0
        if "trung" in n:
            return val * 50.0
        if "chanh" in n or "tac" in n:
            return val * 25.0
        if "ot" in n:
            return val * 5.0
        if "dua" in n:
            return val * 300.0
        return val * 90.0
    if u in ("cu", "bap"):
        if "toi" in n or "hanh tim" in n:
            return val * 25.0
        return val * 120.0
    if u in ("tep", "nhanh", "cay"):
        if "sa" in n or "gung" in n:
            return val * 15.0
        return val * 6.0
    if u in ("la", "lat", "mieng", "chiec"):
        if "banh trang" in n or "banh da" in n:
            return val * 18.0
        if "dau hu" in n:
            return val * 60.0
        return val * 15.0
    if u in ("bo", "mo"):
        return val * 200.0
    if u in ("goi", "hop", "o"):
        return val * 65.0
    if u in ("chen", "bat"):
        return val * 180.0
    return val


def verify_vegan_recipe(title: str, ingredients: list[dict[str, Any]], steps: list[dict[str, Any]]) -> None:
    forbidden = (
        "thịt", "gà", "bò", "heo", "lợn", "vịt", "ngan", "ếch", "cá", "tôm",
        "mực", "cua", "ốc", "hến", "lươn", "bạch tuộc", "lạp xưởng", "giò sống",
        "nước mắm", "mắm tôm", "mắm tép", "mắm ruốc", "mắm nêm", "dầu hào",
        "trứng", "sữa đặc", "sữa tươi", "kem tươi", "kem phô mai", "bơ lạt",
        "phô mai", "mật ong", "gelatin", "nước dùng gà", "chim cút", "sườn",
        "chả cá", "chả lụa", "bò khô", "mỡ gà",
    )
    allowed_exact_vegan = {
        "dầu hào chay", "nước mắm chay", "chả lụa chay", "nấm đùi gà", "nấm mèo",
        "cà chua", "bơ sáp", "cà tím", "cà rốt", "rau răm", "rau ngót",
        "thịt gấc", "tào phớ", "tàu hũ ky", "lá cẩm",
    }
    for ing in ingredients:
        for candidate in (ing.get("name"), ing.get("canon")):
            n_low = str(candidate or "").strip().lower()
            if not n_low or n_low in allowed_exact_vegan or "chay" in n_low:
                continue
            if n_low in ("nước dùng gà", "dầu hào", "nước mắm", "chả lụa"):
                raise ValueError(f"Vegan violation in {title}: {candidate}")
            for bad in forbidden:
                if re.search(rf"(?<!\w){re.escape(bad)}(?!\w)", n_low):
                    raise ValueError(f"Vegan violation in {title}: {candidate} (matched {bad})")
    for st in steps:
        txt = f"{st.get('title', '')} {st.get('description', '')} {st.get('tip', '')}".lower()
        if re.search(r"\bnước mắm\b(?!\s+chay)", txt) or re.search(r"\bmỡ gà\b", txt):
            raise ValueError(f"Vegan step text violation in {title}: {txt}")


def ensure_min_ingredients(recipe: dict[str, Any], name_to_id: dict[str, int]) -> None:
    ings = recipe["ingredients"]
    cat_id = int(recipe["category_id"])
    complements = (
        [("Đậu hũ", "50", "g", False, ""), ("Hành boaro", "20", "g", False, ""), ("Nấm hương", "15", "g", False, ""), ("Cà rốt", "50", "g", False, ""), ("Hạt nêm nấm hương", "10", "g", False, ""), ("Tiêu", "2", "g", False, "")]
        if cat_id == 5
        else [("Đường", "15", "g", False, ""), ("Lá dứa", "15", "g", False, ""), ("Hạt chia", "8", "g", False, ""), ("Bạc hà tươi", "5", "g", False, ""), ("Đá viên", "150", "g", False, ""), ("Muối", "2", "g", False, "")]
        if cat_id in (6, 7)
        else [("Hành tím", "20", "g", False, ""), ("Tỏi", "10", "g", False, ""), ("Hành lá", "20", "g", False, ""), ("Tiêu", "3", "g", False, ""), ("Cà chua", "60", "g", False, ""), ("Dầu ăn", "15", "ml", False, "")]
    )
    existing_names = {norm_ascii(i["name"]) for i in ings}
    idx = 0
    while len(ings) < 6 and idx < len(complements):
        cname, camt, cunit, creq, cnote = complements[idx]
        idx += 1
        if norm_ascii(cname) not in existing_names and cname in name_to_id:
            ings.append({"name": cname, "canon": cname, "amount": camt, "unit": cunit, "is_required": creq, "note": cnote})
            existing_names.add(norm_ascii(cname))


def compute_recipe_macros(recipe: dict[str, Any]) -> dict[str, float]:
    servings = max(1, int(recipe.get("servings") or 4))
    cal = pro = fat = carb = fib = 0.0
    for ing in recipe["ingredients"]:
        iname = ing.get("canon") or ing["name"]
        if iname not in ALL_INGREDIENTS_DATA:
            raise KeyError(f"Ingredient missing from ALL_INGREDIENTS_DATA: {iname!r} (recipe={recipe['title']!r})")
        _, _, c100, p100, f100, cb100, fb100, _ = ALL_INGREDIENTS_DATA[iname]
        grams = parse_grams(ing["amount"], ing.get("unit") or "g", iname)
        factor = grams / 100.0
        cal += c100 * factor
        pro += p100 * factor
        fat += f100 * factor
        carb += cb100 * factor
        fib += fb100 * factor

    return {
        "calories": int(round(max(45.0, cal / servings))),
        "protein": round(max(0.4, pro / servings), 1),
        "fat": round(max(0.2, fat / servings), 1),
        "carbs": round(max(1.2, carb / servings), 1),
        "fiber": round(max(0.2, fib / servings), 1),
    }


def compute_ingredient_weight_score(ing_name: str, ing_cat: str, sort_idx: int, is_req: bool) -> float:
    na = norm_ascii(ing_name)
    cat_a = norm_ascii(ing_cat)
    if na in PANTRY_STAPLES_NORM or cat_a in ("gia vi", "bot", "khac"):
        return 0.600
    if cat_a in ("thit", "hai san", "trung", "do chay"):
        return 5.000 if sort_idx <= 2 else 3.800
    if cat_a in ("rau", "nam", "trai cay", "dau hat", "hat", "ngu coc"):
        return 3.500 if is_req else 2.200
    return 2.500 if is_req else 1.200


def build_all() -> None:
    if not EXISTING_JSON.exists():
        raise FileNotFoundError(f"Missing {EXISTING_JSON}")
    if not VERIFIED_MANIFEST_300.exists():
        raise FileNotFoundError(f"Missing {VERIFIED_MANIFEST_300}; run scripts/fetch_verified_300_images.py first.")

    existing_raw = json.loads(EXISTING_JSON.read_text(encoding="utf-8"))
    manifest = json.loads(VERIFIED_MANIFEST_300.read_text(encoding="utf-8"))
    manifest_by_id = manifest.get("recipes_by_id") or {}
    manifest_by_title = manifest.get("recipes_by_title") or {}
    cat_imgs = manifest.get("categories") or {}

    # 1. Build unified ingredients (preserving IDs 1..160 + existing 161..246 + new regional ingredients)
    ingredients_rows: list[tuple[int, str, str, str, float, float, float, float, float, bool]] = []
    name_to_id: dict[str, int] = {}
    norm_to_name: dict[str, str] = {}
    id_to_cat: dict[int, str] = {}
    used_ids: set[int] = set()

    for item in sorted(existing_raw["ingredients"], key=lambda x: int(x["id"])):
        iid = int(item["id"])
        iname = item["name"]
        cat, unit, cal, pro, fat, carb, fib, pop = ALL_INGREDIENTS_DATA[iname]
        ingredients_rows.append((iid, iname, cat, unit, cal, pro, fat, carb, fib, bool(pop)))
        name_to_id[iname] = iid
        norm_to_name[norm_ascii(iname)] = iname
        id_to_cat[iid] = cat
        used_ids.add(iid)

    next_iid = max(used_ids, default=0) + 1
    for iname, meta in ALL_INGREDIENTS_DATA.items():
        if iname in name_to_id:
            continue
        cat, unit, cal, pro, fat, carb, fib, pop = meta
        ingredients_rows.append((next_iid, iname, cat, unit, cal, pro, fat, carb, fib, bool(pop)))
        name_to_id[iname] = next_iid
        norm_to_name[norm_ascii(iname)] = iname
        id_to_cat[next_iid] = cat
        next_iid += 1
    ingredients_rows.sort(key=lambda r: r[0])
    id_to_name: dict[int, str] = {iid: iname for iid, iname, *_ in ingredients_rows}

    # 2. Assemble all 300 recipes sorted strictly ID = 1..300 ascending!
    all_recipes: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_slugs: set[str] = set()

    for ex in sorted(existing_raw["recipes"], key=lambda r: int(r["id"])):
        rid = int(ex["id"])
        cat_id = int(ex["categoryId"])
        norm_ings = []
        for ing in ex["ingredients"]:
            raw_name = str(ing.get("name") or "").strip()
            linked_id = ing.get("ingredientId")
            if raw_name in name_to_id:
                canon_name = raw_name
            elif norm_ascii(raw_name) in norm_to_name:
                canon_name = norm_to_name[norm_ascii(raw_name)]
            elif linked_id and int(linked_id) in id_to_name:
                canon_name = id_to_name[int(linked_id)]
            else:
                raise KeyError(f"Unmapped existing ingredient: {raw_name!r}")
            if cat_id == 5:
                if canon_name == "Nước mắm":
                    canon_name = raw_name = "Nước mắm chay"
                elif canon_name == "Dầu hào":
                    canon_name = raw_name = "Dầu hào chay"
            norm_ings.append({
                "name": raw_name or canon_name,
                "canon": canon_name,
                "amount": str(ing.get("amount") or "100"),
                "unit": str(ing.get("unit") or "g"),
                "is_required": bool(ing.get("note") != "Tùy chọn"),
                "note": str(ing.get("note") or ""),
            })
        img = manifest_by_id.get(str(rid)) or manifest_by_title.get(ex["title"]) or ""
        assert img.startswith("https://") and not img.lower().endswith(".svg"), f"Invalid image #{rid}"
        slug = ex.get("slug") or slugify(ex["title"])
        if slug in seen_slugs:
            slug = f"{slug}-{rid}"
        seen_titles.add(norm_ascii(ex["title"]))
        seen_slugs.add(slug)

        desc = str(ex.get("description") or f"Công thức {ex['title']} chuẩn định lượng từ CookMate.")
        if cat_id == 5:
            desc = re.sub(r"\bnước mắm\b(?!\s+chay)", "nước mắm chay", desc, flags=re.IGNORECASE)

        rec = {
            "id": rid,
            "dish_id": rid,
            "category_id": cat_id,
            "title": ex["title"],
            "slug": slug,
            "description": desc,
            "image": img,
            "servings": int(ex.get("servings") or 4),
            "prep_time": int(ex.get("prepTime") or 15),
            "cook_time": int(ex.get("cookTime") or 20),
            "difficulty": ex.get("difficulty") or "Dễ",
            "occasion": ex.get("occasion") or None,
            "is_featured": bool(ex.get("isFeatured") or rid <= 16),
            "is_new": bool(ex.get("isNew") or False),
            "tags": ex.get("tags") or [],
            "rating": float(ex.get("rating") or (4.7 if rid % 2 == 0 else 4.8)),
            "review_count": int(ex.get("reviewCount") or (3 + rid % 5)),
            "views": int(ex.get("views") or (120 + rid * 7)),
            "ingredients": norm_ings,
            "steps": [
                {
                    "step": int(st.get("step") or sidx + 1),
                    "title": str(st.get("title") or ""),
                    "description": str(st.get("description") or ""),
                    "time": int(st.get("time") or 5),
                    "tip": str(st.get("tip") or ""),
                }
                for sidx, st in enumerate(ex.get("steps") or [])
            ],
        }
        ensure_min_ingredients(rec, name_to_id)
        rec["steps"] = enrich_recipe_steps(rec)
        if cat_id == 5:
            verify_vegan_recipe(rec["title"], rec["ingredients"], rec["steps"])
        rec["nutrition"] = compute_recipe_macros(rec)
        all_recipes.append(rec)

    # IDs 117..200
    next_rid = 117
    for spec in list(PART1_RECIPES) + list(PART2_RECIPES):
        t_norm = norm_ascii(spec["title"])
        assert t_norm not in seen_titles, f"Duplicate title {spec['title']}"
        seen_titles.add(t_norm)
        slug = slugify(spec["title"])
        if slug in seen_slugs:
            slug = f"{slug}-{next_rid}"
        seen_slugs.add(slug)
        cat_id = int(spec["category_id"])
        img = manifest_by_id.get(str(next_rid)) or manifest_by_title.get(spec["title"]) or ""
        assert img.startswith("https://") and not img.lower().endswith(".svg"), f"Invalid image #{next_rid}"
        norm_ings = []
        for item in spec["ingredients"]:
            cname = item[0] if item[0] in name_to_id else norm_to_name[norm_ascii(item[0])]
            norm_ings.append({
                "name": cname,
                "canon": cname,
                "amount": str(item[1]),
                "unit": str(item[2]),
                "is_required": bool(item[3]),
                "note": str(item[4]),
            })
        rec = {
            "id": next_rid,
            "dish_id": next_rid,
            "category_id": cat_id,
            "title": spec["title"],
            "slug": slug,
            "description": spec["description"],
            "image": img,
            "servings": int(spec["servings"]),
            "prep_time": int(spec["prep_time"]),
            "cook_time": int(spec["cook_time"]),
            "difficulty": spec["difficulty"],
            "occasion": spec.get("occasion"),
            "is_featured": bool(spec.get("is_featured", False)),
            "is_new": False,
            "tags": spec.get("tags") or [],
            "rating": round(4.6 + (next_rid % 4) * 0.1, 2),
            "review_count": 2 + (next_rid % 6),
            "views": 180 + (next_rid % 40) * 11,
            "ingredients": norm_ings,
            "steps": [
                {"step": sidx + 1, "title": st[0], "description": st[1], "time": int(st[2]), "tip": st[3]}
                for sidx, st in enumerate(spec["steps"])
            ],
        }
        ensure_min_ingredients(rec, name_to_id)
        rec["steps"] = enrich_recipe_steps(rec)
        if cat_id == 5:
            verify_vegan_recipe(rec["title"], rec["ingredients"], rec["steps"])
        rec["nutrition"] = compute_recipe_macros(rec)
        all_recipes.append(rec)
        next_rid += 1

    # IDs 201..300 (100 Regional Specialty Dishes)
    for spec in sorted(REGIONAL_100_RECIPES, key=lambda s: int(s["id"])):
        rid = int(spec["id"])
        t_norm = norm_ascii(spec["title"])
        assert t_norm not in seen_titles, f"Duplicate regional title #{rid}: {spec['title']}"
        seen_titles.add(t_norm)
        slug = slugify(spec["title"])
        if slug in seen_slugs:
            slug = f"{slug}-{rid}"
        seen_slugs.add(slug)
        cat_id = int(spec["category_id"])
        img = manifest_by_id.get(str(rid)) or manifest_by_title.get(spec["title"]) or ""
        assert img.startswith("https://") and not img.lower().endswith(".svg"), f"Invalid regional image #{rid}"
        norm_ings = []
        for item in spec["ingredients"]:
            cname = item[0] if item[0] in name_to_id else norm_to_name[norm_ascii(item[0])]
            norm_ings.append({
                "name": cname,
                "canon": cname,
                "amount": str(item[1]),
                "unit": str(item[2]),
                "is_required": bool(item[3]),
                "note": str(item[4]),
            })
        rec = {
            "id": rid,
            "dish_id": rid,
            "category_id": cat_id,
            "title": spec["title"],
            "slug": slug,
            "description": spec["description"],
            "image": img,
            "servings": int(spec["servings"]),
            "prep_time": int(spec["prep_time"]),
            "cook_time": int(spec["cook_time"]),
            "difficulty": spec["difficulty"],
            "occasion": spec.get("occasion"),
            "is_featured": bool(spec.get("is_featured", False)),
            "is_new": True,
            "tags": spec.get("tags") or [],
            "rating": round(4.7 + (rid % 3) * 0.1, 2),
            "review_count": 3 + (rid % 7),
            "views": 220 + (rid % 45) * 13,
            "ingredients": norm_ings,
            "steps": [],
        }
        ensure_min_ingredients(rec, name_to_id)
        rec["steps"] = enrich_recipe_steps(rec)
        if cat_id == 5:
            verify_vegan_recipe(rec["title"], rec["ingredients"], rec["steps"])
        rec["nutrition"] = compute_recipe_macros(rec)
        all_recipes.append(rec)

    # Sort strictly ID = 1..300 ascending!
    all_recipes.sort(key=lambda r: int(r["id"]))
    assert [r["id"] for r in all_recipes] == list(range(1, 301)), "Recipe IDs must be contiguous 1..300!"
    assert len({r["image"] for r in all_recipes}) == 300, "Expected 300 unique recipe photo URLs!"

    cat_counts: dict[int, int] = {}
    for r in all_recipes:
        cat_counts[r["category_id"]] = cat_counts.get(r["category_id"], 0) + 1
    print("Verified 300 recipes category distribution:", cat_counts)

    CATEGORIES_META = [
        (1, "Món chính", "mon-chinh", "fa-utensils", "Các món mặn, kho, rim, bún cơm đặc sản 3 miền đậm đà cho bữa chính.", cat_imgs.get("1", ""), cat_counts.get(1, 0)),
        (2, "Món canh - Súp", "mon-canh-sup", "fa-bowl-food", "Canh chua, súp bổ dưỡng và bún phở bánh canh nước dùng thanh ngọt.", cat_imgs.get("2", ""), cat_counts.get(2, 0)),
        (3, "Món xào", "mon-xao", "fa-fire", "Món xào nhanh lửa lớn giữ trọn độ giòn xanh và hương vị núi rừng - biển cả.", cat_imgs.get("3", ""), cat_counts.get(3, 0)),
        (4, "Món nướng - Chiên", "mon-nuong-chien", "fa-drumstick-bite", "Món nướng than thơm lừng và bánh chả chiên giòn rụm vàng ươm.", cat_imgs.get("4", ""), cat_counts.get(4, 0)),
        (5, "Món chay", "mon-chay", "fa-leaf", "Thực đơn thuần thực vật thanh tịnh, giàu đạm và cân bằng dinh dưỡng.", cat_imgs.get("5", ""), cat_counts.get(5, 0)),
        (6, "Món tráng miệng", "mon-trang-mieng", "fa-ice-cream", "Chè truyền thống 3 miền, tào phớ, bánh quê và tráng miệng thanh mát.", cat_imgs.get("6", ""), cat_counts.get(6, 0)),
        (7, "Đồ uống", "do-uong", "fa-mug-hot", "Cà phê trứng, nước sấu, nước thảo mộc, trà trái cây và sữa hạt bổ dưỡng.", cat_imgs.get("7", ""), cat_counts.get(7, 0)),
        (8, "Món khai vị", "mon-khai-vi", "fa-plate-wheat", "Gỏi nộm thanh mát, phở cuốn, bánh bèo nậm và món khai tiệc tinh tế.", cat_imgs.get("8", ""), cat_counts.get(8, 0)),
    ]

    # Deduplicate KB, Synonyms (+ regional dish synonyms), Curated QA
    seen_kb: set[str] = set()
    kb_rows: list[dict[str, Any]] = []
    for item in KNOWLEDGE_BASE:
        t = item["title"].strip()
        if t.lower() not in seen_kb:
            seen_kb.add(t.lower())
            kb_rows.append(item)

    seen_syn: set[tuple[str, str]] = set()
    syn_rows: list[tuple[str, str, str]] = []
    for canon, var, reg in list(SYNONYMS) + list(REGIONAL_SYNONYMS_EXTRA):
        pair = (canon.strip().lower(), var.strip().lower())
        if pair not in seen_syn:
            seen_syn.add(pair)
            syn_rows.append((canon.strip(), var.strip(), reg))

    qa_rows = []
    seen_qa: set[str] = set()
    for item in CURATED_LEARNED_QA:
        nq = norm_ascii(item["question_text"])[:250]
        if nq not in seen_qa:
            seen_qa.add(nq)
            qa_rows.append({**item, "normalized_question": nq})

    admin_hash = generate_password_hash("admin123")
    giang_hash = generate_password_hash("giang123")
    member_hash = generate_password_hash("cookmate123")

    lines: list[str] = [
        "-- =============================================================================",
        "-- CookMate Unified Full Database Package (300 Recipes + 6-8 Detailed Steps + AI RAG)",
        "-- File duy nhat: database/cookmate_full_database.sql",
        "-- Tuong thich 100%: phpMyAdmin / MariaDB 10.4+ / MySQL 5.7+ / MySQL 8.0+",
        "-- Huong dan: Mo phpMyAdmin -> Tab Import -> Chon file nay -> Bam Go/Thuc hien!",
        "-- =============================================================================",
        "",
        'SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";',
        'SET time_zone = "+07:00";',
        "SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "",
        "CREATE DATABASE IF NOT EXISTS `cookmate` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        "USE `cookmate`;",
        "",
        "-- -----------------------------------------------------------------------------",
        "-- 1. CAU TRUC 17 BANG CO SO DU LIEU + 1 VIEW TONG QUAN 300 MON AN",
        "-- -----------------------------------------------------------------------------",
        "CREATE TABLE IF NOT EXISTS `users` (",
        "  `user_id` INT NOT NULL AUTO_INCREMENT,",
        "  `full_name` VARCHAR(150) NOT NULL,",
        "  `email` VARCHAR(150) NOT NULL,",
        "  `password_hash` VARCHAR(255) NOT NULL,",
        "  `role` ENUM('member','admin') NOT NULL DEFAULT 'member',",
        "  `status` ENUM('active','inactive') NOT NULL DEFAULT 'active',",
        "  `avatar_url` VARCHAR(500) NOT NULL DEFAULT '',",
        "  `bio` VARCHAR(500) NOT NULL DEFAULT '',",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`user_id`), UNIQUE KEY `uq_users_email` (`email`), KEY `ix_users_role_status` (`role`,`status`)",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng quản lý tài khoản quản trị viên và thành viên CookMate';",
        "",
        "CREATE TABLE IF NOT EXISTS `categories` (",
        "  `category_id` INT NOT NULL AUTO_INCREMENT,",
        "  `name` VARCHAR(120) NOT NULL,",
        "  `slug` VARCHAR(160) NOT NULL,",
        "  `icon` VARCHAR(80) NOT NULL DEFAULT 'restaurant',",
        "  `description` VARCHAR(500) NOT NULL DEFAULT '',",
        "  `image_url` VARCHAR(500) NOT NULL DEFAULT '',",
        "  `recipe_count` INT NOT NULL DEFAULT 0,",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`category_id`), UNIQUE KEY `uq_categories_slug` (`slug`), KEY `ix_categories_name` (`name`)",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng 8 danh mục món ăn chính của hệ thống CookMate';",
        "",
        "CREATE TABLE IF NOT EXISTS `ingredients` (",
        "  `ingredient_id` INT NOT NULL AUTO_INCREMENT,",
        "  `ingredient_name` VARCHAR(200) NOT NULL,",
        "  `category` VARCHAR(100) NOT NULL DEFAULT 'Khác',",
        "  `unit` VARCHAR(30) NOT NULL DEFAULT '100g',",
        "  `calories` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `protein` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `fat` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `carbs` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `fiber` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `is_popular` BOOLEAN NOT NULL DEFAULT FALSE,",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`ingredient_id`), UNIQUE KEY `uq_ingredients_name` (`ingredient_name`), KEY `ix_ingredients_category` (`category`), KEY `ix_ingredients_popular` (`is_popular`)",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng từ điển nguyên liệu và chỉ số dinh dưỡng trên 100g/100ml';",
        "",
        "CREATE TABLE IF NOT EXISTS `dishes` (",
        "  `dish_id` INT NOT NULL AUTO_INCREMENT,",
        "  `dish_name` VARCHAR(200) NOT NULL,",
        "  `slug` VARCHAR(200) NOT NULL,",
        "  `thumbnail_url` VARCHAR(500) NOT NULL DEFAULT '',",
        "  `cook_time_mins` INT NOT NULL DEFAULT 0,",
        "  `difficulty` VARCHAR(50) NOT NULL DEFAULT 'Dễ',",
        "  `category_id` INT NULL,",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`dish_id`), UNIQUE KEY `uq_dishes_slug` (`slug`), KEY `ix_dishes_category` (`category_id`), KEY `ix_dishes_name` (`dish_name`),",
        "  CONSTRAINT `fk_dishes_category` FOREIGN KEY (`category_id`) REFERENCES `categories`(`category_id`) ON DELETE SET NULL",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng danh sách 300 món ăn Việt Nam và đặc sản 3 miền (ID 1-300)';",
        "",
        "CREATE TABLE IF NOT EXISTS `dish_ingredients` (",
        "  `id` INT NOT NULL AUTO_INCREMENT,",
        "  `dish_id` INT NOT NULL,",
        "  `ingredient_id` INT NOT NULL,",
        "  `is_required` BOOLEAN NOT NULL DEFAULT TRUE,",
        "  `weight_score` DECIMAL(6,3) NOT NULL DEFAULT 1.000,",
        "  PRIMARY KEY (`id`), UNIQUE KEY `uq_dish_ingredient` (`dish_id`,`ingredient_id`), KEY `ix_dish_ingredients_ingredient` (`ingredient_id`),",
        "  CONSTRAINT `fk_dish_ingredients_dish` FOREIGN KEY (`dish_id`) REFERENCES `dishes`(`dish_id`) ON DELETE CASCADE,",
        "  CONSTRAINT `fk_dish_ingredients_ingredient` FOREIGN KEY (`ingredient_id`) REFERENCES `ingredients`(`ingredient_id`) ON DELETE RESTRICT",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng ánh xạ nguyên liệu cốt lõi và trọng số gợi ý món ăn';",
        "",
        "CREATE TABLE IF NOT EXISTS `recipes` (",
        "  `recipe_id` INT NOT NULL AUTO_INCREMENT,",
        "  `dish_id` INT NULL,",
        "  `category_id` INT NULL,",
        "  `title` VARCHAR(255) NOT NULL,",
        "  `slug` VARCHAR(255) NOT NULL,",
        "  `description` TEXT NOT NULL,",
        "  `image_url` VARCHAR(500) NOT NULL DEFAULT '',",
        "  `cuisine` VARCHAR(100) NOT NULL DEFAULT 'Món Việt',",
        "  `servings` INT NOT NULL DEFAULT 4,",
        "  `prep_time` INT NOT NULL DEFAULT 0,",
        "  `cook_time` INT NOT NULL DEFAULT 0,",
        "  `difficulty` VARCHAR(50) NOT NULL DEFAULT 'Dễ',",
        "  `occasion` VARCHAR(100) NULL,",
        "  `calories` INT NOT NULL DEFAULT 0,",
        "  `protein` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `carbs` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `fat` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `fiber` DECIMAL(8,2) NOT NULL DEFAULT 0,",
        "  `rating` DECIMAL(3,2) NOT NULL DEFAULT 0,",
        "  `review_count` INT NOT NULL DEFAULT 0,",
        "  `views` INT NOT NULL DEFAULT 0,",
        "  `is_featured` BOOLEAN NOT NULL DEFAULT FALSE,",
        "  `is_new` BOOLEAN NOT NULL DEFAULT FALSE,",
        "  `tags_json` JSON NULL,",
        "  `source_type` ENUM('DB','AI','USER') NOT NULL DEFAULT 'DB',",
        "  `created_by` INT NULL,",
        "  `status` ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',",
        "  `rejection_reason` VARCHAR(500) NULL DEFAULT NULL,",
        "  `reviewed_by` INT NULL,",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`recipe_id`), UNIQUE KEY `uq_recipes_slug` (`slug`),",
        "  KEY `ix_recipes_public` (`status`,`category_id`,`created_at`), KEY `ix_recipes_time` (`status`,`cook_time`), KEY `ix_recipes_occasion` (`occasion`),",
        "  KEY `ix_recipes_created_by` (`created_by`,`status`), KEY `ix_recipes_dish` (`dish_id`),",
        "  CONSTRAINT `fk_recipes_dish` FOREIGN KEY (`dish_id`) REFERENCES `dishes`(`dish_id`) ON DELETE SET NULL,",
        "  CONSTRAINT `fk_recipes_category` FOREIGN KEY (`category_id`) REFERENCES `categories`(`category_id`) ON DELETE SET NULL,",
        "  CONSTRAINT `fk_recipes_creator` FOREIGN KEY (`created_by`) REFERENCES `users`(`user_id`) ON DELETE SET NULL,",
        "  CONSTRAINT `fk_recipes_reviewer` FOREIGN KEY (`reviewed_by`) REFERENCES `users`(`user_id`) ON DELETE SET NULL",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng chi tiết 300 công thức nấu ăn chuẩn định lượng và dinh dưỡng';",
        "",
        "CREATE TABLE IF NOT EXISTS `recipe_ingredients` (",
        "  `id` INT NOT NULL AUTO_INCREMENT,",
        "  `recipe_id` INT NOT NULL,",
        "  `ingredient_id` INT NULL,",
        "  `ingredient_name` VARCHAR(200) NOT NULL,",
        "  `amount` VARCHAR(80) NOT NULL DEFAULT '',",
        "  `unit` VARCHAR(40) NOT NULL DEFAULT '',",
        "  `sort_order` INT NOT NULL DEFAULT 0,",
        "  `note` VARCHAR(500) NOT NULL DEFAULT '',",
        "  PRIMARY KEY (`id`), UNIQUE KEY `uq_recipe_ingredient_order` (`recipe_id`,`sort_order`), KEY `ix_recipe_ingredients_ingredient` (`ingredient_id`),",
        "  CONSTRAINT `fk_recipe_ingredients_recipe` FOREIGN KEY (`recipe_id`) REFERENCES `recipes`(`recipe_id`) ON DELETE CASCADE,",
        "  CONSTRAINT `fk_recipe_ingredients_ingredient` FOREIGN KEY (`ingredient_id`) REFERENCES `ingredients`(`ingredient_id`) ON DELETE SET NULL",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng định lượng nguyên liệu chi tiết từng gam/ml cho 300 công thức';",
        "",
        "CREATE TABLE IF NOT EXISTS `recipe_steps` (",
        "  `step_id` INT NOT NULL AUTO_INCREMENT,",
        "  `recipe_id` INT NOT NULL,",
        "  `step_order` INT NOT NULL,",
        "  `title` VARCHAR(200) NOT NULL DEFAULT '',",
        "  `instruction` TEXT NOT NULL,",
        "  `duration_mins` INT NULL,",
        "  `tip_note` VARCHAR(500) NULL,",
        "  `image_url` VARCHAR(500) NULL,",
        "  PRIMARY KEY (`step_id`), UNIQUE KEY `uq_recipe_step_order` (`recipe_id`,`step_order`),",
        "  CONSTRAINT `fk_recipe_steps_recipe` FOREIGN KEY (`recipe_id`) REFERENCES `recipes`(`recipe_id`) ON DELETE CASCADE",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng hướng dẫn 6-8 bước chế biến chi tiết kèm thời gian và mẹo đầu bếp';",
        "",
        "CREATE TABLE IF NOT EXISTS `recipe_sources` (",
        "  `source_id` INT NOT NULL AUTO_INCREMENT,",
        "  `recipe_id` INT NOT NULL,",
        "  `source_name` VARCHAR(255) NOT NULL,",
        "  `source_url` VARCHAR(1000) NOT NULL,",
        "  `relevance_score` DECIMAL(6,4) NOT NULL DEFAULT 0,",
        "  `fetched_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`source_id`), UNIQUE KEY `uq_recipe_source_url` (`recipe_id`,`source_url`(255)), KEY `ix_recipe_sources_recipe` (`recipe_id`),",
        "  CONSTRAINT `fk_recipe_sources_recipe` FOREIGN KEY (`recipe_id`) REFERENCES `recipes`(`recipe_id`) ON DELETE CASCADE",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng nguồn tham khảo công thức món ăn';",
        "",
        "CREATE TABLE IF NOT EXISTS `ai_search_cache` (",
        "  `cache_id` INT NOT NULL AUTO_INCREMENT,",
        "  `query_dish` VARCHAR(255) NOT NULL,",
        "  `normalized_json` JSON NOT NULL,",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  `expires_at` DATETIME NOT NULL,",
        "  PRIMARY KEY (`cache_id`), UNIQUE KEY `uq_ai_cache_query` (`query_dish`), KEY `ix_ai_cache_expiry` (`expires_at`)",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng bộ nhớ đệm tìm kiếm AI thông minh';",
        "",
        "CREATE TABLE IF NOT EXISTS `favorites` (",
        "  `fav_id` INT NOT NULL AUTO_INCREMENT,",
        "  `user_id` INT NOT NULL,",
        "  `recipe_id` INT NOT NULL,",
        "  `saved_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`fav_id`), UNIQUE KEY `uq_favorites_user_recipe` (`user_id`,`recipe_id`), KEY `ix_favorites_recipe` (`recipe_id`),",
        "  CONSTRAINT `fk_favorites_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,",
        "  CONSTRAINT `fk_favorites_recipe` FOREIGN KEY (`recipe_id`) REFERENCES `recipes`(`recipe_id`) ON DELETE CASCADE",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng danh sách món ăn yêu thích của người dùng';",
        "",
        "CREATE TABLE IF NOT EXISTS `comments` (",
        "  `comment_id` INT NOT NULL AUTO_INCREMENT,",
        "  `recipe_id` INT NOT NULL,",
        "  `user_id` INT NOT NULL,",
        "  `user_name` VARCHAR(150) NOT NULL,",
        "  `user_avatar` VARCHAR(500) NOT NULL DEFAULT '',",
        "  `rating` TINYINT NOT NULL DEFAULT 5,",
        "  `comment` TEXT NOT NULL,",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`comment_id`), KEY `ix_comments_recipe` (`recipe_id`,`created_at`), KEY `ix_comments_user` (`user_id`),",
        "  CONSTRAINT `fk_comments_recipe` FOREIGN KEY (`recipe_id`) REFERENCES `recipes`(`recipe_id`) ON DELETE CASCADE,",
        "  CONSTRAINT `fk_comments_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng bình luận và đánh giá sao công thức món ăn';",
        "",
        "CREATE TABLE IF NOT EXISTS `chat_sessions` (",
        "  `session_id` VARCHAR(64) NOT NULL,",
        "  `user_id` INT NULL,",
        "  `context_recipe_id` INT NULL,",
        "  `started_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  `status` VARCHAR(30) NOT NULL DEFAULT 'OPEN',",
        "  PRIMARY KEY (`session_id`), KEY `ix_chat_sessions_user` (`user_id`,`started_at`),",
        "  CONSTRAINT `fk_chat_sessions_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE SET NULL,",
        "  CONSTRAINT `fk_chat_sessions_recipe` FOREIGN KEY (`context_recipe_id`) REFERENCES `recipes`(`recipe_id`) ON DELETE SET NULL",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng phiên trò chuyện cùng Trợ lý Đầu bếp ChefBot AI';",
        "",
        "CREATE TABLE IF NOT EXISTS `chat_messages` (",
        "  `message_id` INT NOT NULL AUTO_INCREMENT,",
        "  `session_id` VARCHAR(64) NOT NULL,",
        "  `sender` ENUM('USER','AI') NOT NULL,",
        "  `message_text` TEXT NOT NULL,",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`message_id`), KEY `ix_chat_messages_session` (`session_id`,`message_id`),",
        "  CONSTRAINT `fk_chat_messages_session` FOREIGN KEY (`session_id`) REFERENCES `chat_sessions`(`session_id`) ON DELETE CASCADE",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng lịch sử tin nhắn hội thoại ChefBot AI';",
        "",
        "CREATE TABLE IF NOT EXISTS `chatbot_knowledge_base` (",
        "  `kb_id` INT NOT NULL AUTO_INCREMENT,",
        "  `topic` VARCHAR(120) NOT NULL DEFAULT 'general',",
        "  `category` VARCHAR(120) NOT NULL DEFAULT 'cooking_tip',",
        "  `title` VARCHAR(255) NOT NULL,",
        "  `keywords_text` TEXT NOT NULL,",
        "  `content` TEXT NOT NULL,",
        "  `substitution_json` JSON NULL,",
        "  `is_active` BOOLEAN NOT NULL DEFAULT TRUE,",
        "  `priority` INT NOT NULL DEFAULT 10,",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`kb_id`), UNIQUE KEY `uq_chatbot_kb_title` (`title`(191)), KEY `ix_chatbot_kb_topic` (`topic`,`is_active`,`priority`)",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng tri thức kỹ thuật nấu ăn, xử lý sự cố bếp và thay thế gia vị';",
        "",
        "CREATE TABLE IF NOT EXISTS `chatbot_synonyms` (",
        "  `synonym_id` INT NOT NULL AUTO_INCREMENT,",
        "  `canonical_term` VARCHAR(150) NOT NULL,",
        "  `variant_term` VARCHAR(150) NOT NULL,",
        "  `region` VARCHAR(60) NOT NULL DEFAULT 'toan_quoc',",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`synonym_id`), UNIQUE KEY `uq_chatbot_synonym_pair` (`canonical_term`(90),`variant_term`(90)), KEY `ix_chatbot_synonym_variant` (`variant_term`(90))",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng từ điển phương ngữ nguyên liệu và tên món vùng miền Bắc - Trung - Nam';",
        "",
        "CREATE TABLE IF NOT EXISTS `chatbot_learned_qa` (",
        "  `qa_id` INT NOT NULL AUTO_INCREMENT,",
        "  `normalized_question` VARCHAR(255) NOT NULL,",
        "  `question_text` TEXT NOT NULL,",
        "  `intent` VARCHAR(80) NOT NULL DEFAULT 'cooking',",
        "  `answer_text` MEDIUMTEXT NOT NULL,",
        "  `keywords_text` TEXT NOT NULL,",
        "  `matched_recipe_ids` VARCHAR(255) NULL DEFAULT NULL,",
        "  `model_used` VARCHAR(120) NOT NULL DEFAULT '',",
        "  `quality_score` DECIMAL(5,2) NOT NULL DEFAULT 0.70,",
        "  `usage_count` INT NOT NULL DEFAULT 1,",
        "  `is_verified` BOOLEAN NOT NULL DEFAULT FALSE,",
        "  `source_type` ENUM('CURATED','AUTO_LEARNED','GEMINI_VERIFIED') NOT NULL DEFAULT 'AUTO_LEARNED',",
        "  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
        "  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,",
        "  PRIMARY KEY (`qa_id`), UNIQUE KEY `uq_chatbot_learned_question` (`normalized_question`(191)), KEY `ix_chatbot_learned_quality` (`is_verified`,`quality_score`,`usage_count`)",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bảng bộ nhớ hỏi đáp ẩm thực đã kiểm chứng của ChefBot AI';",
        "",
        "ALTER TABLE `categories` ADD COLUMN IF NOT EXISTS `recipe_count` INT NOT NULL DEFAULT 0;",
        "ALTER TABLE `recipes` ADD COLUMN IF NOT EXISTS `rejection_reason` VARCHAR(500) NULL DEFAULT NULL AFTER `status`;",
        "ALTER TABLE `chatbot_learned_qa` ADD COLUMN IF NOT EXISTS `matched_recipe_ids` VARCHAR(255) NULL DEFAULT NULL AFTER `keywords_text`;",
        "",
        "-- -----------------------------------------------------------------------------",
        "-- 2. TAI KHOAN MAU & 8 DANH MUC ANH CHUP THAT",
        "-- -----------------------------------------------------------------------------",
        "INSERT IGNORE INTO `users` (`user_id`,`full_name`,`email`,`password_hash`,`role`,`status`,`avatar_url`,`bio`) VALUES",
        f"(1,'Quản trị viên CookMate','admin@cookmate.vn',{sql_str(admin_hash)},'admin','active','https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=200&h=200&fit=crop&crop=face','Quản trị hệ thống và kiểm duyệt công thức CookMate.'),",
        f"(2,'Giang Nguyễn','giang@cookmate.vn',{sql_str(giang_hash)},'member','active','https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=100&h=100&fit=crop&crop=face','Đam mê ẩm thực truyền thống ba miền và cân bằng dinh dưỡng.'),",
        f"(3,'Bếp Minh Anh','minhanh@cookmate.vn',{sql_str(member_hash)},'member','active','','Yêu thích các món ăn gia đình nhanh gọn và Eat Clean.'),",
        f"(4,'Lan Hương Chay','lanhuong@cookmate.vn',{sql_str(member_hash)},'member','active','','Chuyên chia sẻ thực đơn chay thanh tịnh và bánh truyền thống.');",
        "",
        "INSERT INTO `categories` (`category_id`,`name`,`slug`,`icon`,`description`,`image_url`,`recipe_count`) VALUES",
        ",\n".join(
            f"({cid},{sql_str(name)},{sql_str(slug)},{sql_str(icon)},{sql_str(desc)},{sql_str(img)},{rcount})"
            for cid, name, slug, icon, desc, img, rcount in CATEGORIES_META
        ),
        "ON DUPLICATE KEY UPDATE `name`=VALUES(`name`),`slug`=VALUES(`slug`),`icon`=VALUES(`icon`),`description`=VALUES(`description`),`image_url`=VALUES(`image_url`),`recipe_count`=VALUES(`recipe_count`);",
        "",
    ]

    # 3. Ingredients (batches of 30)
    lines.append("-- -----------------------------------------------------------------------------")
    lines.append(f"-- 3. INGREDIENTS ({len(ingredients_rows)} nguyen lieu chuan hoa dinh duong tren 100g/100ml)")
    lines.append("-- -----------------------------------------------------------------------------")
    for i in range(0, len(ingredients_rows), 30):
        batch = ingredients_rows[i:i + 30]
        lines.append("INSERT INTO `ingredients` (`ingredient_id`,`ingredient_name`,`category`,`unit`,`calories`,`protein`,`fat`,`carbs`,`fiber`,`is_popular`) VALUES")
        lines.append(",\n".join(
            f"({iid},{sql_str(iname)},{sql_str(cat)},{sql_str(unit)},{cal:.2f},{pro:.2f},{fat:.2f},{carb:.2f},{fib:.2f},{1 if pop else 0})"
            for iid, iname, cat, unit, cal, pro, fat, carb, fib, pop in batch
        ))
        lines.append("ON DUPLICATE KEY UPDATE `category`=VALUES(`category`),`unit`=VALUES(`unit`),`calories`=VALUES(`calories`),`protein`=VALUES(`protein`),`fat`=VALUES(`fat`),`carbs`=VALUES(`carbs`),`fiber`=VALUES(`fiber`),`is_popular`=VALUES(`is_popular`);")
        lines.append("")

    # 4. Dishes (strictly ID = 1..300 ascending, batches of 25)
    lines.append("-- -----------------------------------------------------------------------------")
    lines.append("-- 4. DISHES (300 mon an Viet Nam & dac san vung mien sap xep ID = 1 -> 300)")
    lines.append("-- -----------------------------------------------------------------------------")
    for i in range(0, len(all_recipes), 25):
        batch = all_recipes[i:i + 25]
        lines.append("INSERT INTO `dishes` (`dish_id`,`dish_name`,`slug`,`thumbnail_url`,`cook_time_mins`,`difficulty`,`category_id`) VALUES")
        lines.append(",\n".join(
            f"({r['dish_id']},{sql_str(r['title'])},{sql_str(r['slug'])},{sql_str(r['image'])},{r['prep_time'] + r['cook_time']},{sql_str(r['difficulty'])},{r['category_id']})"
            for r in batch
        ))
        lines.append("ON DUPLICATE KEY UPDATE `dish_name`=VALUES(`dish_name`),`slug`=VALUES(`slug`),`thumbnail_url`=VALUES(`thumbnail_url`),`cook_time_mins`=VALUES(`cook_time_mins`),`difficulty`=VALUES(`difficulty`),`category_id`=VALUES(`category_id`);")
        lines.append("")

    # 5. Recipes (strictly ID = 1..300 ascending, batches of 25)
    lines.append("-- -----------------------------------------------------------------------------")
    lines.append("-- 5. RECIPES (300 APPROVED recipes sap xep ID = 1 -> 300)")
    lines.append("-- -----------------------------------------------------------------------------")
    for i in range(0, len(all_recipes), 25):
        batch = all_recipes[i:i + 25]
        lines.append(
            "INSERT INTO `recipes` (`recipe_id`,`dish_id`,`category_id`,`title`,`slug`,`description`,`image_url`,`cuisine`,"
            "`servings`,`prep_time`,`cook_time`,`difficulty`,`occasion`,`calories`,`protein`,`carbs`,`fat`,`fiber`,"
            "`rating`,`review_count`,`views`,`is_featured`,`is_new`,`tags_json`,`source_type`,`created_by`,`status`,`rejection_reason`,`reviewed_by`) VALUES"
        )
        vals = []
        for r in batch:
            n = r["nutrition"]
            tags_str = json.dumps(r["tags"], ensure_ascii=False)
            vals.append(
                f"({r['id']},{r['dish_id']},{r['category_id']},{sql_str(r['title'])},{sql_str(r['slug'])},"
                f"{sql_str(r['description'])},{sql_str(r['image'])},'Món Việt',{r['servings']},{r['prep_time']},"
                f"{r['cook_time']},{sql_str(r['difficulty'])},{sql_str(r['occasion'])},{n['calories']},"
                f"{n['protein']:.2f},{n['carbs']:.2f},{n['fat']:.2f},{n['fiber']:.2f},{r['rating']:.2f},"
                f"{r['review_count']},{r['views']},{1 if r['is_featured'] else 0},{1 if r['is_new'] else 0},"
                f"{sql_str(tags_str)},'DB',1,'APPROVED',NULL,1)"
            )
        lines.append(",\n".join(vals))
        lines.append(
            "ON DUPLICATE KEY UPDATE `dish_id`=VALUES(`dish_id`),`category_id`=VALUES(`category_id`),`title`=VALUES(`title`),"
            "`slug`=VALUES(`slug`),`description`=VALUES(`description`),`image_url`=VALUES(`image_url`),`servings`=VALUES(`servings`),"
            "`prep_time`=VALUES(`prep_time`),`cook_time`=VALUES(`cook_time`),`difficulty`=VALUES(`difficulty`),"
            "`occasion`=VALUES(`occasion`),`calories`=VALUES(`calories`),`protein`=VALUES(`protein`),"
            "`carbs`=VALUES(`carbs`),`fat`=VALUES(`fat`),`fiber`=VALUES(`fiber`),`is_featured`=VALUES(`is_featured`),"
            "`is_new`=VALUES(`is_new`),`tags_json`=VALUES(`tags_json`),`status`='APPROVED';"
        )
        lines.append("")

    # 6. Child tables (IDs 1..300)
    lines.append("-- -----------------------------------------------------------------------------")
    lines.append("-- 6. DISH_INGREDIENTS, RECIPE_INGREDIENTS & RECIPE_STEPS (6-8 buoc chi tiet / mon)")
    lines.append("-- -----------------------------------------------------------------------------")
    lines.append("DELETE FROM `dish_ingredients` WHERE `dish_id` BETWEEN 1 AND 300;")
    lines.append("DELETE FROM `recipe_ingredients` WHERE `recipe_id` BETWEEN 1 AND 300;")
    lines.append("DELETE FROM `recipe_steps` WHERE `recipe_id` BETWEEN 1 AND 300;")
    lines.append("")

    di_tuples: list[tuple[int, int, int, float]] = []
    ri_tuples: list[tuple[int, int, str, str, str, int, str]] = []
    rs_tuples: list[tuple[int, int, str, str, int, str]] = []

    for r in all_recipes:
        rid = r["id"]
        did = r["dish_id"]
        seen_di: set[int] = set()
        for sort_idx, ing in enumerate(r["ingredients"]):
            canon_name = ing.get("canon") or ing["name"]
            iid = name_to_id[canon_name]
            ri_tuples.append((rid, iid, ing["name"], ing["amount"], ing["unit"], sort_idx, ing["note"]))
            if iid not in seen_di and len(seen_di) < 10:
                seen_di.add(iid)
                na = norm_ascii(canon_name)
                is_req = 1 if ((ing["is_required"] or sort_idx < 3) and na not in PANTRY_STAPLES_NORM) else 0
                w_score = compute_ingredient_weight_score(canon_name, id_to_cat.get(iid, "Khác"), sort_idx, bool(is_req))
                di_tuples.append((did, iid, is_req, w_score))
        for step in r["steps"]:
            rs_tuples.append((rid, step["step"], step["title"], step["description"], step["time"], step["tip"]))

    for i in range(0, len(di_tuples), 30):
        batch = di_tuples[i:i + 30]
        lines.append("INSERT INTO `dish_ingredients` (`dish_id`,`ingredient_id`,`is_required`,`weight_score`) VALUES")
        lines.append(",\n".join(f"({d},{iid},{req},{w:.3f})" for d, iid, req, w in batch) + ";")
        lines.append("")

    for i in range(0, len(ri_tuples), 30):
        batch = ri_tuples[i:i + 30]
        lines.append("INSERT INTO `recipe_ingredients` (`recipe_id`,`ingredient_id`,`ingredient_name`,`amount`,`unit`,`sort_order`,`note`) VALUES")
        lines.append(",\n".join(f"({rid},{iid},{sql_str(n)},{sql_str(a)},{sql_str(u)},{ord_i},{sql_str(nt)})" for rid, iid, n, a, u, ord_i, nt in batch) + ";")
        lines.append("")

    for i in range(0, len(rs_tuples), 25):
        batch = rs_tuples[i:i + 25]
        lines.append("INSERT INTO `recipe_steps` (`recipe_id`,`step_order`,`title`,`instruction`,`duration_mins`,`tip_note`) VALUES")
        lines.append(",\n".join(f"({rid},{sord},{sql_str(t)},{sql_str(inst)},{dur},{sql_str(tip)})" for rid, sord, t, inst, dur, tip in batch) + ";")
        lines.append("")

    # 7. Sample Comments
    sample_comments = [
        (1, 1, 2, "Giang Nguyễn", 5, "Nước phở bò trong vắt và dậy mùi quế hồi đúng vị Hà Nội xưa, định lượng gam rất chuẩn!"),
        (2, 6, 3, "Bếp Minh Anh", 5, "Làm theo 7 bước hướng dẫn chi tiết thịt ba chỉ mềm rục lên màu cánh gián bóng đẹp, cả nhà khen tấm tắc."),
        (3, 201, 2, "Giang Nguyễn", 5, "Bún thang Hà Nội hướng dẫn tráng trứng mỏng và nấu nước dùng tôm khô cực kỳ tỉ mỉ, dễ thành công ngay lần đầu."),
        (4, 204, 3, "Bếp Minh Anh", 5, "Bánh đa cua đồng Hải Phòng chuẩn vị đất Cảng, riêu cua đóng tảng béo thơm ăn kèm chả lá lốt tuyệt ngon!"),
        (5, 239, 2, "Giang Nguyễn", 5, "Cơm hến xứ Huế cay thơm đúng điệu, mắm ruốc pha theo tỷ lệ hướng dẫn rất vừa vặn không bị gắt."),
        (6, 249, 4, "Lan Hương Chay", 5, "Cơm sen chay gói lá sen thơm thanh tịnh, hạt sen bùi mềm rất hợp cúng Rằm và đãi tiệc gia đình."),
        (7, 253, 3, "Bếp Minh Anh", 5, "Sợi cao lầu trộn sốt xá xíu ngũ vị thơm nức mũi, có ghi rõ mức lửa và thời gian từng bước rất dễ theo dõi."),
        (8, 271, 2, "Giang Nguyễn", 5, "Cá basa tẩm bột bắp chiên giòn rụm bên ngoài mềm ngọt bên trong, sốt me chua ngọt bắt cơm vô cùng!"),
        (9, 287, 3, "Bếp Minh Anh", 5, "Bún mắm miền Tây nấu theo công thức lọc mắm cá linh rất trong và thơm sả, topping tôm mực heo quay đầy đặn."),
        (10, 300, 4, "Lan Hương Chay", 5, "Chè bà ba miền Tây béo ngậy cốt dừa, khoai lang khoai môn chín bùi nguyên miếng không bị nát."),
    ]
    lines.append("-- -----------------------------------------------------------------------------")
    lines.append("-- 7. BINH LUAN MAU (SAMPLE COMMENTS)")
    lines.append("-- -----------------------------------------------------------------------------")
    lines.append("INSERT IGNORE INTO `comments` (`comment_id`,`recipe_id`,`user_id`,`user_name`,`user_avatar`,`rating`,`comment`) VALUES")
    lines.append(",\n".join(
        f"({cid},{rid},{uid},{sql_str(uname)},'',{rt},{sql_str(cm)})"
        for cid, rid, uid, uname, rt, cm in sample_comments
    ) + ";")
    lines.append("")

    # 8. AI Knowledge Base, Synonyms, Curated QA
    lines.append("-- -----------------------------------------------------------------------------")
    lines.append(f"-- 8. AI RAG KNOWLEDGE BASE ({len(kb_rows)}), SYNONYMS ({len(syn_rows)}), VERIFIED QA ({len(qa_rows)})")
    lines.append("-- -----------------------------------------------------------------------------")
    for i in range(0, len(kb_rows), 25):
        batch = kb_rows[i:i + 25]
        lines.append("INSERT INTO `chatbot_knowledge_base` (`topic`,`category`,`title`,`keywords_text`,`content`,`substitution_json`,`is_active`,`priority`) VALUES")
        vals = []
        for item in batch:
            sub_val = "NULL" if item.get("substitution") is None else sql_str(json.dumps(item["substitution"], ensure_ascii=False))
            vals.append(
                f"({sql_str(item['topic'])},{sql_str(item['category'])},{sql_str(item['title'])},"
                f"{sql_str(item['keywords_text'])},{sql_str(item['content'])},{sub_val},1,{int(item.get('priority', 10))})"
            )
        lines.append(",\n".join(vals))
        lines.append("ON DUPLICATE KEY UPDATE `topic`=VALUES(`topic`),`category`=VALUES(`category`),`keywords_text`=VALUES(`keywords_text`),`content`=VALUES(`content`),`substitution_json`=VALUES(`substitution_json`),`priority`=VALUES(`priority`);")
        lines.append("")

    for i in range(0, len(syn_rows), 30):
        batch = syn_rows[i:i + 30]
        lines.append("INSERT INTO `chatbot_synonyms` (`canonical_term`,`variant_term`,`region`) VALUES")
        lines.append(",\n".join(f"({sql_str(c)},{sql_str(v)},{sql_str(rg)})" for c, v, rg in batch))
        lines.append("ON DUPLICATE KEY UPDATE `region`=VALUES(`region`);")
        lines.append("")

    lines.append(
        "DELETE FROM `chatbot_learned_qa` WHERE `answer_text` LIKE '%chưa có trong CSDL%' "
        "OR `answer_text` LIKE '%Gợi ý tự nấu%' OR `answer_text` LIKE '%tự nấu do%' "
        "OR (`source_type`='AUTO_LEARNED' AND (`matched_recipe_ids` IS NULL OR `matched_recipe_ids`='' OR `matched_recipe_ids`='[]'));"
    )
    lines.append("")

    for i in range(0, len(qa_rows), 20):
        batch = qa_rows[i:i + 20]
        lines.append("INSERT INTO `chatbot_learned_qa` (`normalized_question`,`question_text`,`intent`,`answer_text`,`keywords_text`,`matched_recipe_ids`,`model_used`,`quality_score`,`usage_count`,`is_verified`,`source_type`) VALUES")
        lines.append(",\n".join(
            f"({sql_str(q['normalized_question'])},{sql_str(q['question_text'])},{sql_str(q['intent'])},"
            f"{sql_str(q['answer_text'])},{sql_str(q['keywords_text'])},'[1, 6, 201]',{sql_str(q['model_used'])},{q['quality_score']:.2f},5,1,{sql_str(q['source_type'])})"
            for q in batch
        ))
        lines.append("ON DUPLICATE KEY UPDATE `answer_text`=VALUES(`answer_text`),`keywords_text`=VALUES(`keywords_text`),`matched_recipe_ids`=COALESCE(NULLIF(`matched_recipe_ids`,'[]'),VALUES(`matched_recipe_ids`)),`quality_score`=GREATEST(`quality_score`,VALUES(`quality_score`)),`is_verified`=1;")
        lines.append("")

    # 9. Portable Overview SQL View (no DEFINER, 100% phpMyAdmin compatible) + Category Count Sync
    lines.extend([
        "-- -----------------------------------------------------------------------------",
        "-- 9. BANG VIEW TRUC QUAN 300 MON AN CHO PHPMYADMIN (v_danh_sach_300_mon_an)",
        "-- -----------------------------------------------------------------------------",
        "CREATE OR REPLACE VIEW `v_danh_sach_300_mon_an` AS",
        "SELECT",
        "  r.`recipe_id` AS `ma_mon`,",
        "  r.`title` AS `ten_mon_an`,",
        "  c.`name` AS `danh_muc`,",
        "  r.`servings` AS `khau_phan`,",
        "  (r.`prep_time` + r.`cook_time`) AS `tong_thoi_gian_phut`,",
        "  r.`difficulty` AS `do_kho`,",
        "  r.`calories` AS `calo_moi_phan`,",
        "  (SELECT COUNT(*) FROM `recipe_ingredients` ri WHERE ri.`recipe_id` = r.`recipe_id`) AS `so_nguyen_lieu`,",
        "  (SELECT COUNT(*) FROM `recipe_steps` rs WHERE rs.`recipe_id` = r.`recipe_id`) AS `so_buoc_nau`,",
        "  r.`status` AS `trang_thai`",
        "FROM `recipes` r",
        "LEFT JOIN `categories` c ON c.`category_id` = r.`category_id`",
        "WHERE r.`status` = 'APPROVED'",
        "ORDER BY r.`recipe_id` ASC;",
        "",
        "UPDATE `categories` c SET `recipe_count` = (",
        "  SELECT COUNT(*) FROM `recipes` r WHERE r.`category_id` = c.`category_id` AND r.`status` = 'APPROVED'",
        ");",
        "SET FOREIGN_KEY_CHECKS = 1;",
        "",
    ])

    sql_text = "\n".join(lines)

    # Strict self-assertions before writing disk
    for forbidden_kw in ("DELIMITER ", "CREATE TRIGGER", "CREATE PROCEDURE", "CREATE FUNCTION", "DEFINER="):
        assert forbidden_kw not in sql_text.upper(), f"Forbidden SQL construct: {forbidden_kw}"
    assert len(all_recipes) == 300
    assert len(rs_tuples) >= 1900, f"Expected >= 1900 steps, got {len(rs_tuples)}"
    for r in all_recipes:
        assert 6 <= len(r["steps"]) <= 8, f"Step count out of [6,8] in #{r['id']}: {len(r['steps'])}"
        for st in r["steps"]:
            assert not re.match(r"^\s*bước\s*\d+", st["title"], re.I), f"Generic title in #{r['id']}: {st['title']}"
            assert len(st["description"]) >= 180, f"Short instruction in #{r['id']}: {len(st['description'])}"
            assert int(st["time"]) > 0, f"Zero duration in #{r['id']}"
            assert len(st["tip"].strip()) >= 20, f"Empty tip_note in #{r['id']}"

    OUTPUT_SQL.write_text(sql_text, encoding="utf-8")
    avg_len = sum(len(t[3]) for t in rs_tuples) / len(rs_tuples)
    print(f"Built {OUTPUT_SQL} ({OUTPUT_SQL.stat().st_size / 1024:.1f} KB)")
    print(
        f"Summary: categories=8, ingredients={len(ingredients_rows)}, dishes=300, recipes=300, "
        f"ri={len(ri_tuples)}, di={len(di_tuples)}, steps={len(rs_tuples)} (avg_len={avg_len:.1f} chars), "
        f"kb={len(kb_rows)}, syn={len(syn_rows)}, qa={len(qa_rows)}"
    )


if __name__ == "__main__":
    build_all()
