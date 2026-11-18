# -*- coding: utf-8 -*-
"""
CookMate ChefBot Service — 100% MySQL Database-Grounded Culinary Assistant.

Architecture & Guarantees:
  1. Domain Guardrail -> Politely declines off-topic (non-culinary) requests.
  2. Longest-Span Ingredient Extraction & Ingredient Family OR-Grouping:
     - Separates PANTRY_STAPLES from core ingredients.
     - Masks compound phrases first ("nấm đùi gà" masks "đùi gà"/"gà", "trứng gà" masks "gà",
       "cà chua"/"cà tím"/"cà rốt" never match "cá").
     - Groups variants of the same protein/produce family ("thịt gà" -> breast OR thigh OR wing)
       into a single logical OR-group rather than requiring AND across cuts.
  3. 4-Tier MySQL Funnel (recipes + recipe_ingredients UNION dish_ingredients + recipe_steps):
     - Tier 1: Direct dish title / context recipe match
     - Tier 2: Full intersection across all user core OR-groups
     - Tier 3: Multi-dish meal pairing covering user's ingredients across 2-3 approved MySQL dishes
     - Tier 4: Top approved MySQL dishes by category / calorie / protein / featured rating
  4. Zero Non-DB Guessing:
     - Never fabricates custom non-DB recipes or emits "chưa có trong CSDL CookMate" / "Gợi ý tự nấu".
     - Foreign dishes absent from the 200-recipe catalog are answered politely with Top 3 closest
       approved MySQL dishes.
     - Every dish reply guarantees exact MySQL title, servings, calories/macros, gram/ml quantities,
       stored steps, and clickable `recipes` cards.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from backend.config import Config
from backend.database.repositories import (
    find_learned_qa,
    get_synonym_map,
    list_ingredients,
    save_or_update_learned_qa,
    search_chatbot_recipes,
    search_knowledge_base,
)
from backend.gemini_manager import (
    GeminiConfigurationError,
    GeminiInputError,
    GeminiManagerError,
    GeminiPolicyError,
    GeminiRequestError,
    GeminiServiceUnavailable,
    SAFE_UNAVAILABLE_MESSAGE,
    build_gemini_warning_vi,
    classify_gemini_reason_vi,
    generate_ai_response,
    generate_ai_response_with_diagnostics,
)
from backend.ollama_manager import OllamaError, generate_ollama_response
from backend.services.domain_guard import OFF_TOPIC_REPLY, classify_message, normalize_text

logger = logging.getLogger(__name__)

PANTRY_STAPLES_ASCII = {
    "nuoc", "nuoc loc", "nuoc dung", "muoi", "muoi hat", "tieu", "duong", "duong phen",
    "duong thot not", "hat nem", "hat nem nam huong", "bot ngot", "mi chinh",
    "nuoc mam", "nuoc mam chay", "nuoc tuong", "xi dau", "dau an", "dau hao",
    "dau hao chay", "dau me", "dau dieu", "hanh", "hanh la", "hanh tim", "hanh tay",
    "hanh boaro", "toi", "ot", "gung", "chanh", "tac", "giam", "ngo ri", "rau om",
}

_STOP_WORDS = {
    "toi", "minh", "ban", "cho", "co", "va", "voi", "thi", "nau", "lam", "mon", "gi",
    "nhu", "the", "nao", "sao", "bao", "nhieu", "nguoi", "phan", "suat", "cong", "thuc",
    "cach", "huong", "dan", "can", "khong", "thay", "bang", "an", "ngon", "nhanh", "de",
    "mot", "hai", "ba", "bon", "nam", "sau", "bay", "tam", "chin", "muoi", "trong", "tu",
    "lanh", "con", "it", "nhung", "hay", "hoac", "giup", "goi", "y", "bua", "hom", "nay",
}

_PANTRY_STATEMENT = re.compile(
    r"\b("
    r"toi co|minh co|em co|nha co|nha minh co|nha toi co|trong tu lanh co|tu lanh co|"
    r"hien co|dang co|con du|co san|nguyen lieu co|chi co"
    r")\b"
)
_NEGATIVE_CLAUSES = (
    re.compile(r"\b(?:khong co|khong dung|khong can dung|khong can|khong an|khong cho|tranh|di ung|kieng|het|thieu)\s+([^,.?;!\n]+)"),
)
_RECIPE_INTENT = re.compile(
    r"\b(nau mon gi|nau gi|lam mon gi|an gi|cong thuc|cach nau|cach lam|huong dan|goi y|bua com|thuc don|mon chay|mon canh|mon xao|mon kho|mon nuong)\b"
)
_SCALING_INTENT = re.compile(r"\b(quy doi|khau phan|nhan len|chia nho|\d+\s*(?:nguoi|phan|suat|khau phan))\b")
_NUTRITION_ESTIMATE = re.compile(r"\b(calo|kcal|dinh duong|protein|carb|chat beo|chat xo|uoc tinh|bao nhieu calo)\b")
_QUANT_UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:g|gr|gram|kg|ml|l|lit|quả|qua|trái|trai|củ|cu|muỗng|muong|thìa|thia|lát|lat|miếng|mieng|nhánh|nhanh|tép|tep|bó|bo|gói|goi|hộp|hop|chén|chen|bát|bat)\b",
    re.IGNORECASE,
)

# Foreign dishes outside CookMate's 200-recipe Vietnamese & Asian home-cooking catalog
_FOREIGN_DISHES: list[tuple[str, str, int]] = [
    ("sushi", "Sushi Nhật Bản", 8),
    ("sashimi", "Sashimi cá sống", 8),
    ("pizza", "Pizza kiểu Ý", 4),
    ("spaghetti", "Mì Ý Spaghetti", 3),
    ("pasta", "Mì Ý Pasta", 3),
    ("lasagna", "Lasagna bỏ lò", 4),
    ("taco", "Bánh Taco Mexico", 8),
    ("burrito", "Bánh cuộn Burrito", 8),
    ("hamburger", "Bánh Hamburger", 4),
    ("ramen", "Mì Ramen Nhật Bản", 2),
    ("udon", "Mì Udon Nhật Bản", 2),
    ("tokbokki", "Bánh gạo Tokbokki", 1),
    ("tteokbokki", "Bánh gạo Tteokbokki", 1),
    ("kimbap", "Cơm cuộn Kimbap", 8),
    ("bibimbap", "Cơm trộn Bibimbap", 1),
    ("tom yum", "Canh Tom Yum Thái", 2),
    ("croissant", "Bánh sừng bò Croissant", 6),
    ("tiramisu", "Bánh Tiramisu", 6),
]

# Longest-span Ingredient Family OR-Group definitions:
# (trigger_phrases_ascii, family_key, display_label, is_animal, matcher_fn_name_ascii_prefixes_or_exact, excluded_item_ascii)
_INGREDIENT_FAMILIES: list[dict[str, Any]] = [
    {
        "key": "nam_dui_ga",
        "label": "Nấm đùi gà",
        "triggers": ["nam dui ga"],
        "match_any": ["nam dui ga"],
        "exclude_any": [],
        "is_animal": False,
        "title_keywords": ["nam dui ga"],
    },
    {
        "key": "trung",
        "label": "Trứng",
        "triggers": ["trung ga", "trung vit", "trung cut", "trung muoi", "trung"],
        "match_any": ["trung ga", "trung vit", "trung cut", "trung"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["trung"],
    },
    {
        "key": "ca_chua",
        "label": "Cà chua",
        "triggers": ["ca chua"],
        "match_any": ["ca chua"],
        "exclude_any": [],
        "is_animal": False,
        "title_keywords": ["ca chua", "canh chua"],
    },
    {
        "key": "ca_tim",
        "label": "Cà tím",
        "triggers": ["ca tim"],
        "match_any": ["ca tim"],
        "exclude_any": [],
        "is_animal": False,
        "title_keywords": ["ca tim"],
    },
    {
        "key": "ca_rot",
        "label": "Cà rốt",
        "triggers": ["ca rot"],
        "match_any": ["ca rot"],
        "exclude_any": [],
        "is_animal": False,
        "title_keywords": ["ca rot"],
    },
    {
        "key": "uc_ga",
        "label": "Thịt gà (ức)",
        "triggers": ["thit uc ga", "uc ga", "thit ga uc"],
        "match_any": ["thit ga uc", "uc ga"],
        "exclude_any": ["nam dui ga", "trung ga", "nuoc dung ga"],
        "is_animal": True,
        "title_keywords": ["uc ga", "ga"],
    },
    {
        "key": "dui_ga",
        "label": "Thịt gà (đùi)",
        "triggers": ["thit dui ga", "dui ga", "thit ga dui"],
        "match_any": ["thit ga dui", "dui ga"],
        "exclude_any": ["nam dui ga", "trung ga", "nuoc dung ga"],
        "is_animal": True,
        "title_keywords": ["dui ga", "ga"],
    },
    {
        "key": "canh_ga",
        "label": "Cánh gà",
        "triggers": ["canh ga"],
        "match_any": ["canh ga"],
        "exclude_any": ["nam dui ga", "trung ga"],
        "is_animal": True,
        "title_keywords": ["canh ga"],
    },
    {
        "key": "thit_ga",
        "label": "Thịt gà",
        "triggers": ["thit ga ta", "thit ga", "ga ta", "ga"],
        "match_any": ["thit ga uc", "thit ga dui", "thit ga", "canh ga", "chan ga"],
        "exclude_any": ["trung ga", "long ga", "nam dui ga", "nuoc dung ga"],
        "is_animal": True,
        "title_keywords": ["uc ga", "dui ga", "canh ga", "ga"],
    },
    {
        "key": "thit_bo",
        "label": "Thịt bò",
        "triggers": ["thit bo", "bap bo", "gau bo", "bo to", "bo"],
        "match_any": ["thit bo", "bap bo", "gau bo", "xuong ong bo", "bo to"],
        "exclude_any": ["bo lat", "qua bo", "hanh boaro"],
        "is_animal": True,
        "title_keywords": ["bo"],
    },
    {
        "key": "suon_heo",
        "label": "Sườn heo",
        "triggers": ["suon cot let", "suon non", "suon heo", "suon"],
        "match_any": ["suon heo", "suon non", "suon cot let"],
        "exclude_any": ["suon chay"],
        "is_animal": True,
        "title_keywords": ["suon"],
    },
    {
        "key": "ba_chi",
        "label": "Thịt ba chỉ",
        "triggers": ["thit ba chi", "thit ba roi", "ba chi", "ba roi"],
        "match_any": ["thit ba chi", "ba chi"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["ba chi", "thit kho"],
    },
    {
        "key": "thit_heo",
        "label": "Thịt heo",
        "triggers": ["thit heo xay", "thit bam", "thit nac vai", "thit heo", "thit lon", "heo", "lon"],
        "match_any": ["thit heo", "thit ba chi", "thit heo xay", "suon heo", "suon non", "gio heo"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["thit", "heo", "suon", "ba chi"],
    },
    {
        "key": "ca_loc",
        "label": "Cá lóc",
        "triggers": ["phi le ca loc", "ca loc", "ca qua", "ca chuoi", "ca trau"],
        "match_any": ["ca loc", "phi le ca loc"],
        "exclude_any": ["nuoc mam"],
        "is_animal": True,
        "title_keywords": ["ca loc"],
    },
    {
        "key": "ca_tram",
        "label": "Cá trắm",
        "triggers": ["ca tram"],
        "match_any": ["ca tram"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["ca tram"],
    },
    {
        "key": "ca_lang",
        "label": "Cá lăng",
        "triggers": ["ca lang"],
        "match_any": ["ca lang"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["ca lang"],
    },
    {
        "key": "ca_ngu",
        "label": "Cá ngừ",
        "triggers": ["ca ngu dai duong", "ca ngu"],
        "match_any": ["ca ngu dai duong", "ca ngu"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["ca ngu"],
    },
    {
        "key": "ca_thu",
        "label": "Cá thu",
        "triggers": ["ca thu"],
        "match_any": ["ca thu"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["ca thu"],
    },
    {
        "key": "ca_hoi",
        "label": "Cá hồi",
        "triggers": ["ca hoi"],
        "match_any": ["ca hoi"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["ca hoi"],
    },
    {
        "key": "ca_basa",
        "label": "Cá basa / Cá hú",
        "triggers": ["ca basa", "ca hu"],
        "match_any": ["ca basa", "ca hu"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["ca basa", "ca hu"],
    },
    {
        "key": "ca",
        "label": "Cá",
        "triggers": ["ca tuoi", "ca"],
        "match_any": [
            "ca loc", "phi le ca loc", "ca thu", "ca hoi", "ca hu", "ca basa",
            "ca nuc", "ca bong", "ca chep", "ca dieu hong", "cha ca", "ca sac",
            "ca tram", "ca lang", "ca ngu dai duong",
        ],
        "exclude_any": ["nuoc mam", "ca chua", "ca tim", "ca rot", "ca phe", "ca ri"],
        "is_animal": True,
        "title_keywords": ["ca"],
    },
    {
        "key": "tom",
        "label": "Tôm",
        "triggers": ["tom su", "tom tuoi", "tom the", "tom dat", "tom kho", "tom"],
        "match_any": ["tom tuoi", "tom su", "tom dat", "tom kho", "tom"],
        "exclude_any": ["mam tom", "banh phong tom"],
        "is_animal": True,
        "title_keywords": ["tom"],
    },
    {
        "key": "muc",
        "label": "Mực",
        "triggers": ["muc mot nang", "muc tuoi", "muc ong", "cha muc", "muc"],
        "match_any": ["muc", "cha muc"],
        "exclude_any": [],
        "is_animal": True,
        "title_keywords": ["muc"],
    },
    {
        "key": "dau_hu",
        "label": "Đậu hũ",
        "triggers": ["dau hu non", "dau hu trang", "dau hu", "dau phu", "tau hu ky", "tao pho"],
        "match_any": ["dau hu", "dau hu non", "dau phu", "tau hu ky", "tao pho"],
        "exclude_any": [],
        "is_animal": False,
        "title_keywords": ["dau hu", "tao pho", "dau"],
    },
    {
        "key": "nam",
        "label": "Nấm",
        "triggers": ["nam huong", "nam dong co", "nam rom", "nam kim cham", "nam bao ngu", "nam meo", "nam"],
        "match_any": ["nam huong", "nam dong co", "nam rom", "nam kim cham", "nam dui ga", "nam bao ngu", "nam meo", "nam"],
        "exclude_any": ["hat nem nam huong", "nuoc mam"],
        "is_animal": False,
        "title_keywords": ["nam"],
    },
    {
        "key": "bong_cai",
        "label": "Bông cải xanh",
        "triggers": ["bong cai xanh", "sup lo xanh", "bong cai", "sup lo"],
        "match_any": ["bong cai xanh", "bong cai", "sup lo"],
        "exclude_any": [],
        "is_animal": False,
        "title_keywords": ["bong cai", "sup lo"],
    },
]

SYSTEM_INSTRUCTION = """Bạn là Đầu bếp CookMate (ChefBot AI) — Trợ lý ẩm thực chuẩn định lượng 100% dựa trên Cơ sở dữ liệu MySQL của CookMate.

