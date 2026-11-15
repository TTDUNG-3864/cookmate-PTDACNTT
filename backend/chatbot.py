# -*- coding: utf-8 -*-
"""
CookMate ChefBot — Trợ Lý Đầu Bếp AI (Backend Engine)
=====================================================
Tích hợp đầy đủ 3 nhóm chức năng thông minh trên cơ sở dữ liệu SQLite (`cookmate.db`):

Nhóm 1 — Khai thác CSDL CookMate cốt lõi:
  1. "Tủ lạnh nhà bạn có gì?" (Gợi ý món ăn từ nguyên liệu sẵn có)
  2. Tư vấn thực đơn theo mục tiêu Calo & Dinh dưỡng (UC06-B)
  3. Tính toán & Quy đổi khẩu phần ăn tức thì trong Chat (UC06-A)

Nhóm 2 — Trợ lý Đứng bếp theo ngữ cảnh (Context-Aware Kitchen Assistant):
  4. Hỏi đáp theo đúng món ăn đang mở trên màn hình (Bước làm, Thời gian, Mẹo)
  5. Gợi ý nguyên liệu thay thế (Ingredient Substitution)
  6. "Cấp cứu món ăn" — Xử lý sự cố nhà bếp (Mặn, nhão, khê, đục nước, tanh...)

Nhóm 3 — Tiện ích thông minh & Cá nhân hóa:
  7. Gợi ý món theo thời tiết, dịp lễ (Tết, Rằm, Cuối tuần) hoặc nấu nhanh (< 25 phút)
  8. Tạo "Danh sách đi chợ" (Shopping List) gộp định lượng tự động
  9. Hỗ trợ tạo nháp công thức mới bằng AI (AI Recipe Generator) điền 1-click vào Form
"""

import json
import os
import re
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from backend import database as db


# ============================================================
# CƠ SỞ TRI THỨC ẨM THỰC VIỆT NAM (NHÓM 2 & NHÓM 3)
# ============================================================

SUBSTITUTION_KNOWLEDGE = [
    {
        "keywords": ["nước cốt dừa", "nuoc cot dua", "cốt dừa"],
        "ingredient": "Nước cốt dừa",
        "substitutes": [
            "**Sữa tươi không đường + Bơ lạt:** Pha 200ml sữa tươi không đường với 15g bơ lạt đun chảy (tạo độ béo ngậy gần giống 85% cốt dừa).",
            "**Sữa đặc + Sữa tươi:** Dùng cho các món chè hoặc bánh ngọt (180ml sữa tươi + 2 muỗng canh sữa đặc).",
            "**Kem tươi (Whipping Cream):** Thay thế tỷ lệ 1:1 cho các món cà ri hoặc súp.",
        ],
    },
    {
        "keywords": ["nước mắm", "nuoc mam", "ăn chay", "mắm chay"],
        "ingredient": "Nước mắm (hoặc thay thế chay)",
        "substitutes": [
            "**Nước tương (Xì dầu) + Một chút muối:** Thay tỷ lệ 1:1 kèm 1/4 muỗng cà phê muối để giữ độ đậm đà.",
            "**Nước mắm chay từ dứa/nấm:** Nấu nước dứa ép với muối biển, đường phèn và nước tương lên men.",
            "**Muối + Bột nấm hương:** Dùng cho các món canh chay cần vị ngọt thanh.",
        ],
    },
    {
        "keywords": ["bột năng", "bot nang", "bột bắp", "bot bap", "tạo sánh"],
        "ingredient": "Bột năng / Bột bắp",
        "substitutes": [
            "**Bột bắp (Cornstarch) ↔ Bột năng (Tapioca starch):** Thay thế trực tiếp tỷ lệ 1:1 để tạo độ sánh cho súp, chè hoặc nước sốt.",
            "**Bột sắn dây:** Pha loãng với nước lạnh rồi đổ từ từ vào nồi đang sôi.",
            "**Bột mì đa dụng:** Dùng gấp đôi lượng bột năng nếu làm đặc nước sốt xào.",
        ],
    },
    {
        "keywords": ["rượu nấu ăn", "ruou nau an", "rượu trắng", "rượu mirin", "khử mùi"],
        "ingredient": "Rượu nấu ăn / Rượu trắng",
        "substitutes": [
            "**Gừng đập dập + Giấm gạo:** Chà xát trực tiếp lên thịt/cá giúp khử mùi hôi tanh hiệu quả như rượu.",
            "**Nước cốt chanh + Muối hạt:** Rất hợp để sơ chế hải sản, gà, vịt.",
            "**Nước táo ép + 1 chút đường:** Thay cho rượu ngọt Mirin trong các món sốt.",
        ],
    },
    {
        "keywords": ["đường phèn", "duong phen", "đường nâu", "duong nau", "đường thốt nốt"],
        "ingredient": "Đường phèn / Đường thốt nốt",
        "substitutes": [
            "**Đường cát trắng:** Thay tỷ lệ 1:0.9 (đường cát ngọt gắt hơn đường phèn một chút).",
            "**Mật ong:** Dùng 3/4 lượng đường, cho vào cuối khi món ăn đã hạ nhiệt để giữ hương thơm.",
        ],
    },
    {
        "keywords": ["chanh", "giấm", "giam", "me chua", "tạo chua"],
        "ingredient": "Chanh / Giấm / Me chua",
        "substitutes": [
            "**Quất (Tắc):** Thay cho chanh theo tỷ lệ 2 quả tắc = 1 quả chanh vừa, dậy mùi rất thơm cho món bún/phở.",
            "**Giấm táo hoặc Giấm gạo:** 1 muỗng canh giấm = 1 muỗng canh nước cốt chanh.",
            "**Cà chua hoặc Dứa (Thơm):** Tạo vị chua thanh tự nhiên cho các món canh chua.",
        ],
    },
    {
        "keywords": ["bơ lạt", "bo lat", "dầu hào", "dau hao"],
        "ingredient": "Bơ lạt / Dầu hào",
        "substitutes": [
            "**Thay Dầu hào:** Dùng 1 muỗng canh nước tương + 1/2 muỗng cà phê đường + 1/4 muỗng cà phê bột năng.",
            "**Thay Bơ lạt:** Dùng dầu ô-liu hoặc dầu thực vật theo tỷ lệ 10g bơ = 8ml dầu ăn.",
        ],
    },
]