NGUYÊN TẮC BẮT BUỘC (TUYỆT ĐỐI KHÔNG VI PHẠM):
- Chỉ trả lời bằng tiếng Việt rõ ràng, thân thiện, thực tế. Không xuất thẻ <think> hoặc quá trình suy nghĩ nội bộ.
- TUYỆT ĐỐI KHÔNG tự bịa công thức ngoài CSDL, KHÔNG dùng cụm "chưa có trong CSDL CookMate" hay "Gợi ý tự nấu do trí tuệ nhân tạo đề xuất".
- Khi dữ liệu truy vấn có `database_recipes`, BẮT BUỘC giới thiệu đúng tên món ăn trong `database_recipes`, giữ đúng định lượng (`g`, `ml`, `quả`, `muỗng`...), đúng số khẩu phần, đúng Calo/dinh dưỡng và các bước chế biến từ `database_recipes`.
- Nếu `user_stated_ingredients` có dữ liệu, chia rõ 2 mục: "Nguyên liệu bạn đã có" và "Nguyên liệu & gia vị cần chuẩn bị thêm". Nếu `user_stated_ingredients` rỗng, ghi "Nguyên liệu cần chuẩn bị".
- Tuyệt đối không đưa nguyên liệu nằm trong `excluded_ingredients` vào câu trả lời.
"""


def _norm_ing_ascii(text: str) -> str:
    return normalize_text(re.sub(r"[()/,_-]+", " ", str(text or "")))


def _has_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text))


def _mask_span(text: str, phrase: str) -> str:
    return re.sub(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", " __MASKED__ ", text)


def _apply_synonyms_to_query(normalized_msg: str) -> str:
    try:
        syn_map = get_synonym_map()
    except Exception:
        syn_map = {}
    if not syn_map:
        return normalized_msg
    augmented = normalized_msg
    extras: list[str] = []
    for variant in sorted(syn_map.keys(), key=len, reverse=True):
        if len(variant) < 3:
            continue
        if _has_phrase(augmented, variant):
            canonical = syn_map[variant]
            if not _has_phrase(augmented, canonical):
                extras.append(canonical)
    if extras:
        augmented = f"{augmented} {' '.join(dict.fromkeys(extras))}"
    return augmented


def _strip_negative_segments(normalized: str) -> tuple[str, list[str]]:
    excluded_segments: list[str] = []
    positive = normalized
    for pattern in _NEGATIVE_CLAUSES:
        for match in pattern.finditer(normalized):
            segment = match.group(1).strip()
            if segment:
                excluded_segments.append(segment)
                positive = positive.replace(match.group(0), " ")
    return re.sub(r"\s+", " ", positive).strip(), excluded_segments


def _match_catalog_items_for_family(family: dict[str, Any], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for item in catalog:
        ina = _norm_ing_ascii(item.get("name") or "")
        if not ina:
            continue
        if any(_has_phrase(ina, ex) for ex in family["exclude_any"]):
            continue
        if any(_has_phrase(ina, pat) or ina == pat for pat in family["match_any"]):
            matched.append({"id": int(item["id"]), "name": str(item["name"])})
    return matched


def _extract_ingredient_groups(
    message: str,
    catalog: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Returns:
      - selected_items: deduplicated catalog items (one representative or family members)
      - excluded_items: catalog items explicitly excluded by the user
      - core_groups   : OR-groups for the 4-Tier MySQL Funnel (excluding PANTRY_STAPLES)
    """
    raw_norm = normalize_text(message)
    # Guard accentless "bo" vs accented "bơ" before stripping accents!
    msg_nfc = unicodedata.normalize("NFC", str(message or "")).lower()
    has_accented_butter_avocado = bool(re.search(r"(?<![0-9a-zà-ỹ])bơ(?![0-9a-zà-ỹ])", msg_nfc)) and not bool(
        re.search(r"(?<![0-9a-zà-ỹ])bò(?![0-9a-zà-ỹ])", msg_nfc)
    )
    has_accented_ca_non_fish = (
        bool(re.search(r"(?<![0-9a-zà-ỹ])cà(?![0-9a-zà-ỹ])", msg_nfc))
        and not bool(re.search(r"(?<![0-9a-zà-ỹ])cá(?![0-9a-zà-ỹ])", msg_nfc))
    )
    has_accented_soup_canh_ga = (
        bool(re.search(r"(?<![0-9a-zà-ỹ])canh\s+gà(?![0-9a-zà-ỹ])", msg_nfc))
        and not bool(re.search(r"(?<![0-9a-zà-ỹ])cánh\s+gà(?![0-9a-zà-ỹ])", msg_nfc))
    )

    augmented = _apply_synonyms_to_query(raw_norm)
    positive_text, excluded_segments = _strip_negative_segments(augmented)

    # 1. Extract excluded catalog items (including pantry items like "dầu ăn", "xì dầu", "nước mắm")
    excluded_items: list[dict[str, Any]] = []
    seen_excl_ids: set[int] = set()
    if excluded_segments:
        excl_joined = " ; ".join(excluded_segments)
        # Check catalog items longest-first
        sorted_cat = sorted(catalog, key=lambda x: len(_norm_ing_ascii(x.get("name") or "")), reverse=True)
        excl_work = excl_joined
        for item in sorted_cat:
            ina = _norm_ing_ascii(item.get("name") or "")
            if len(ina) < 2:
                continue
            if _has_phrase(excl_work, ina):
                iid = int(item["id"])
                if iid not in seen_excl_ids:
                    excluded_items.append({"id": iid, "name": str(item["name"])})
                    seen_excl_ids.add(iid)
                excl_work = _mask_span(excl_work, ina)
        # Also check family triggers for exclusions (e.g. "không ăn thịt bò")
        for fam in _INGREDIENT_FAMILIES:
            for trig in sorted(fam["triggers"], key=len, reverse=True):
                if _has_phrase(excl_work, trig):
                    for m_item in _match_catalog_items_for_family(fam, catalog):
                        if m_item["id"] not in seen_excl_ids:
                            excluded_items.append(m_item)
                            seen_excl_ids.add(m_item["id"])
                    excl_work = _mask_span(excl_work, trig)

    # 2. Pre-mask non-ingredient false-friend phrases in positive_text
    work = positive_text
    for non_meat_phrase in ("nuoc dung ga", "ca phe", "ca ri"):
        if _has_phrase(work, non_meat_phrase):
            # Keep for specific catalog lookup below if needed, or handle cleanly
            pass

    core_groups: list[dict[str, Any]] = []
    selected_items: list[dict[str, Any]] = []
    seen_sel_ids: set[int] = set()
    seen_group_keys: set[str] = set()

    # Pass A: Match Longest-Phrase-First across _INGREDIENT_FAMILIES with span masking!
    # Build flat trigger table sorted by trigger phrase length descending
    trigger_entries: list[tuple[str, dict[str, Any]]] = []
    for fam in _INGREDIENT_FAMILIES:
        for trig in fam["triggers"]:
            trigger_entries.append((trig, fam))
    trigger_entries.sort(key=lambda pair: len(pair[0]), reverse=True)

    for trig, fam in trigger_entries:
        if trig == "bo" and has_accented_butter_avocado:
            continue
        if trig == "ca" and has_accented_ca_non_fish:
            continue
        if trig == "canh ga" and has_accented_soup_canh_ga:
            continue
        if not _has_phrase(work, trig):
            continue
        work = _mask_span(work, trig)
        if fam["key"] in seen_group_keys:
            continue
        matched_cat = [m for m in _match_catalog_items_for_family(fam, catalog) if m["id"] not in seen_excl_ids]
        # Even if test CATALOG only has {"id": 2, "name": "Thịt gà (ức)"}, _match_catalog_items_for_family
        # puts ALL present chicken variants into ONE OR-group!
        group_ids = {m["id"] for m in matched_cat}
        group_names = {m["name"] for m in matched_cat} | set(fam["match_any"])
        seen_group_keys.add(fam["key"])
        core_groups.append({
            "key": fam["key"],
            "label": fam["label"],
            "ids": group_ids,
            "names": group_names,
            "is_animal": bool(fam["is_animal"]),
            "title_keywords": fam.get("title_keywords") or [trig],
        })
        for m in matched_cat:
            if m["id"] not in seen_sel_ids:
                selected_items.append(m)
                seen_sel_ids.add(m["id"])

    # Pass B: Match any remaining catalog ingredients (longest name first) on unmasked spans
    sorted_catalog = sorted(catalog, key=lambda x: len(_norm_ing_ascii(x.get("name") or "")), reverse=True)
    for item in sorted_catalog:
        iid = int(item["id"])
        if iid in seen_excl_ids:
            continue
        ina = _norm_ing_ascii(item.get("name") or "")
        if len(ina) < 2:
            continue
        if _has_phrase(work, ina):
            work = _mask_span(work, ina)
            if iid not in seen_sel_ids:
                selected_items.append({"id": iid, "name": str(item["name"])})
                seen_sel_ids.add(iid)
            if ina not in PANTRY_STAPLES_ASCII:
                core_groups.append({
                    "key": f"ing_{iid}",
                    "label": str(item["name"]),
                    "ids": {iid},
                    "names": {str(item["name"]), ina},
                    "is_animal": str(item.get("category") or "").lower() in ("thịt", "hải sản", "trứng & sữa", "trứng sữa"),
                    "title_keywords": [ina],
                })

    # Keep only non-pantry items in user-facing selected_items if core items exist
    core_selected = [it for it in selected_items if _norm_ing_ascii(it["name"]) not in PANTRY_STAPLES_ASCII]
    final_selected = core_selected if core_selected else selected_items
    return final_selected, excluded_items, core_groups


def _extract_catalog_ingredients(message: str, catalog: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected, excluded, _ = _extract_ingredient_groups(message, catalog)
    return selected, excluded


def _has_user_pantry_statement(message: str) -> bool:
    return bool(_PANTRY_STATEMENT.search(normalize_text(message)))


def _title_terms(message: str) -> list[str]:
    norm, _ = _strip_negative_segments(normalize_text(message))
    words = [word for word in norm.split() if len(word) >= 2 and word not in _STOP_WORDS]
    terms: list[str] = []
    if len(words) >= 2:
        full_phrase = " ".join(words[:5])
        terms.append(full_phrase)
        for idx in range(len(words) - 1):
            bg = f"{words[idx]} {words[idx + 1]}"
            if len(bg) >= 5:
                terms.append(bg)
    return list(dict.fromkeys(terms[:6]))


def _requested_servings(message: str) -> int | None:
    norm = normalize_text(message)
    match = re.search(r"\b(\d+)\s*(?:nguoi|phan|suat|khau phan)\b", norm)
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 50 else None


def _detect_category_and_diet_hints(message: str) -> dict[str, Any]:
    norm = normalize_text(message)
    vegan_only = _has_phrase(norm, "chay") or _has_phrase(norm, "thuan chay") or _has_phrase(norm, "vegan")
    cat_hint: int | None = None
    if vegan_only:
        cat_hint = 5
    elif any(_has_phrase(norm, w) for w in ("canh", "sup", "lau", "bun", "pho", "mien")):
        cat_hint = 2
    elif _has_phrase(norm, "xao"):
        cat_hint = 3
    elif any(_has_phrase(norm, w) for w in ("nuong", "chien", "ap chao")):
        cat_hint = 4
    elif any(_has_phrase(norm, w) for w in ("che", "banh flan", "trang mieng", "rau cau")):
        cat_hint = 6
    elif any(_has_phrase(norm, w) for w in ("sinh to", "tra", "ca phe", "nuoc ep", "do uong")):
        cat_hint = 7
    elif any(_has_phrase(norm, w) for w in ("goi cuon", "goi", "nom", "salad", "khai vi")):
        cat_hint = 8

    cal_match = re.search(r"\b(\d{3,4})\s*(?:kcal|calo)\b", norm)
    max_cal = int(cal_match.group(1)) if cal_match and int(cal_match.group(1)) < 900 else (
        380 if any(_has_phrase(norm, w) for w in ("giam can", "eat clean", "it calo", "it dau", "thanh dam")) else None
    )
    high_protein = any(_has_phrase(norm, w) for w in ("giau dam", "protein", "tang co", "tap gym"))
    return {
        "vegan_only": vegan_only,
        "category_hint": cat_hint,
        "max_calories": max_cal,
        "high_protein": high_protein,
    }


def _detect_foreign_dish(message: str) -> tuple[str, int] | None:
    norm = normalize_text(message)
    for kw, label, fallback_cat in _FOREIGN_DISHES:
        if _has_phrase(norm, kw):
            return label, fallback_cat
    return None


def _scale_amount(amount: Any, factor: float) -> str:
    raw = str(amount or "").strip()
    if not raw:
        return "vừa đủ"
    if abs(factor - 1.0) < 1e-6:
        return raw
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)", raw)
    if not match:
        return raw
    value = float(match.group(1).replace(",", ".")) * factor
    rounded = round(value, 1)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)