KITCHEN_RESCUE_KNOWLEDGE = [
    {
        "keywords": ["bị mặn", "bi man", "mặn quá", "man qua", "chữa mặn", "chua man"],
        "problem": "Món canh / Món kho bị mặn quá",
        "solutions": [
            "**Mẹo khoai tây sống:** Gọt vỏ 1 củ khoai tây, cắt lát dày thả vào nồi canh/nồi kho đun 10 phút rồi vớt ra — khoai tây sẽ hút bớt lượng muối thừa cực nhạy!",
            "**Thêm nước sôi + Cà chua/Dứa:** Với món canh, châm thêm nước sôi và vài múi cà chua (vị chua nhẹ làm dịu cảm giác mặn).",
            "**Pha dịu bằng đường phèn hoặc nước cốt dừa:** Với món thịt/cá kho, thêm 1 muỗng cà phê đường hoặc chút nước dừa tươi rồi đun nhỏ lửa.",
        ],
    },
    {
        "keywords": ["bị nhão", "cơm nhão", "com nhao", "bị khê", "cơm khê", "com khe", "cơm sống"],
        "problem": "Cơm bị nhão, khê hoặc sống",
        "solutions": [
            "**Cơm bị nhão:** Mở nắp nồi, đặt 1–2 lát bánh mì sandwich (hoặc khăn giấy sạch gấp dày) lên mặt cơm, đậy nắp bật nút Warm 10 phút để hút hết hơi nước thừa.",
            "**Cơm bị khê (cháy đáy):** Đặt ngay 1 bát nhỏ nước lạnh hoặc 1 phần gốc hành lá tươi lên mặt cơm, đậy nắp 5 phút — mùi khê sẽ bị hút sạch!",
            "**Cơm bị sống/sượng:** Xới tơi cơm, rưới đều 2 muỗng canh nước ấm (hoặc chút rượu trắng theo tỷ lệ 10ml/nồi) rồi bấm nấu lại.",
        ],
    },
    {
        "keywords": ["bị đục", "nước dùng đục", "nuoc pho duc", "nước lèo đục", "nuoc dung duc"],
        "problem": "Nước dùng Phở / Canh hầm xương bị đục",
        "solutions": [
            "**Dùng lòng trắng trứng gà:** Đánh tan 1 lòng trắng trứng, đổ vào nồi nước dùng đang ấm rồi khuấy đều. Khi sôi, lòng trắng kết tủa sẽ cuốn sạch cặn đục — chỉ cần lọc qua rây là nước trong veo!",
            "**Thả vài lát khoai tây sống:** Giúp lắng cặn xương hiệu quả.",
            "**Lưu ý lửa:** Luôn chần xương lần đầu với nước sôi + gừng, rửa sạch rồi mới ninh lửa liu riu, không đậy kín nắp.",
        ],
    },
    {
        "keywords": ["bị dai", "thịt dai", "thit bo dai", "thịt cứng"],
        "problem": "Thịt bò / Thịt hầm bị dai hoặc khô",
        "solutions": [
            "**Khi đang hầm:** Cho vào nồi vài miếng **dứa (thơm) chín**, 1 muỗng nước cốt chanh hoặc 1 miếng đu đủ xanh nhỏ — enzyme tự nhiên giúp thịt mềm nhanh gấp đôi.",
            "**Khi ướp thịt bò xào:** Ướp với 1 muỗng dầu ăn + chút bột bắp và ướp muối/nước mắm sau cùng để thịt không bị ra nước.",
        ],
    },
    {
        "keywords": ["cay quá", "cay qua", "quá cay", "chua quá", "chua qua", "bị chua"],
        "problem": "Món ăn bị quá cay hoặc quá chua",
        "solutions": [
            "**Giảm độ cay:** Thêm nước cốt dừa, sữa tươi, đường hoặc một ít bơ đậu phộng; capsaicin tan trong chất béo nên sẽ dịu ngay.",
            "**Giảm độ chua:** Thêm 1/2 muỗng cà phê đường hoặc một nhúm rất nhỏ muối nở (baking soda) để trung hòa axit.",
        ],
    },
    {
        "keywords": ["bị tanh", "cá tanh", "hải sản tanh", "khu mui tanh"],
        "problem": "Cá hoặc Hải sản bị tanh",
        "solutions": [
            "**Khi sơ chế:** Rửa bằng nước vo gạo, hoặc chà muối + gừng đập dập + rượu trắng, nhớ cạo sạch màng đen trong bụng cá.",
            "**Khi đang nấu:** Cho thêm nước chè xanh đặc, gừng thái chỉ, sả đập dập, thì là hoặc cà chua để át hoàn toàn mùi tanh.",
        ],
    },
]

AI_RECIPE_TEMPLATES = {
    "sườn xào chua ngọt": {
        "title": "Sườn Xào Chua Ngọt Chuẩn Vị Bắc",
        "description": "Sườn non mềm thấm đẫm sốt chua ngọt bóng mượt màu cánh gián, cực kỳ đưa cơm cho bữa tối gia đình.",
        "categoryId": 3,
        "occasion": "tiecgiadinh",
        "difficulty": "Dễ",
        "prepTime": 15,
        "cookTime": 25,
        "servings": 4,
        "image": "https://images.unsplash.com/photo-1544025162-d76694265947?w=800&auto=format&fit=crop&q=80",
        "ingredients": [
            {"name": "Sườn non heo", "amount": 500, "unit": "g"},
            {"name": "Hành tím, tỏi băm", "amount": 30, "unit": "g"},
            {"name": "Giấm gạo (hoặc cốt chanh)", "amount": 3, "unit": "muỗng canh"},
            {"name": "Đường cát", "amount": 3, "unit": "muỗng canh"},
            {"name": "Nước mắm ngon", "amount": 2, "unit": "muỗng canh"},
            {"name": "Cà chua", "amount": 100, "unit": "g"},
        ],
        "steps": [
            {"step": 1, "description": "Sườn non chặt miếng vừa ăn, chần qua nước sôi có pha chút muối và gừng để khử mùi, rửa sạch để ráo."},
            {"step": 2, "description": "Áp chảo sườn với chút dầu ăn cho vàng sém 2 mặt. Pha chén sốt chua ngọt gồm: 3 muỗng nước lọc, 3 muỗng đường, 3 muỗng giấm, 2 muỗng nước mắm."},
            {"step": 3, "description": "Phi thơm hành tỏi và cà chua băm, đổ chén nước sốt vào sườn, đun lửa nhỏ 15 phút đến khi nước sốt sánh kẹo bám đều quanh miếng sườn."},
        ],
    },
    "gà nướng mật ong": {
        "title": "Đùi Gà Nướng Mật Ong Tỏi Thơm Lừng",
        "description": "Lớp da gà vàng óng giòn rụm quyện vị ngọt thanh của mật ong rừng và hương tỏi phi quyến rũ.",
        "categoryId": 4,
        "occasion": "tiecgiadinh",
        "difficulty": "Trung bình",
        "prepTime": 20,
        "cookTime": 30,
        "servings": 4,
        "image": "https://images.unsplash.com/photo-1598515214211-89d3c73ae83b?w=800&auto=format&fit=crop&q=80",
        "ingredients": [
            {"name": "Thịt gà (Đùi gà góc tư)", "amount": 800, "unit": "g"},
            {"name": "Mật ong nguyên chất", "amount": 3, "unit": "muỗng canh"},
            {"name": "Tỏi băm, sả băm", "amount": 30, "unit": "g"},
            {"name": "Nước mắm", "amount": 2, "unit": "muỗng canh"},
            {"name": "Dầu ăn", "amount": 1, "unit": "muỗng canh"},
        ],
        "steps": [
            {"step": 1, "description": "Đùi gà rửa sạch với muối và gừng, khứa nhẹ vài đường trên thớ thịt để gia vị thấm sâu."},
            {"step": 2, "description": "Ướp gà với 2 muỗng mật ong, nước mắm, tỏi sả băm, tiêu xay và dầu ăn trong ít nhất 30 phút."},
            {"step": 3, "description": "Nướng ở nhiệt độ 190 độ C trong 25–30 phút. Phết thêm 1 lớp mật ong lên da gà ở 5 phút cuối để lên màu nâu bóng đẹp mắt."},
        ],
    },
}


def _normalize(text: str) -> str:
    return db.slugify_vietnamese(text or "").replace("-", " ")


def _format_recipe_card(r: Dict[str, Any]) -> Dict[str, Any]:
    nut = r.get("nutrition") or {}
    return {
        "id": r["id"],
        "title": r["title"],
        "image": r["image"],
        "categoryName": r.get("categoryName", "Món ngon"),
        "totalTime": r.get("totalTime") or (int(r.get("prepTime", 15)) + int(r.get("cookTime", 20))),
        "servings": r.get("servings", 4),
        "calories": nut.get("calories") or r.get("calories", 350),
        "protein": nut.get("protein", "15g"),
        "difficulty": r.get("difficulty", "Dễ"),
        "rating": r.get("rating", 4.8),
        "ingredients": r.get("ingredients", []),
    }