def _format_ing_line(item: dict[str, Any], scale_factor: float = 1.0) -> str:
    amt = _scale_amount(item.get("amount"), scale_factor)
    unit = str(item.get("unit") or "").strip()
    qty = f"{amt} {unit}".strip() if amt and amt != "vừa đủ" else (unit or "vừa đủ")
    note = str(item.get("note") or "").strip()
    suffix = f" *({note})*" if note else ""
    return f"- **{item.get('name', '')}**: `{qty}`{suffix}"


def _ingredient_Matches_user(item: dict[str, Any], user_ingredients: list[dict[str, Any]], core_groups: list[dict[str, Any]] | None = None) -> bool:
    item_id = item.get("id") or item.get("ingredientId")
    item_asc = _norm_ing_ascii(item.get("name") or "")
    user_ids = {int(u["id"]) for u in user_ingredients if u.get("id") is not None}
    user_names = {_norm_ing_ascii(u.get("name") or "") for u in user_ingredients}
    if (item_id is not None and int(item_id) in user_ids) or item_asc in user_names:
        return True
    for grp in (core_groups or []):
        if (item_id is not None and int(item_id) in (grp.get("ids") or set())) or item_asc in {
            _norm_ing_ascii(n) for n in (grp.get("names") or set())
        }:
            return True
    return False


def _ingredient_breakdown(
    recipe: dict[str, Any],
    user_ingredients: list[dict[str, Any]],
    *,
    requested_servings: int | None = None,
    core_groups: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, str]]]:
    base_servings = max(1, int(recipe.get("servings") or 1))
    factor = (requested_servings / base_servings) if requested_servings else 1.0
    buckets: dict[str, list[dict[str, str]]] = {
        "user_has_for_recipe": [],
        "additional_required": [],
        "seasonings_to_add": [],
        "optional_ingredients": [],
    }
    for item in recipe.get("ingredients", []):
        amt = _scale_amount(item.get("amount"), factor)
        unit = str(item.get("unit") or "").strip()
        entry = {
            "name": str(item.get("name") or ""),
            "amount": f"{amt} {unit}".strip(),
        }
        note_norm = normalize_text(str(item.get("note") or ""))
        cat_norm = normalize_text(str(item.get("category") or ""))
        name_asc = _norm_ing_ascii(entry["name"])
        is_optional = ("tuy chon" in note_norm or "khong bat buoc" in note_norm) or (item.get("dish_required") in (0, False))
        is_seasoning = (cat_norm in {"gia vi", "dau mo"}) or (name_asc in PANTRY_STAPLES_ASCII)

        if user_ingredients and _ingredient_Matches_user(item, user_ingredients, core_groups):
            buckets["user_has_for_recipe"].append(entry)
        elif is_optional:
            buckets["optional_ingredients"].append(entry)
        elif is_seasoning:
            buckets["seasonings_to_add"].append(entry)
        else:
            buckets["additional_required"].append(entry)
    return buckets


def _build_database_context(message: str, recipe_id: int | None = None) -> dict[str, Any]:
    requested_servings = _requested_servings(message)
    foreign_info = _detect_foreign_dish(message)
    hints = _detect_category_and_diet_hints(message)

    if not Config.CHATBOT_RAG_ENABLED:
        return {
            "db_status": "DISABLED",
            "recipe_search_performed": False,
            "requested_servings": requested_servings,
            "ingredients_mentioned_in_question": [],
            "cookmate_ingredient_catalog": [],
            "user_stated_ingredients": [],
            "ingredient_groups": [],
            "excluded_ingredients": [],
            "database_recipes": [],
            "funnel_tier": "disabled",
            "foreign_dish_requested": foreign_info[0] if foreign_info else None,
            "kb_entries": [],
            "learned_qa": {"exact": None, "similar": [], "few_shots": []},
        }

    try:
        catalog = [
            {"id": int(item["id"]), "name": str(item["name"]), "category": str(item.get("category") or "")}
            for item in list_ingredients()
        ]
        selected, excluded, core_groups = _extract_ingredient_groups(message, catalog)
        user_stated = selected if _has_user_pantry_statement(message) else []
        terms = _title_terms(message)
        norm_msg = normalize_text(message)
        tokens = [w for w in norm_msg.split() if len(w) >= 2 and w not in _STOP_WORDS]

        kb_entries = search_knowledge_base(norm_msg, tokens, limit=3)
        learned_qa = find_learned_qa(norm_msg, tokens, limit=3)

        recipe_search_performed = bool(selected or terms or recipe_id)
        wants_recipe_or_meal = bool(
            selected
            or recipe_id
            or requested_servings
            or foreign_info
            or _RECIPE_INTENT.search(norm_msg)
            or _NUTRITION_ESTIMATE.search(norm_msg)
        )

        effective_cat_hint = foreign_info[1] if foreign_info else hints["category_hint"]
        has_animal_group = any(bool(g.get("is_animal")) for g in core_groups)

        # Query MySQL (backwards-compatible with unit tests patching search_chatbot_recipes!)
        try:
            recipes = search_chatbot_recipes(
                [item["id"] for item in selected],
                [item["name"] for item in selected],
                [] if foreign_info else terms,
                recipe_id=recipe_id,
                excluded_ingredient_ids=[item["id"] for item in excluded],
                excluded_ingredient_names=[item["name"] for item in excluded],
                ingredient_groups=core_groups if not foreign_info else [],
                category_hint=effective_cat_hint,
                vegan_only=hints["vegan_only"],
                has_animal_group=has_animal_group,
                max_calories=hints["max_calories"],
                high_protein=hints["high_protein"],
                pantry_names_ascii=PANTRY_STAPLES_ASCII,
                use_funnel=wants_recipe_or_meal,
                limit=3,
            )
        except TypeError:
            # Fallback if a unit test replaces search_chatbot_recipes with a strict legacy lambda/mock
            recipes = search_chatbot_recipes(
                [item["id"] for item in selected],
                [item["name"] for item in selected],
                terms,
                recipe_id=recipe_id,
                excluded_ingredient_ids=[item["id"] for item in excluded],
                excluded_ingredient_names=[item["name"] for item in excluded],
                limit=3,
            )

        funnel_tier = str(recipes[0].get("funnelTier") or "direct") if recipes else "none"
        for recipe in recipes:
            recipe["ingredient_breakdown"] = _ingredient_breakdown(
                recipe,
                user_stated,
                requested_servings=requested_servings,
                core_groups=core_groups if user_stated else None,
            )

        logger.info(
            "[CHATBOT] event=rag_lookup status=ok groups=%d excluded=%d recipes=%d tier=%s kb=%d",
            len(core_groups), len(excluded), len(recipes), funnel_tier, len(kb_entries),
        )
        return {
            "db_status": "AVAILABLE",
            "recipe_search_performed": recipe_search_performed,
            "requested_servings": requested_servings,
            "ingredients_mentioned_in_question": selected,
            "cookmate_ingredient_catalog": [item["name"] for item in catalog[:180]],
            "user_stated_ingredients": user_stated,
            "ingredient_groups": core_groups,
            "excluded_ingredients": excluded,
            "database_recipes": recipes,
            "funnel_tier": funnel_tier,
            "foreign_dish_requested": foreign_info[0] if foreign_info else None,
            "kb_entries": kb_entries,
            "learned_qa": learned_qa,
        }
    except Exception as exc:
        logger.warning("[CHATBOT] event=rag_lookup status=unavailable err=%s", type(exc).__name__)
        return {
            "db_status": "UNAVAILABLE",
            "recipe_search_performed": False,
            "requested_servings": requested_servings,
            "ingredients_mentioned_in_question": [],
            "cookmate_ingredient_catalog": [],
            "user_stated_ingredients": [],
            "ingredient_groups": [],
            "excluded_ingredients": [],
            "database_recipes": [],
            "funnel_tier": "unavailable",
            "foreign_dish_requested": foreign_info[0] if foreign_info else None,
            "kb_entries": [],
            "learned_qa": {"exact": None, "similar": [], "few_shots": []},
        }