def _find_mentioned_recipes(msg_norm: str, all_recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matched = []
    for r in all_recipes:
        title_norm = _normalize(r["title"])
        if title_norm and title_norm in msg_norm:
            matched.append(r)
            continue
        # Also match key 2-3 word phrases from title
        words = [w for w in title_norm.split() if len(w) >= 2]
        if len(words) >= 2:
            short_title = " ".join(words[:2])
            if len(short_title) >= 5 and short_title in msg_norm:
                matched.append(r)
    return matched


# ============================================================
# 1. TỦ LẠNH NHÀ BẠN CÓ GÌ? (FRIDGE INGREDIENT MATCHER)
# ============================================================

def _handle_fridge_search(
    message: str, msg_norm: str, all_recipes: List[Dict[str, Any]], all_ingredients: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    # Detect ingredients mentioned by the user
    detected_ing_names: List[str] = []
    for ing in all_ingredients:
        ing_norm = _normalize(ing["name"])
        if ing_norm and re.search(r"\b" + re.escape(ing_norm) + r"\b", msg_norm):
            detected_ing_names.append(ing["name"])

    # Extra common ingredient keywords
    extra_keywords = {
        "thit bo": "Thịt bò",
        "thit heo": "Thịt heo",
        "thit lon": "Thịt heo",
        "suon": "Sườn heo",
        "thit ga": "Thịt gà",
        "trung": "Trứng gà",
        "ca chua": "Cà chua",
        "dau hu": "Đậu hũ",
        "dau phu": "Đậu hũ",
        "tom": "Tôm tươi",
        "ca": "Cá",
        "muc": "Mực",
        "nam": "Nấm",
        "bi do": "Bí đỏ",
        "khoai tay": "Khoai tây",
        "ca rot": "Cà rốt",
        "bun": "Bún tươi",
        "banh pho": "Bánh phở",
        "com": "Cơm / Gạo",
    }
    for kw, label in extra_keywords.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", msg_norm):
            if not any(_normalize(label) in _normalize(x) for x in detected_ing_names):
                detected_ing_names.append(label)

    if not detected_ing_names:
        return None

    scored_recipes = []
    for r in all_recipes:
        r_ings = r.get("ingredients", [])
        have_list = []
        missing_list = []
        for ri in r_ings:
            ri_norm = _normalize(ri["name"])
            matched_user = any(
                _normalize(u_ing) in ri_norm or ri_norm in _normalize(u_ing)
                for u_ing in detected_ing_names
            )
            if matched_user:
                have_list.append(ri["name"])
            else:
                missing_list.append(ri["name"])
        if have_list:
            score = len(have_list) / max(1.0, float(len(r_ings)))
            scored_recipes.append((len(have_list), score, r, have_list, missing_list))

    if not scored_recipes:
        return None

    scored_recipes.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top = scored_recipes[:3]

    lines = [
        f"🧊 **Từ nguyên liệu bạn có ({', '.join(detected_ing_names)})**, ChefBot tìm thấy **{len(scored_recipes)} món ngon** phù hợp nhất trong CSDL CookMate:\n"
    ]
    cards = []
    for idx, (match_cnt, ratio, r, have_l, miss_l) in enumerate(top, 1):
        miss_preview = ", ".join(miss_l[:3]) + ("..." if len(miss_l) > 3 else "")
        status_note = (
            "✅ Đủ nguyên liệu chính!"
            if not miss_l
            else f"🛒 Cần chuẩn bị thêm: *{miss_preview}*"
        )
        lines.append(
            f"{idx}. **{r['title']}** ({r.get('calories', 350)} kcal • {r.get('totalTime', 30)} phút)\n"
            f"   - Đã khớp: **{match_cnt}/{len(r.get('ingredients', []))}** nguyên liệu ({', '.join(have_l)})\n"
            f"   - {status_note}"
        )
        cards.append(_format_recipe_card(r))

    lines.append(
        "\n💡 *Bạn có thể nhấn vào thẻ món ăn bên dưới để xem chi tiết hoặc bấm **+ Đi chợ** để lưu nguyên liệu còn thiếu nhé!*"
    )
    return {
        "intent": "fridge_match",
        "reply": "\n".join(lines),
        "recipes": cards,
        "suggestions": [
            f"Quy đổi {top[0][2]['title']} cho 6 người",
            "Lập danh sách đi chợ cho món này",
            "Gợi ý món dưới 400 kcal",
        ],
    }


# ============================================================
# 2. TƯ VẤN THỰC ĐƠN THEO CALO & DINH DƯỠNG (UC06-B)
# ============================================================

def _handle_nutrition_query(
    message: str, msg_norm: str, all_recipes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    # Check if user asked for a full day 3-meal menu
    cal_match = re.search(r"(\d{3,4})\s*(?:kcal|calo|cal)", msg_norm)
    target_cal = int(cal_match.group(1)) if cal_match else None

    if "thuc don" in msg_norm or "3 bua" in msg_norm or (target_cal and target_cal >= 1000):
        daily_budget = target_cal or 1500
        # Pick 1 breakfast/light, 1 main dish, 1 soup/salad
        breakfasts = [r for r in all_recipes if r.get("categoryId") in (1, 2, 7)] or all_recipes[:3]
        mains = [r for r in all_recipes if r.get("categoryId") in (3, 4)] or all_recipes[3:6]
        soups = [r for r in all_recipes if r.get("categoryId") in (5, 6)] or all_recipes[6:9]

        b_dish = min(breakfasts, key=lambda r: abs(int(r.get("calories", 350)) - daily_budget * 0.3))
        m_dish = min(mains, key=lambda r: abs(int(r.get("calories", 450)) - daily_budget * 0.4))
        s_dish = min(soups, key=lambda r: abs(int(r.get("calories", 250)) - daily_budget * 0.3))

        chosen = [b_dish, m_dish, s_dish]
        total_c = sum(int(r.get("calories", 350)) for r in chosen)
        reply = (
            f"🥗 **Thực đơn 3 bữa cân bằng dinh dưỡng (Mục tiêu ~{daily_budget} kcal/ngày):**\n\n"
            f"- 🌅 **Bữa sáng:** **{b_dish['title']}** — `{b_dish.get('calories')} kcal` (Đạm: {b_dish.get('nutrition', {}).get('protein', '15g')})\n"
            f"- ☀️ **Bữa trưa:** **{m_dish['title']}** — `{m_dish.get('calories')} kcal` (Đạm: {m_dish.get('nutrition', {}).get('protein', '22g')})\n"
            f"- 🌙 **Bữa tối thanh đạm:** **{s_dish['title']}** — `{s_dish.get('calories')} kcal` (Chất xơ: {s_dish.get('nutrition', {}).get('fiber', '4g')})\n\n"
            f"🔥 **Tổng năng lượng 3 bữa:** **{total_c} kcal / người** — Đầy đủ nhóm chất Đạm, Tinh bột, Chất béo tốt và Chất xơ!"
        )
        return {
            "intent": "nutrition_plan",
            "reply": reply,
            "recipes": [_format_recipe_card(r) for r in chosen],
            "suggestions": [
                "Tạo danh sách đi chợ cho 3 món này",
                "Món ăn dưới 350 kcal giảm cân",
                "Món giàu Protein tăng cơ",
            ],
        }

    max_cal = target_cal if (target_cal and target_cal < 1000) else 420
    if "giau dam" in msg_norm or "protein" in msg_norm or "tang co" in msg_norm:
        def _prot_val(r):
            p = str((r.get("nutrition") or {}).get("protein", "0")).replace("g", "").strip()
            try:
                return float(p)
            except ValueError:
                return 0.0

        sorted_prot = sorted(all_recipes, key=_prot_val, reverse=True)[:3]
        lines = ["💪 **Top 3 món ăn giàu Đạm (Protein) nhất trên CookMate:**\n"]
        for idx, r in enumerate(sorted_prot, 1):
            nut = r.get("nutrition") or {}
            lines.append(
                f"{idx}. **{r['title']}** — **{nut.get('protein', '25g')} Protein** • `{r.get('calories')} kcal/khẩu phần`"
            )
        return {
            "intent": "nutrition_plan",
            "reply": "\n".join(lines),
            "recipes": [_format_recipe_card(r) for r in sorted_prot],
            "suggestions": ["Thực đơn 3 bữa 1500 kcal", "Món ăn dưới 350 kcal", "Tủ lạnh có ức gà, trứng"],
        }

    low_cal = [r for r in all_recipes if int(r.get("calories", 350)) <= max_cal]
    if not low_cal:
        low_cal = sorted(all_recipes, key=lambda r: int(r.get("calories", 350)))[:3]
    else:
        low_cal = sorted(low_cal, key=lambda r: int(r.get("calories", 350)))[:4]

    lines = [
        f"🌿 **Các món ngon thanh đạm dưới {max_cal} kcal/khẩu phần (phù hợp Eat Clean & kiểm soát cân nặng):**\n"
    ]
    for idx, r in enumerate(low_cal, 1):
        nut = r.get("nutrition") or {}
        lines.append(
            f"{idx}. **{r['title']}** — `{r.get('calories')} kcal` | Đạm: {nut.get('protein', '12g')} | Chất xơ: {nut.get('fiber', '3g')} ({r.get('totalTime', 25)} phút)"
        )
    return {
        "intent": "nutrition_plan",
        "reply": "\n".join(lines),
        "recipes": [_format_recipe_card(r) for r in low_cal[:3]],
        "suggestions": [
            "Lên thực đơn 3 bữa 1500 kcal",
            "Món giàu Protein tăng cơ",
            "Tạo danh sách đi chợ",
        ],
    }


# ============================================================
# 3. TÍNH TOÁN & QUY ĐỔI KHẨU PHẦN TỨC THÌ (UC06-A)
# ============================================================

def _handle_portion_scaling(
    message: str,
    msg_norm: str,
    all_recipes: List[Dict[str, Any]],
    current_recipe_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    srv_match = re.search(r"(\d+)\s*(?:nguoi|khau phan|suat|phan)", msg_norm)
    if not srv_match:
        return None
    target_servings = max(1, min(50, int(srv_match.group(1))))

    mentioned = _find_mentioned_recipes(msg_norm, all_recipes)
    target_recipe = mentioned[0] if mentioned else None
    if not target_recipe and current_recipe_id:
        target_recipe = next((r for r in all_recipes if r["id"] == int(current_recipe_id)), None)
    if not target_recipe and all_recipes:
        target_recipe = all_recipes[0]

    if not target_recipe:
        return None

    scaled = db.scale_recipe(target_recipe["id"], target_servings)
    if not scaled:
        return None

    ing_lines = [
        f"- **{ing['name']}:** `{ing['amount']} {ing['unit']}` *(gốc {scaled['baseServings']} người: {ing['originalAmount']} {ing['unit']})*"
        for ing in scaled["ingredients"]
    ]
    reply = (
        f"⚖️ **Bảng định lượng món \"{target_recipe['title']}\" quy đổi cho {target_servings} người ăn** "
        f"(Tỷ lệ co giãn: **×{scaled['scaleRatio']}** so với khẩu phần gốc {scaled['baseServings']} người):\n\n"
        + "\n".join(ing_lines)
        + f"\n\n🔥 **Năng lượng:** `{scaled['caloriesPerServing']} kcal/người` "
        f"(Tổng toàn bộ nồi {target_servings} người: **{scaled['totalCaloriesForServings']} kcal**)."
    )
    return {
        "intent": "portion_scale",
        "reply": reply,
        "recipes": [_format_recipe_card(target_recipe)],
        "scaledData": scaled,
        "suggestions": [
            f"Quy đổi {target_recipe['title']} cho 10 người",
            f"Các bước nấu {target_recipe['title']}",
            "Thêm nguyên liệu này vào danh sách đi chợ",
        ],
    }


# ============================================================
# 4. TRỢ LÝ ĐỨNG BẾP THEO NGỮ CẢNH MÓN ĐANG XEM (NHÓM 2)
# ============================================================

def _handle_recipe_context_question(
    message: str,
    msg_norm: str,
    all_recipes: List[Dict[str, Any]],
    current_recipe_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    mentioned = _find_mentioned_recipes(msg_norm, all_recipes)
    recipe = mentioned[0] if mentioned else None
    if not recipe and current_recipe_id:
        recipe = next((r for r in all_recipes if r["id"] == int(current_recipe_id)), None)

    if not recipe:
        return None

    steps = recipe.get("steps", [])
    step_match = re.search(r"buoc\s*(\d+)", msg_norm)
    if step_match and steps:
        step_num = int(step_match.group(1))
        found_step = next((s for s in steps if int(s.get("step", 0)) == step_num), None)
        if not found_step and 1 <= step_num <= len(steps):
            found_step = steps[step_num - 1]
        if found_step:
            return {
                "intent": "recipe_context",
                "reply": (
                    f"👩‍🍳 **Hướng dẫn chi tiết Bước {step_num} của món \"{recipe['title']}\":**\n\n"
                    f"> {found_step['description']}\n\n"
                    f"⏱️ *Mẹo nhỏ:* Hãy chuẩn bị sẵn nguyên liệu trên bàn bếp và giữ lửa ổn định ở bước này nhé!"
                ),
                "recipes": [_format_recipe_card(recipe)],
                "suggestions": [
                    f"Quy đổi {recipe['title']} cho 6 người",
                    f"Toàn bộ các bước làm {recipe['title']}",
                    "Món bị mặn thì chữa thế nào?",
                ],
            }

    # General breakdown of the active/mentioned recipe
    ing_summary = ", ".join(
        f"{i['name']} ({i['amount']} {i['unit']})" for i in recipe.get("ingredients", [])
    )
    step_lines = [
        f"**Bước {s.get('step', idx + 1)}:** {s.get('description', '')}"
        for idx, s in enumerate(steps)
    ]
    nut = recipe.get("nutrition") or {}
    reply = (
        f"🍲 **Tóm tắt nhanh công thức \"{recipe['title']}\"** ({recipe.get('difficulty', 'Dễ')} • "
        f"Chuẩn bị {recipe.get('prepTime', 15)}p + Nấu {recipe.get('cookTime', 25)}p • Khẩu phần {recipe.get('servings', 4)} người):\n\n"
        f"**1. Nguyên liệu chuẩn định lượng:**\n{ing_summary}\n\n"
        f"**2. Quy trình chế biến ({len(steps)} bước):**\n"
        + "\n".join(step_lines)
        + f"\n\n**3. Dinh dưỡng / khẩu phần:** `{recipe.get('calories', 350)} kcal` "
        f"(Đạm: {nut.get('protein', '15g')}, Béo: {nut.get('fat', '10g')}, Tinh bột: {nut.get('carbs', '40g')})."
    )
    return {
        "intent": "recipe_context",
        "reply": reply,
        "recipes": [_format_recipe_card(recipe)],
        "suggestions": [
            f"Quy đổi {recipe['title']} cho 8 người",
            "Gợi ý nguyên liệu thay thế",
            "Thêm món này vào danh sách đi chợ",
        ],
    }


# ============================================================
# 5 & 6. NGUYÊN LIỆU THAY THẾ & CẤP CỨU MÓN ĂN (NHÓM 2)
# ============================================================

def _handle_substitution(msg_norm: str) -> Optional[Dict[str, Any]]:
    has_sub_intent = any(
        w in msg_norm
        for w in ["thay", "het ", "khong co", "thieu", "an chay", "mam chay"]
    )
    if not has_sub_intent:
        return None
    for item in SUBSTITUTION_KNOWLEDGE:
        if any(_normalize(kw) in msg_norm for kw in item["keywords"]):
            bullets = "\n".join(f"- {s}" for s in item["substitutes"])
            return {
                "intent": "ingredient_substitution",
                "reply": (
                    f"🔄 **Gợi ý thay thế cho \"{item['ingredient']}\":**\n\n"
                    f"{bullets}\n\n"
                    f"💡 *Mẹo từ ChefBot: Khi thay thế gia vị, bạn nên cho khoảng 2/3 lượng dự kiến trước rồi nếm lại cho vừa khẩu vị gia đình nhé!*"
                ),
                "recipes": [],
                "suggestions": [
                    "Thay thế nước cốt dừa bằng gì?",
                    "Ăn chay thay nước mắm bằng gì?",
                    "Canh bị mặn quá chữa sao?",
                ],
            }
    if "thay the" in msg_norm or "thay bang gi" in msg_norm or "het " in msg_norm:
        overview = "\n".join(
            f"- **{it['ingredient']}:** {it['substitutes'][0]}"
            for it in SUBSTITUTION_KNOWLEDGE[:5]
        )
        return {
            "intent": "ingredient_substitution",
            "reply": (
                "🔄 **Bảng quy đổi & thay thế nguyên liệu thông dụng trong bếp Việt:**\n\n"
                + overview
                + "\n\n*Bạn đang thiếu nguyên liệu cụ thể nào? Hãy nhắn tên nguyên liệu cho ChefBot nhé!*"
            ),
            "recipes": [],
            "suggestions": [
                "Hết nước cốt dừa thay bằng gì?",
                "Thay bột năng bằng bột gì?",
                "Không có rượu nấu ăn khử mùi bằng gì?",
            ],
        }
    return None


def _handle_kitchen_rescue(msg_norm: str) -> Optional[Dict[str, Any]]:
    for item in KITCHEN_RESCUE_KNOWLEDGE:
        if any(_normalize(kw) in msg_norm for kw in item["keywords"]):
            bullets = "\n".join(f"- {s}" for s in item["solutions"])
            return {
                "intent": "kitchen_rescue",
                "reply": (
                    f"🆘 **Cấp cứu nhà bếp — Xử lý ngay lỗi: {item['problem']}**\n\n"
                    f"{bullets}"
                ),
                "recipes": [],
                "suggestions": [
                    "Cơm bị nhão hoặc khê làm sao?",
                    "Làm sao để nước phở trong veo?",
                    "Thịt bò bị dai xử lý thế nào?",
                ],
            }
    if "cap cuu" in msg_norm or "chua cháy" in msg_norm or "bi loi" in msg_norm:
        summary = "\n".join(
            f"- **{it['problem']}:** {it['solutions'][0]}"
            for it in KITCHEN_RESCUE_KNOWLEDGE[:4]
        )
        return {
            "intent": "kitchen_rescue",
            "reply": "🆘 **Cẩm nang Cấp cứu Món ăn tức thì của CookMate ChefBot:**\n\n" + summary,
            "recipes": [],
            "suggestions": [
                "Canh bị mặn quá chữa sao?",
                "Cơm bị nhão làm thế nào?",
                "Cá bị tanh khử mùi sao?",
            ],
        }
    return None


# ============================================================
# 7, 8, 9. TIỆN ÍCH THÔNG MINH & TẠO NHÁP CÔNG THỨC AI (NHÓM 3)
# ============================================================

def _handle_shopping_list(
    msg_norm: str,
    all_recipes: List[Dict[str, Any]],
    current_recipe_id: Optional[int] = None,
) -> Dict[str, Any]:
    mentioned = _find_mentioned_recipes(msg_norm, all_recipes)
    if not mentioned and current_recipe_id:
        r = next((x for x in all_recipes if x["id"] == int(current_recipe_id)), None)
        if r:
            mentioned = [r]
    if not mentioned:
        mentioned = all_recipes[:2]

    aggregated: Dict[str, Dict[str, Any]] = {}
    for r in mentioned:
        for ing in r.get("ingredients", []):
            key = f"{_normalize(ing['name'])}|{ing.get('unit', '').strip().lower()}"
            try:
                amt = float(str(ing.get("amount", 0)).replace(",", "."))
            except ValueError:
                amt = 0.0
            if key not in aggregated:
                aggregated[key] = {
                    "name": ing["name"],
                    "amount": amt,
                    "unit": ing.get("unit", ""),
                    "fromRecipes": [r["title"]],
                }
            else:
                aggregated[key]["amount"] += amt
                if r["title"] not in aggregated[key]["fromRecipes"]:
                    aggregated[key]["fromRecipes"].append(r["title"])

    items_list = list(aggregated.values())
    titles_str = ", ".join(f"**{r['title']}**" for r in mentioned)
    lines = [
        f"🛒 **Danh sách đi chợ tổng hợp cho {len(mentioned)} món ({titles_str}):**\n"
    ]
    shopping_items = []
    for idx, item in enumerate(items_list, 1):
        amt_val = int(item["amount"]) if item["amount"].is_integer() else round(item["amount"], 1)
        lines.append(f"- [ ] **{item['name']}:** `{amt_val} {item['unit']}`")
        shopping_items.append(
            {
                "name": item["name"],
                "amount": amt_val,
                "unit": item["unit"],
            }
        )

    lines.append("\n✨ *Danh sách đã được cộng gộp định lượng tự động. Bạn có thể bấm nút **Lưu vào Giỏ đi chợ** bên dưới!*")
    return {
        "intent": "shopping_list",
        "reply": "\n".join(lines),
        "recipes": [_format_recipe_card(r) for r in mentioned],
        "shoppingList": shopping_items,
        "suggestions": [
            "Thực đơn 3 bữa 1500 kcal",
            "Tạo nháp công thức mới bằng AI",
            "Gợi ý món ngày mưa",
        ],
    }


def _handle_ai_recipe_draft(message: str, msg_norm: str) -> Dict[str, Any]:
    chosen_draft = None
    for key, tpl in AI_RECIPE_TEMPLATES.items():
        if _normalize(key) in msg_norm:
            chosen_draft = dict(tpl)
            break

    if not chosen_draft:
        # Extract custom dish name if provided
        custom_title = message
        for prefix in [
            "tao nhap cong thuc",
            "viet cong thuc",
            "tao cong thuc",
            "up cong thuc",
            "mon ",
        ]:
            custom_title = re.sub(prefix, "", custom_title, flags=re.IGNORECASE).strip()
        if len(custom_title) < 4 or "nháp" in custom_title.lower() or "ai" in custom_title.lower():
            chosen_draft = dict(AI_RECIPE_TEMPLATES["sườn xào chua ngọt"])
        else:
            chosen_draft = dict(AI_RECIPE_TEMPLATES["gà nướng mật ong"])
            chosen_draft["title"] = custom_title[:1].upper() + custom_title[1:]

    ing_preview = "\n".join(
        f"- {i['name']}: `{i['amount']} {i['unit']}`" for i in chosen_draft["ingredients"]
    )
    step_preview = "\n".join(
        f"- **Bước {s['step']}:** {s['description']}" for s in chosen_draft["steps"]
    )
    reply = (
        f"✨ **ChefBot đã khởi tạo bản nháp công thức chuẩn định lượng: \"{chosen_draft['title']}\"**\n\n"
        f"- **Độ khó:** {chosen_draft['difficulty']} | **Chuẩn bị:** {chosen_draft['prepTime']}p | **Nấu:** {chosen_draft['cookTime']}p | **Khẩu phần:** {chosen_draft['servings']} người\n\n"
        f"**Nguyên liệu:**\n{ing_preview}\n\n"
        f"**Các bước chế biến:**\n{step_preview}\n\n"
        f"👉 Nhấn nút **\"Điền tự động vào Form Đăng Công Thức\"** bên dưới để mở trang đăng bài với toàn bộ dữ liệu đã điền sẵn!"
    )
    return {
        "intent": "recipe_draft",
        "reply": reply,
        "recipeDraft": chosen_draft,
        "recipes": [],
        "suggestions": [
            "Tạo công thức Sườn xào chua ngọt",
            "Tạo công thức Gà nướng mật ong",
            "Ước tính dinh dưỡng cho món này",
        ],
    }


def _handle_occasion_or_weather(
    msg_norm: str, all_recipes: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if "tu lanh" not in msg_norm and any(
        k in msg_norm for k in ["troi mua", "ngay mua", "troi lanh", "se lanh", "am bung", "mua dong"]
    ):
        picks = [r for r in all_recipes if r.get("categoryId") in (2, 3, 5)] or all_recipes[:3]
        return {
            "intent": "occasion_weather",
            "reply": (
                "🌧️ **Trời mưa se lạnh thì những món kho đậm đà hoặc bún/phở nóng hổi là tuyệt nhất!** "
                "ChefBot gợi ý cho bạn 3 món cực kỳ ấm bụng:"
            ),
            "recipes": [_format_recipe_card(r) for r in picks[:3]],
            "suggestions": [
                "Quy đổi Phở bò Hà Nội cho 6 người",
                "Món nấu nhanh dưới 20 phút",
                "Mâm cỗ Tết truyền thống",
            ],
        }
    if any(k in msg_norm for k in ["nhanh", "20 phut", "15 phut", "30 phut", "ban ron"]):
        quick = sorted(all_recipes, key=lambda r: int(r.get("totalTime", 45)))[:3]
        return {
            "intent": "occasion_weather",
            "reply": "⚡ **Top 3 món ngon siêu tốc (tổng thời gian chuẩn bị + nấu nhanh nhất) cho ngày bận rộn:**",
            "recipes": [_format_recipe_card(r) for r in quick],
            "suggestions": [
                "Tủ lạnh có trứng gà, cà chua",
                "Thực đơn dưới 400 kcal",
                "Tạo danh sách đi chợ",
            ],
        }
    if any(k in msg_norm for k in ["tet", "co truyen", "mam co", "ram", "chay", "cuoi tuan"]):
        holiday_recipes = [r for r in all_recipes if r.get("holiday")] or all_recipes[:3]
        if "chay" in msg_norm or "ram" in msg_norm:
            holiday_recipes = [
                r for r in all_recipes if r.get("categoryId") == 6 or "chay" in _normalize(r["title"])
            ] or holiday_recipes
        return {
            "intent": "occasion_weather",
            "reply": "🏮 **Gợi ý thực đơn đặc sắc theo Dịp lễ & Sum họp gia đình trên CookMate:**",
            "recipes": [_format_recipe_card(r) for r in holiday_recipes[:3]],
            "suggestions": [
                "Lập danh sách đi chợ cho mâm cỗ",
                "Quy đổi khẩu phần cho 10 người",
                "Gợi ý món tráng miệng",
            ],
        }
    return None


# ============================================================
# MAIN CHATBOT ROUTER (HYBRID RAG + OPTIONAL GEMINI API)
# ============================================================

def generate_chatbot_response(
    message: str,
    context: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xử lý câu hỏi của người dùng và trả về phản hồi thông minh kèm thẻ món ăn,
    bảng quy đổi khẩu phần, danh sách đi chợ hoặc bản nháp công thức AI.
    """
    context = context or {}
    raw_msg = (message or "").strip()
    msg_norm = _normalize(raw_msg)
    current_recipe_id = context.get("recipeId")

    all_recipes = db.get_all_recipes(status="approved", db_path=db_path)
    all_ingredients = db.get_all_ingredients(db_path=db_path)

    if not raw_msg:
        return {
            "intent": "greeting",
            "reply": (
                "Xin chào! Mình là **CookMate ChefBot — Trợ lý Đầu bếp AI** 👨‍🍳.\n"
                "Mình có thể giúp bạn:\n"
                "1. 🧊 **Tìm món từ tủ lạnh** (nhập các nguyên liệu bạn đang có)\n"
                "2. 🥗 **Tư vấn thực đơn theo Calo & Dinh dưỡng** (VD: *dưới 400 kcal*, *thực đơn 3 bữa 1500 kcal*)\n"
                "3. ⚖️ **Quy đổi khẩu phần tức thì** (VD: *Phở bò cho 8 người*)\n"
                "4. 🆘 **Cấp cứu món ăn & Thay thế nguyên liệu** (VD: *canh bị mặn*, *hết nước cốt dừa*)\n"
                "5. 🛒 **Gộp danh sách đi chợ & Viết nháp công thức AI**"
            ),
            "recipes": [_format_recipe_card(r) for r in all_recipes[:2]],
            "suggestions": [
                "Tủ lạnh có thịt bò, trứng gà, cà chua",
                "Lên thực đơn 3 bữa 1500 kcal",
                "Phở bò Hà Nội cho 8 người",
                "Canh bị mặn quá chữa sao?",
            ],
        }

    # 1. Check AI Recipe Draft Generator (Nhóm 3 - #9)
    if any(
        kw in msg_norm
        for kw in ["tao nhap", "viet cong thuc", "tao cong thuc", "nhap cong thuc", "ai recipe"]
    ):
        return _handle_ai_recipe_draft(raw_msg, msg_norm)

    # 2. Check Shopping List Generator (Nhóm 3 - #8)
    if any(kw in msg_norm for kw in ["di cho", "shopping", "danh sach mua", "mua nguyen lieu"]):
        return _handle_shopping_list(msg_norm, all_recipes, current_recipe_id=current_recipe_id)

    # 3. Check Kitchen Rescue (Nhóm 2 - #6)
    rescue = _handle_kitchen_rescue(msg_norm)
    if rescue:
        return rescue

    # 4. Check Ingredient Substitution (Nhóm 2 - #5)
    sub = _handle_substitution(msg_norm)
    if sub:
        return sub

    # 5. Check Portion Scaling (Nhóm 1 - #3)
    if any(kw in msg_norm for kw in ["quy doi", "khau phan", "nguoi an", "cho ", "suat"]):
        scaled_resp = _handle_portion_scaling(
            raw_msg, msg_norm, all_recipes, current_recipe_id=current_recipe_id
        )
        if scaled_resp:
            return scaled_resp

    # 6. Check Nutrition & Calorie Planning (Nhóm 1 - #2)
    if any(
        kw in msg_norm
        for kw in [
            "calo",
            "kcal",
            "giam can",
            "eat clean",
            "dinh duong",
            "protein",
            "giau dam",
            "thuc don",
            "3 bua",
            "it beo",
        ]
    ):
        return _handle_nutrition_query(raw_msg, msg_norm, all_recipes)

    # 7. Check Weather / Holiday / Quick Meal (Nhóm 3 - #7)
    occ = _handle_occasion_or_weather(msg_norm, all_recipes)
    if occ:
        return occ

    # 8. Check Fridge Ingredient Matching (Nhóm 1 - #1)
    fridge = _handle_fridge_search(raw_msg, msg_norm, all_recipes, all_ingredients)
    if fridge:
        return fridge

    # 9. Check Context-Aware Recipe Question (Nhóm 2 - #4)
    ctx_resp = _handle_recipe_context_question(
        raw_msg, msg_norm, all_recipes, current_recipe_id=current_recipe_id
    )
    if ctx_resp:
        return ctx_resp

    # 10. Default helpful overview with top featured recipes
    featured = [r for r in all_recipes if r.get("featured")] or all_recipes[:3]
    return {
        "intent": "general_recommend",
        "reply": (
            "👨‍🍳 **ChefBot gợi ý cho bạn các công thức nổi bật nhất hôm nay trên CookMate!**\n\n"
            "Bạn có thể hỏi cụ thể hơn như:\n"
            "- *\"Nhà còn thịt heo, trứng, cà chua thì nấu gì?\"*\n"
            "- *\"Gợi ý thực đơn 3 bữa 1500 kcal\"*\n"
            "- *\"Phở bò Hà Nội nấu cho 8 người cần bao nhiêu nguyên liệu?\"*\n"
            "- *\"Canh bị mặn quá chữa sao?\"* hoặc *\"Tạo nháp công thức Sườn xào chua ngọt\"*"
        ),
        "recipes": [_format_recipe_card(r) for r in featured[:3]],
        "suggestions": [
            "Tủ lạnh có thịt bò, cà chua, trứng",
            "Thực đơn 3 bữa 1500 kcal",
            "Phở bò Hà Nội cho 8 người",
            "Tạo nháp công thức Sườn xào chua ngọt",
        ],
    }