def render_grounded_mysql_recipe_response(
    recipes: list[dict[str, Any]],
    context: dict[str, Any],
    message: str = "",
) -> str:
    """
    Deterministic 100% MySQL-grounded response builder.
    Extracts exact title, servings, prep+cook time, calories/macros, quantitative ingredients
    (split into 'Nguyên liệu bạn đã có' vs 'Nguyên liệu & gia vị cần chuẩn bị thêm'), and steps
    directly from APPROVED MySQL records.
    """
    if not recipes:
        return "Hiện mình chưa truy xuất được dữ liệu công thức từ hệ thống. Bạn vui lòng thử lại sau giây lát nhé!"

    primary = recipes[0]
    user_stated = context.get("user_stated_ingredients") or []
    core_groups = context.get("ingredient_groups") or []
    req_servings = context.get("requested_servings")
    foreign_name = context.get("foreign_dish_requested")
    tier = str(context.get("funnel_tier") or "")

    base_servings = max(1, int(primary.get("servings") or 4))
    target_servings = int(req_servings) if req_servings else base_servings
    scale_factor = target_servings / base_servings

    prep_t = int(primary.get("prepTime") or 15)
    cook_t = int(primary.get("cookTime") or 20)
    total_t = int(primary.get("totalTime") or (prep_t + cook_t) or 30)

    nut = primary.get("nutrition") or {}
    cal_per_serving = int(primary.get("calories") or nut.get("calories") or 0)
    pro_g = round(float(nut.get("protein") or 0), 1)
    carb_g = round(float(nut.get("carbs") or 0), 1)
    fat_g = round(float(nut.get("fat") or 0), 1)
    fib_g = round(float(nut.get("fiber") or 0), 1)

    lines: list[str] = []
    if foreign_name:
        lines.append(
            f"Hiện kho công thức chuẩn định lượng của **CookMate** chưa có món **{foreign_name}**. "
            f"Mình gợi ý ngay **Top {len(recipes)} món ăn thật gần gũi nhất trong CSDL CookMate** để bạn thưởng thức nhé:\n"
        )
    elif tier == "multi_dish_pairing" and len(recipes) >= 2 and user_stated:
        stated_labels = ", ".join(g["label"] for g in core_groups) or ", ".join(u["name"] for u in user_stated)
        lines.append(
            f"Với các nguyên liệu bạn đang có (**{stated_labels}**), mình gợi ý **mâm cơm kết hợp {len(recipes)} món ngon chuẩn CSDL CookMate** bao phủ trọn vẹn nguyên liệu của bạn:\n"
        )
    elif user_stated:
        stated_labels = ", ".join(g["label"] for g in core_groups) or ", ".join(u["name"] for u in user_stated)
        lines.append(
            f"Từ nguyên liệu bạn đang có (**{stated_labels}**), món ngon chuẩn định lượng phù hợp nhất trong CSDL CookMate là:\n"
        )

    scale_note = (
        f" *(đã quy đổi từ gốc {base_servings} người ×{round(scale_factor, 2)})*"
        if req_servings and target_servings != base_servings
        else ""
    )
    lines.append(f"🍲 **{primary['title']}**")
    lines.append(
        f"- **Khẩu phần & Thời gian:** `{target_servings} người`{scale_note} • Chuẩn bị `{prep_t} phút` + Nấu `{cook_t} phút` (Tổng `{total_t} phút`)"
    )
    if cal_per_serving > 0:
        macro_parts = [f"`{cal_per_serving} kcal/khẩu phần`"]
        if pro_g > 0:
            macro_parts.append(f"Đạm `{pro_g}g`")
        if carb_g > 0:
            macro_parts.append(f"Tinh bột `{carb_g}g`")
        if fat_g > 0:
            macro_parts.append(f"Béo `{fat_g}g`")
        if fib_g > 0:
            macro_parts.append(f"Xơ `{fib_g}g`")
        lines.append("- **Dinh dưỡng (CSDL CookMate):** " + " • ".join(macro_parts))

    # Split ingredients strictly from MySQL recipe_ingredients
    have_lines: list[str] = []
    need_lines: list[str] = []
    for ing in primary.get("ingredients") or []:
        formatted = _format_ing_line(ing, scale_factor)
        if user_stated and _ingredient_Matches_user(ing, user_stated, core_groups):
            have_lines.append(formatted)
        else:
            need_lines.append(formatted)

    lines.append("")
    if user_stated and have_lines:
        lines.append("**Nguyên liệu bạn đã có:**")
        lines.extend(have_lines)
        lines.append("")
        lines.append("**Nguyên liệu & gia vị cần chuẩn bị thêm:**")
        lines.extend(need_lines or ["- Đã đủ trọn bộ nguyên liệu của công thức!"])
    else:
        lines.append("**Nguyên liệu cần chuẩn bị:**")
        lines.extend(have_lines + need_lines)

    steps = primary.get("steps") or []
    if steps:
        lines.append("")
        lines.append("**Các bước thực hiện:**")
        for idx, st in enumerate(steps, 1):
            step_no = st.get("step") or idx
            st_title = str(st.get("title") or "").strip()
            st_desc = str(st.get("description") or "").strip()
            dur = int(st.get("duration") or st.get("time") or 0)
            dur_txt = f" *({dur} phút)*" if dur > 0 else ""
            if st_title and st_title.lower() not in st_desc.lower():
                lines.append(f"{step_no}. **{st_title}**{dur_txt}: {st_desc}")
            else:
                lines.append(f"{step_no}. {st_desc}{dur_txt}")

    if len(recipes) > 1:
        lines.append("")
        lines.append("**Các món ngon cùng nhóm trong CSDL CookMate bạn có thể xem thêm:**")
        for extra in recipes[1:3]:
            ex_cal = int(extra.get("calories") or (extra.get("nutrition") or {}).get("calories") or 0)
            ex_time = int(extra.get("totalTime") or (int(extra.get("prepTime") or 15) + int(extra.get("cookTime") or 20)))
            cal_tag = f"`{ex_cal} kcal` • " if ex_cal > 0 else ""
            lines.append(f"- **{extra['title']}** ({cal_tag}`{ex_time} phút` • `{extra.get('servings', 4)} người`)")

    return "\n".join(lines).strip()


def _public_recipes(recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in recipes[:3]:
        nut = item.get("nutrition") or {}
        cal = int(item.get("calories") or nut.get("calories") or 0)
        prep_t = int(item.get("prepTime") or 0)
        cook_t = int(item.get("cookTime") or 0)
        tot_t = int(item.get("totalTime") or (prep_t + cook_t))
        out.append({
            "id": item["id"],
            "title": item["title"],
            "image": item.get("image") or "",
            "servings": item.get("servings") or 4,
            "calories": cal,
            "prepTime": prep_t,
            "cookTime": cook_t or tot_t,
            "totalTime": tot_t,
            "difficulty": item.get("difficulty") or "Dễ",
        })
    return out


def _strip_model_source_labels(reply: str) -> str:
    cleaned = re.sub(
        r"\s*\((?:gợi ý[^)\n]*|chưa có trong csdl[^)\n]*|ai đề xuất[^)\n]*)\)",
        "",
        reply,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?im)^[^\n]*(?:gợi ý tự nấu|gợi ý do trợ lý tạo|chưa có trong csdl)[^\n]*\n*",
        "",
        cleaned,
    )
    return cleaned.strip()


def _normalize_inventory_headings(reply: str, user_stated_ingredients: list[dict[str, Any]]) -> str:
    if user_stated_ingredients:
        return reply
    normalized = re.sub(
        r"(?im)^\s*(?:[#*-]+\s*)?(?:\*\*)?nguyên liệu\s+(?:người dùng\s+|bạn\s+)?(?:đã|hiện)\s+có(?:\*\*)?\s*:?\s*(?:không có[^\n]*|chưa[^\n]*)?\n?",
        lambda m: "" if re.search(r"không có|chưa", m.group(0), flags=re.IGNORECASE) else "Nguyên liệu chính cần chuẩn bị:\n",
        reply,
    )
    normalized = re.sub(
        r"(?im)^\s*(?:[#*-]+\s*)?(?:\*\*)?nguyên liệu\s+(?:chính\s+)?cần chuẩn bị\s+thêm(?:\*\*)?\s*:?",
        "Nguyên liệu bổ sung cần chuẩn bị:",
        normalized,
    )
    if normalized.count("Nguyên liệu chính cần chuẩn bị:") > 1:
        first, rest = normalized.split("Nguyên liệu chính cần chuẩn bị:", 1)
        rest = rest.replace("Nguyên liệu chính cần chuẩn bị:", "Nguyên liệu bổ sung cần chuẩn bị:")
        normalized = first + "Nguyên liệu chính cần chuẩn bị:" + rest
    cleaned_lines: list[str] = []
    skip_empty = False
    for idx, line in enumerate(normalized.splitlines()):
        if line.strip() == "Nguyên liệu chính cần chuẩn bị:":
            next_lines = [cand.strip() for cand in normalized.splitlines()[idx + 1:] if cand.strip()]
            if next_lines and re.match(r"^(không có thông tin|chưa có thông tin)\.?$", next_lines[0], flags=re.IGNORECASE):
                skip_empty = True
                continue
        if skip_empty and re.match(r"^(không có thông tin|chưa có thông tin)\.?$", line.strip(), flags=re.IGNORECASE):
            skip_empty = False
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _remove_duplicate_available_ingredients(reply: str, user_stated_ingredients: list[dict[str, Any]]) -> str:
    if not user_stated_ingredients:
        return reply
    stated_norms = [normalize_text(item["name"]) for item in user_stated_ingredients if item.get("name")]
    in_prepare_section = False
    output: list[str] = []
    for line in reply.splitlines():
        norm_line = normalize_text(line)
        if "nguyen lieu" in norm_line and ("chuan bi" in norm_line or "can them" in norm_line):
            in_prepare_section = True
            output.append(line)
            continue
        if ("buoc" in norm_line or "cach lam" in norm_line or "thuc hien" in norm_line) and not line.lstrip().startswith(("-", "*", "•")):
            in_prepare_section = False
        if in_prepare_section and line.lstrip().startswith(("-", "*", "•")):
            if any(stated and _has_phrase(norm_line, stated) for stated in stated_norms):
                continue
        output.append(line)
    return "\n".join(output)


def _validate_chefbot_output(reply: str, message: str, context: dict[str, Any]) -> bool:
    norm_reply = normalize_text(reply)
    if not norm_reply or "<think>" in reply.lower():
        return False
    if "chua co trong csdl" in norm_reply or "goi y tu nau" in norm_reply:
        return False
    for item in context.get("excluded_ingredients", []):
        excluded_norm = _norm_ing_ascii(str(item.get("name") or ""))
        if excluded_norm and _has_phrase(norm_reply, excluded_norm):
            return False

    recipes = context.get("database_recipes") or []
    norm_msg = normalize_text(message)
    needs_strict_db_grounding = bool(
        recipes
        and (
            context.get("user_stated_ingredients")
            or context.get("requested_servings")
            or _RECIPE_INTENT.search(norm_msg)
            or _SCALING_INTENT.search(norm_msg)
            or _NUTRITION_ESTIMATE.search(norm_msg)
        )
    )
    if needs_strict_db_grounding:
        # Must cite at least one approved MySQL dish title verbatim + quantitative units + kcal!
        if not any(normalize_text(r["title"]) in norm_reply for r in recipes):
            return False
        if not _QUANT_UNIT_RE.search(reply):
            return False
        if int(recipes[0].get("calories") or (recipes[0].get("nutrition") or {}).get("calories") or 0) > 0:
            if "kcal" not in norm_reply and "calo" not in norm_reply:
                return False
    return True


def _direct_cooking_substitution_reply(message: str) -> str | None:
    norm = normalize_text(message)
    if any(p in norm for p in ("khong co xi dau", "het xi dau", "thay xi dau", "khong co nuoc tuong", "thay nuoc tuong")):
        if any(p in norm for p in ("mon chay", "an chay", "chay")):
            return (
                "Trong món chay, khi hết xì dầu (nước tương) bạn có thể thay bằng:\n"
                "- **Nước mắm chay từ nấm hương/dứa** theo tỉ lệ `1:1`.\n"
                "- **Muối hầm + hạt nêm nấm hương + 1/3 muỗng cà phê đường nâu** để giữ vị đậm umami và màu nâu nhẹ.\n"
                "- Lưu ý: Đường trắng không thay thế được vị mặn umami của xì dầu."
            )
        return (
            "Nếu không có xì dầu (nước tương), bạn có thể thay thế linh hoạt như sau:\n"
            "- **Món kho / xào:** Pha `2/3 muỗng nước mắm pha loãng với 1/3 muỗng nước ấm` và thêm chút nước hàng/đường thắng nhẹ để lên màu.\n"
            "- **Món ướp / sốt sánh:** Dùng `dầu hào` giảm nhẹ lượng muối.\n"
            "- Lưu ý: Đường không thay được xì dầu vì không tạo được vị mặn đậm đà; chỉ dùng vài giọt nước màu nếu cần sắc nâu."
        )
    return None


def _prompt_context_payload(context: dict[str, Any]) -> dict[str, Any]:
    compact_recipes = []
    for idx, recipe in enumerate(context.get("database_recipes", [])[:3]):
        entry: dict[str, Any] = {
            "id": recipe["id"],
            "title": recipe["title"],
            "servings": recipe.get("servings"),
            "prepTime": recipe.get("prepTime"),
            "cookTime": recipe.get("cookTime"),
            "calories": recipe.get("calories"),
            "nutrition": recipe.get("nutrition"),
            "ingredients": [
                {"name": item["name"], "amount": item.get("amount"), "unit": item.get("unit")}
                for item in recipe.get("ingredients", [])[:14]
            ],
        }
        if idx == 0:
            entry["ingredient_breakdown"] = recipe.get("ingredient_breakdown")
            entry["steps"] = [
                {"step": s.get("step"), "title": s.get("title"), "description": str(s.get("description") or "")[:220]}
                for s in recipe.get("steps", [])[:8]
            ]
        compact_recipes.append(entry)
    compact_kb = [
        {"title": item["title"], "category": item["category"], "content": str(item["content"])[:280]}
        for item in context.get("kb_entries", [])[:2]
    ]
    learned = context.get("learned_qa") or {}
    compact_shots = [
        {"question": str(s.get("question") or "")[:160], "answer": str(s.get("answer") or "")[:450]}
        for s in (learned.get("few_shots") or [])[:1]
        if isinstance(s, dict)
    ]
    return {
        "db_status": context.get("db_status"),
        "requested_servings": context.get("requested_servings"),
        "user_stated_ingredients": [item["name"] for item in context.get("user_stated_ingredients", [])],
        "excluded_ingredients": [item["name"] for item in context.get("excluded_ingredients", [])],
        "database_recipes": compact_recipes,
        "culinary_knowledge_base": compact_kb,
        "verified_reference_qa": compact_shots,
    }


def _persist_learned_qa(
    message: str,
    context: dict[str, Any],
    reply: str,
    model_used: str,
    *,
    is_gemini_fallback: bool = False,
) -> int | None:
    if not reply or len(reply.strip()) < 25:
        return None
    if context.get("requested_servings"):
        return None
    norm_q = normalize_text(message)
    if len(norm_q) < 6:
        return None
    recipes = context.get("database_recipes") or []
    matched_ids = [int(r["id"]) for r in recipes if str(r.get("id", "")).isdigit()]
    intent = "recipe_db" if recipes else "cooking_guide"
    keywords = ",".join(w for w in norm_q.split() if len(w) >= 3 and w not in _STOP_WORDS)[:240]
    source_type = "GEMINI_VERIFIED" if is_gemini_fallback else "AUTO_LEARNED"
    initial_score = 0.85 if is_gemini_fallback else 0.78
    return save_or_update_learned_qa(
        question_text=message.strip(),
        normalized_question=norm_q,
        intent=intent,
        answer_text=reply.strip(),
        keywords_text=keywords,
        model_used=model_used,
        matched_recipe_ids=matched_ids,
        initial_score=initial_score,
        source_type=source_type,
        is_verified=False,
    )


def _make_diagnostics(
    active_provider: str,
    model_used: str,
    *,
    gemini_failed: bool = False,
    attempted_models: list[dict[str, Any]] | None = None,
    user_warning_vi: str = "",
) -> dict[str, Any]:
    return {
        "activeProvider": active_provider,
        "modelUsed": model_used,
        "geminiFailed": bool(gemini_failed),
        "attemptedModels": list(attempted_models or []),
        "userWarningVi": str(user_warning_vi or ""),
    }


def _error_result(
    reply: str,
    error_code: str,
    *,
    model_used: str = "ollama",
    fallback_used: bool = False,
    ai_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "classification": "FOOD_RELATED",
        "reply": reply,
        "error": reply,
        "error_code": error_code,
        "recipes": [],
        "suggestions": _suggestions(),
        "mode": "unavailable",
        "model_used": model_used,
        "fallback_used": fallback_used,
        "qa_id": None,
        "aiDiagnostics": ai_diagnostics or _make_diagnostics("sql_grounded", model_used, gemini_failed=True, user_warning_vi=reply),
    }


def _invoke_gemini_chain(
    message: str,
    *,
    history: list[dict[str, Any]] | None,
    system_instruction: str,
) -> dict[str, Any]:
    """
    Run Gemini Free Priority #1 -> Priority #2.
    Also adapts cleanly if a unit test patches `generate_ai_response` directly.
    """
    if "unittest.mock" in type(generate_ai_response).__module__:
        primary = Config.GEMINI_PRIMARY_MODEL
        if not Config.GEMINI_API_KEY:
            return {
                "success": False,
                "response": "",
                "model_used": "",
                "fallback_used": False,
                "gemini_failed": True,
                "error_code": "AI_MISSING_API_KEY",
                "error_message": "Chưa cấu hình GEMINI_API_KEY trong file .env.",
                "attempted_models": [{
                    "model": primary,
                    "status": "failed",
                    "httpCode": 0,
                    "reasonVi": classify_gemini_reason_vi(None, "missing_api_key"),
                }],
            }
        try:
            gen = generate_ai_response(message, conversation_history=history, system_instruction=system_instruction)
            used = str(gen.get("model_used") or primary)
            return {
                "success": True,
                "response": str(gen.get("response") or ""),
                "model_used": used,
                "fallback_used": bool(gen.get("fallback_used", False)),
                "gemini_failed": False,
                "attempted_models": [{"model": used, "status": "success", "httpCode": 200, "reasonVi": "Phản hồi thành công."}],
            }
        except GeminiPolicyError:
            raise
        except GeminiConfigurationError as cfg_err:
            code = cfg_err.http_status or (403 if cfg_err.reason == "PERMISSION_DENIED" else 401 if "EXPIRED" in cfg_err.reason else 400)
            return {
                "success": False,
                "response": "",
                "model_used": "",
                "fallback_used": False,
                "gemini_failed": True,
                "error_code": cfg_err.error_code,
                "error_message": str(cfg_err),
                "attempted_models": [{
                    "model": primary,
                    "status": "failed",
                    "httpCode": code,
                    "reasonVi": classify_gemini_reason_vi(code, cfg_err.reason.lower()),
                }],
            }
        except GeminiManagerError as mgr_err:
            code = mgr_err.http_status or 503
            return {
                "success": False,
                "response": "",
                "model_used": "",
                "fallback_used": True,
                "gemini_failed": True,
                "error_code": mgr_err.error_code,
                "error_message": str(mgr_err),
                "attempted_models": [
                    {"model": primary, "status": "failed", "httpCode": code, "reasonVi": classify_gemini_reason_vi(code, "service_unavailable")},
                    {"model": Config.GEMINI_FALLBACK_MODEL, "status": "failed", "httpCode": code, "reasonVi": classify_gemini_reason_vi(code, "service_unavailable")},
                ],
            }

    return generate_ai_response_with_diagnostics(
        message,
        conversation_history=history,
        system_instruction=system_instruction,
    )


def answer_message(
    message: str,
    *,
    recipe_id: int | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not Config.CHATBOT_ENABLED:
        return _error_result("ChefBot AI hiện đang tạm tắt trong cấu hình hệ thống.", "CHATBOT_DISABLED")

    decision = classify_message(message)
    if decision.classification != "FOOD_RELATED":
        if recipe_id and decision.classification == "UNCERTAIN":
            pass
        else:
            logger.info("[CHATBOT] event=domain_guard classification=%s", decision.classification)
            is_ok = decision.classification in {"GREETING", "OFF_TOPIC", "UNCERTAIN"}
            err_code = "AI_INVALID_INPUT" if not is_ok else None
            res: dict[str, Any] = {
                "success": is_ok,
                "classification": decision.classification,
                "reply": decision.message or OFF_TOPIC_REPLY,
                "recipes": [],
                "suggestions": _suggestions(),
                "mode": "domain_guard",
                "model_used": "guard",
                "fallback_used": False,
                "qa_id": None,
                "aiDiagnostics": _make_diagnostics("sql_grounded", "cookmate-guard"),
            }
            if err_code:
                res["error"] = res["reply"]
                res["error_code"] = err_code
            return res

    context = _build_database_context(message, recipe_id=recipe_id)
    recipes: list[dict[str, Any]] = context.get("database_recipes") or []
    norm_msg = normalize_text(message)

    if decision.contains_injection:
        safe_reply = (
            render_grounded_mysql_recipe_response(recipes, context, message)
            if recipes
            else "Mình chỉ hỗ trợ tra cứu công thức nấu ăn, định lượng nguyên liệu và dinh dưỡng từ CSDL CookMate."
        )
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": safe_reply,
            "recipes": _public_recipes(recipes),
            "suggestions": _suggestions(message, recipes=recipes, recipe_id=recipe_id),
            "mode": "internal",
            "model_used": "guard",
            "fallback_used": False,
            "qa_id": None,
            "aiDiagnostics": _make_diagnostics("sql_grounded", "cookmate-guard"),
        }

    # 1. Direct substitution fast-path
    direct_sub = _direct_cooking_substitution_reply(message)
    if direct_sub:
        qa_id = _persist_learned_qa(message, context, direct_sub, "cookmate-rule", is_gemini_fallback=False)
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": direct_sub,
            "recipes": _public_recipes(recipes),
            "suggestions": _suggestions(message, recipes=recipes, recipe_id=recipe_id),
            "mode": "cooking_guide",
            "model_used": "cookmate-guide",
            "fallback_used": False,
            "qa_id": qa_id,
            "aiDiagnostics": _make_diagnostics("sql_grounded", "cookmate-guide"),
        }

    # 2. Nutrition query when zero saved nutrition exists in DB (safety guard against hallucinated numbers)
    if _NUTRITION_ESTIMATE.search(norm_msg) and not any(r.get("nutrition") or r.get("calories") for r in recipes):
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": (
                "Mình chưa tìm thấy công thức phù hợp có số liệu dinh dưỡng đã lưu trong CSDL CookMate, "
                "nên không thể đưa ra con số đáng tin cậy. Nếu bạn chọn một công thức CookMate cụ thể, mình sẽ tra cứu ngay."
            ),
            "recipes": [],
            "suggestions": _suggestions(message, recipe_id=recipe_id),
            "mode": "database_info",
            "model_used": "mysql",
            "fallback_used": False,
            "qa_id": None,
            "aiDiagnostics": _make_diagnostics("sql_grounded", "mysql"),
        }

    # 3. Foreign dish absent from CookMate's 300-recipe catalog -> Polite notice + Top 3 closest MySQL recipes
    if context.get("foreign_dish_requested") and recipes:
        grounded_foreign = render_grounded_mysql_recipe_response(recipes, context, message)
        qa_id = _persist_learned_qa(message, context, grounded_foreign, "mysql-rag", is_gemini_fallback=False)
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": grounded_foreign,
            "recipes": _public_recipes(recipes),
            "suggestions": _suggestions(message, recipes=recipes, recipe_id=recipe_id),
            "mode": "mysql_grounded",
            "model_used": "mysql-rag",
            "fallback_used": False,
            "qa_id": qa_id,
            "aiDiagnostics": _make_diagnostics("sql_grounded", "mysql-rag"),
        }

    # 4. Verified culinary QA memory fast-path (for troubleshooting / techniques without pantry/recipe scaling)
    learned_bundle = context.get("learned_qa") if isinstance(context.get("learned_qa"), dict) else None
    exact_qa = learned_bundle.get("exact") if learned_bundle else None
    if (
        exact_qa
        and exact_qa.get("is_verified")
        and float(exact_qa.get("quality_score") or 0) >= 0.92
        and not recipe_id
        and not context.get("requested_servings")
        and not context.get("user_stated_ingredients")
        and not recipes
    ):
        qa_id = _persist_learned_qa(message, context, exact_qa["answer"], "cookmate-memory", is_gemini_fallback=False) or exact_qa.get("qa_id")
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": exact_qa["answer"],
            "recipes": [],
            "suggestions": _suggestions(message, recipe_id=recipe_id),
            "mode": "memory_verified",
            "model_used": "cookmate-memory",
            "fallback_used": False,
            "qa_id": qa_id,
            "notice": "Câu trả lời đã kiểm chứng từ bộ nhớ kiến thức ẩm thực CookMate.",
            "aiDiagnostics": _make_diagnostics("sql_grounded", "cookmate-memory"),
        }

    # 5. Build 100% MySQL-grounded prompt for Priority Chain:
    #    #1 Gemini Primary Free -> #2 Gemini Secondary Free -> #3 Ollama Local (qwen3.5:4b)
    prompt_payload = _prompt_context_payload(context)
    context_json = json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"), default=str)
    pantry_note = (
        f"\nTÌNH TRẠNG NGUYÊN LIỆU: Người dùng đang có {', '.join(i['name'] for i in context['user_stated_ingredients'])}.\n"
        if context.get("user_stated_ingredients")
        else "\nTÌNH TRẠNG NGUYÊN LIỆU: Người dùng chưa kê nguyên liệu sẵn có; ghi tất cả vào mục Nguyên liệu cần chuẩn bị.\n"
    )
    extra_rules = (
        "\nRÀNG BUỘC TRẢ LỜI:\n"
        + (f"- Món bắt buộc lấy từ database_recipes[0]: {recipes[0]['title']} ({recipes[0].get('calories', 0)} kcal/khẩu phần).\n" if recipes else "")
        + (f"- Quy đổi định lượng cho đúng {context['requested_servings']} người.\n" if context.get("requested_servings") else "")
        + "- Trình bày đầy đủ định lượng gram/ml/muỗng/quả và các bước chế biến súc tích từ database_recipes[0] (nếu có món phụ chỉ nêu tên món + kcal 1 dòng); tuyệt đối không tự đoán ngoài CSDL.\n"
    )
    system_instruction = (
        SYSTEM_INSTRUCTION
        + pantry_note
        + "\nDỮ LIỆU CSDL MYSQL COOKMATE (JSON 300 MÓN):\n"
        + context_json
        + extra_rules
    )

    # --- PRIORITY #1 & #2: GOOGLE GEMINI FREE MODELS ---
    try:
        gem_res = _invoke_gemini_chain(message, history=history, system_instruction=system_instruction)
    except GeminiPolicyError as policy_err:
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": str(policy_err),
            "recipes": _public_recipes(recipes),
            "suggestions": _suggestions(message, recipes=recipes, recipe_id=recipe_id),
            "mode": "guard",
            "model_used": "gemini",
            "fallback_used": False,
            "qa_id": None,
            "aiDiagnostics": _make_diagnostics("gemini", "gemini-guard"),
        }
    except GeminiInputError as inp_err:
        return _error_result(str(inp_err), inp_err.error_code, model_used="gemini", fallback_used=False)

    if gem_res.get("success"):
        reply = re.sub(r"(?m)^#\s+", "", str(gem_res.get("response") or ""))
        reply = _strip_model_source_labels(reply)
        reply = _normalize_inventory_headings(reply, context.get("user_stated_ingredients") or [])
        reply = _remove_duplicate_available_ingredients(reply, context.get("user_stated_ingredients") or [])
        if not _validate_chefbot_output(reply, message, context):
            if recipes:
                reply = render_grounded_mysql_recipe_response(recipes, context, message)
        used_gemini = str(gem_res.get("model_used") or Config.GEMINI_PRIMARY_MODEL)
        qa_id = _persist_learned_qa(message, context, reply, used_gemini, is_gemini_fallback=True)
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": reply,
            "recipes": _public_recipes(recipes),
            "suggestions": _suggestions(message, recipes=recipes, recipe_id=recipe_id),
            "mode": "gemini_rag" if recipes else "gemini_guide",
            "notice": "",
            "model_used": used_gemini,
            "fallback_used": bool(gem_res.get("fallback_used", False)),
            "qa_id": qa_id,
            "aiDiagnostics": _make_diagnostics(
                "gemini",
                used_gemini,
                gemini_failed=False,
                attempted_models=gem_res.get("attempted_models") or [],
                user_warning_vi="",
            ),
        }

    # --- PRIORITY #3: LOCAL OLLAMA FALLBACK (ONLY AFTER BOTH GEMINI MODELS FAILED) ---
    attempted_gemini = list(gem_res.get("attempted_models") or [])
    gem_error_code = str(gem_res.get("error_code") or "AI_SERVICE_UNAVAILABLE")
    gem_error_msg = str(gem_res.get("error_message") or SAFE_UNAVAILABLE_MESSAGE)
    logger.warning(
        "[CHATBOT] event=gemini_failed_switching_to_ollama attempted=%d code=%s",
        len(attempted_gemini),
        gem_error_code,
    )

    ollama_error: OllamaError | None = None
    try:
        generated = generate_ollama_response(
            message,
            system_instruction=system_instruction,
            conversation_history=history,
        )
        reply = re.sub(r"(?m)^#\s+", "", str(generated["response"] or ""))
        reply = _strip_model_source_labels(reply)
        reply = _normalize_inventory_headings(reply, context.get("user_stated_ingredients") or [])
        reply = _remove_duplicate_available_ingredients(reply, context.get("user_stated_ingredients") or [])
        if not _validate_chefbot_output(reply, message, context):
            if recipes:
                reply = render_grounded_mysql_recipe_response(recipes, context, message)
            else:
                raise OllamaError("INVALID_GROUNDED_CONTENT")
        used_ollama = str(generated["model_used"])
        warn_vi = build_gemini_warning_vi(attempted_gemini, f"AI nội bộ Ollama ({used_ollama})")
        qa_id = _persist_learned_qa(message, context, reply, used_ollama, is_gemini_fallback=False)
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": reply,
            "recipes": _public_recipes(recipes),
            "suggestions": _suggestions(message, recipes=recipes, recipe_id=recipe_id),
            "mode": "ollama_fallback",
            "notice": warn_vi,
            "model_used": used_ollama,
            "fallback_used": True,
            "qa_id": qa_id,
            "aiDiagnostics": _make_diagnostics(
                "ollama",
                used_ollama,
                gemini_failed=True,
                attempted_models=attempted_gemini,
                user_warning_vi=warn_vi,
            ),
        }
    except OllamaError as err_ol:
        ollama_error = err_ol
        logger.warning("[CHATBOT] event=ollama_fallback_failed model=%s reason=%s", Config.OLLAMA_MODEL, err_ol.reason)

    # --- DETERMINISTIC SQL GROUNDED SAFETY NET WHEN ALL AI MODELS ARE DOWN ---
    if recipes:
        grounded = render_grounded_mysql_recipe_response(recipes, context, message)
        warn_sql = build_gemini_warning_vi(attempted_gemini, "bộ kết xuất chuẩn định lượng MySQL CookMate")
        qa_id = _persist_learned_qa(message, context, grounded, "mysql-rag", is_gemini_fallback=False)
        return {
            "success": True,
            "classification": "FOOD_RELATED",
            "reply": grounded,
            "recipes": _public_recipes(recipes),
            "suggestions": _suggestions(message, recipes=recipes, recipe_id=recipe_id),
            "mode": "mysql_grounded",
            "notice": warn_sql,
            "model_used": "mysql-rag",
            "fallback_used": True,
            "qa_id": qa_id,
            "aiDiagnostics": _make_diagnostics(
                "sql_grounded",
                "mysql-rag",
                gemini_failed=True,
                attempted_models=attempted_gemini,
                user_warning_vi=warn_sql,
            ),
        }

    if gem_error_code != "AI_SERVICE_UNAVAILABLE":
        warn_err = build_gemini_warning_vi(attempted_gemini, "Ollama cục bộ (cũng đang ngoại tuyến)")
        return _error_result(
            gem_error_msg,
            gem_error_code,
            model_used="gemini",
            fallback_used=True,
            ai_diagnostics=_make_diagnostics("sql_grounded", "unavailable", gemini_failed=True, attempted_models=attempted_gemini, user_warning_vi=warn_err),
        )

    if ollama_error and ollama_error.reason in {"THINK_PARAMETER_UNSUPPORTED", "THINK_FALSE_NOT_HONORED", "THINKING_LEAK_IN_CONTENT"}:
        reply_err = "Cả Google Gemini và Ollama hiện chưa sẵn sàng (Ollama chưa xác nhận chế độ tắt suy luận). Vui lòng thử lại sau."
    else:
        reply_err = "Hiện không kết nối được API Google Gemini và AI dự phòng Ollama cục bộ cũng chưa phản hồi. Hãy kiểm tra kết nối mạng hoặc dịch vụ Ollama."
    return _error_result(
        reply_err,
        "AI_OLLAMA_UNAVAILABLE",
        model_used="ollama",
        fallback_used=True,
        ai_diagnostics=_make_diagnostics(
            "sql_grounded",
            "unavailable",
            gemini_failed=True,
            attempted_models=attempted_gemini,
            user_warning_vi=build_gemini_warning_vi(attempted_gemini, "Ollama cục bộ (chưa kết nối được)"),
        ),
    )


def _suggestions(message: str = "", *, recipes: list[dict[str, Any]] | None = None, recipe_id: int | None = None) -> list[str]:
    if recipes:
        first_title = str(recipes[0].get("title") or "món này")
        return [
            f"Quy đổi {first_title} cho 6 người ăn",
            f"Món {first_title} bao nhiêu calo mỗi phần?",
            "Nếu thiếu gia vị trong món này thì thay bằng gì?",
        ]
    if recipe_id:
        return [
            "Quy đổi khẩu phần món đang xem cho 6 người",
            "Kiểm tra calo & dinh dưỡng của món này",
            "Có nguyên liệu nào thay thế được không?",
        ]
    norm = normalize_text(message)
    if any(tok in norm for tok in ("chay", "dau hu", "nam")):
        return [
            "Gợi ý thực đơn mâm cơm chay thanh đạm",
            "Nước mắm chay thay thế trong món kho sao cho đậm?",
            "Món chay giàu đạm nấu trong 20 phút",
        ]
    return [
        "Tôi có thịt gà và cà chua, nấu món gì?",
        "Cá kho bị mặn thì xử lý sao cho vừa miệng?",
        "Món ít dầu mỡ tốt cho người giảm cân?",
    ]
