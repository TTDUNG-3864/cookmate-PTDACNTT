# -*- coding: utf-8 -*-
"""
CookMate ChefBot — Trợ Lý AI Chuyên Biệt Về Món Ăn & Kỹ Thuật Nấu Nướng
=======================================================================
Chỉ tập trung giải đáp chuyên sâu về ẩm thực & món ăn, tích hợp Nhóm 1 & Nhóm 2:

Nhóm 1 — Giải đáp Món ăn, Nguyên liệu sẵn có, Định lượng & Dinh dưỡng (CSDL CookMate):
  1. "Có những nguyên liệu này thì nấu được món gì?" (Đối chiếu nguyên liệu tủ lạnh với CSDL)
  2. Tư vấn món ăn & thực đơn theo Calo, Đạm (Protein), Chất béo, Tinh bột, Chất xơ (UC06-B)
  3. Tính toán & quy đổi định lượng nguyên liệu theo số người ăn (UC06-A)

Nhóm 2 — Trợ lý Đứng bếp, Xử lý sự cố món ăn & Thay thế nguyên liệu:
  4. Xử lý sự cố khi nấu ăn ("Cấp cứu món ăn": món bị cháy/khê, mặn, nhão, sống, đục nước, dai, tanh, cay, chua, dính chảo...)
  5. Tư vấn thay thế nguyên liệu khi thiếu đồ kèm tỷ lệ quy đổi chuẩn
  6. Giải đáp chi tiết cách nấu, các bước thực hiện và bí quyết theo món ăn đang xem

Từ chối lịch sự mọi câu hỏi ngoài phạm vi ẩm thực / nấu ăn.
"""

import re
from typing import Any, Dict, List, Optional

from backend import database as db


# ============================================================
# DANH MỤC TỪ KHÓA NGOÀI PHẠM VI ẨM THỰC (OFF-TOPIC GUARDRAIL)
# ============================================================

OFF_TOPIC_KEYWORDS = [
    "lap trinh",
    "code python",
    "javascript",
    "html",
    "css",
    "toan hoc",
    "giai phuong trinh",
    "dao ham",
    "tich phan",
    "chinh tri",
    "bau cu",
    "chung khoan",
    "bitcoin",
    "crypto",
    "bong da",
    "world cup",
    "ngoai hang anh",
    "viet bai van",
    "lam tho",
    "dich tieng anh",
    "cai win",
    "sua may tinh",
]


# ============================================================
# CƠ SỞ TRI THỨC: THAY THẾ NGUYÊN LIỆU KHI THIẾU (NHÓM 2)
# ============================================================

SUBSTITUTION_KNOWLEDGE = [
    {
        "keywords": ["nước cốt dừa", "nuoc cot dua", "cốt dừa", "cot dua"],
        "ingredient": "Nước cốt dừa",
        "substitutes": [
            "**Sữa tươi không đường + Bơ lạt (Khuyên dùng):** Pha `200ml sữa tươi không đường` với `15g bơ lạt` đun chảy — tạo độ béo ngậy và sánh đạt 85–90% so với cốt dừa tươi, rất hợp cho món cà ri, kho, bánh.",
            "**Sữa đặc + Sữa tươi:** Pha `180ml sữa tươi + 2 muỗng canh sữa đặc` khi nấu các món chè hoặc tráng miệng.",
            "**Kem tươi (Whipping Cream / Cooking Cream):** Thay thế theo tỷ lệ `1:1` cho các món súp, sốt kem hoặc cà ri.",
        ],
    },
    {
        "keywords": ["nước mắm", "nuoc mam", "mắm chay", "mam chay"],
        "ingredient": "Nước mắm (hoặc khi ăn chay)",
        "substitutes": [
            "**Nước tương (Xì dầu) + Muối biển:** Thay `1 muỗng canh nước mắm` bằng `1 muỗng canh nước tương + 1/4 muỗng cà phê muối` để giữ độ mặn đằm mà không bị nhạt.",
            "**Nước mắm chay từ dứa (thơm) hoặc nấm:** Dùng tỷ lệ `1:1` cho các món kho, chấm hoặc canh chay.",
            "**Muối + Bột nêm nấm hương:** Dùng khi nấu nước dùng canh/phở để nước trong và không bị sẫm màu.",
        ],
    },
    {
        "keywords": ["bột năng", "bot nang", "bột bắp", "bot bap", "bột sắn", "bot san", "tạo sánh", "tao sanh"],
        "ingredient": "Bột năng / Bột bắp (Tạo độ sánh)",
        "substitutes": [
            "**Bột bắp ↔ Bột năng:** Thay thế trực tiếp tỷ lệ `1:1` (hoà tan với chút nước lạnh trước khi đổ từ từ vào nồi đang sôi).",
            "**Bột sắn dây:** Thay tỷ lệ `1:1`, cực kỳ hợp cho các món chè và súp cần độ trong mát.",
            "**Bột mì đa dụng:** Dùng lượng gấp đôi (`2 muỗng bột mì = 1 muỗng bột năng`), thích hợp làm sánh sốt các món xào/âu.",
        ],
    },
    {
        "keywords": ["rượu nấu ăn", "ruou nau an", "rượu trắng", "ruou trang", "rượu mirin", "mirin"],
        "ingredient": "Rượu nấu ăn / Rượu trắng khử mùi",
        "substitutes": [
            "**Gừng tươi đập dập + Giấm gạo:** Chà xát hoặc cho vào nước chần thịt/cá theo tỷ lệ `1 nhánh gừng + 1 muỗng canh giấm` giúp khử sạch mùi hôi tanh.",
            "**Nước cốt chanh + Muối hạt:** Rất hiệu quả khi sơ chế gà, vịt, hải sản và lòng.",
            "**Nước ép táo + 1/2 muỗng cà phê đường:** Thay thế cho rượu ngọt Mirin trong các món sốt Teriyaki hoặc kho.",
        ],
    },
    {
        "keywords": ["đường phèn", "duong phen", "đường nâu", "duong nau", "đường thốt nốt", "duong thot not", "mật ong", "mat ong"],
        "ingredient": "Đường phèn / Đường nâu / Mật ong",
        "substitutes": [
            "**Thay Đường phèn bằng Đường cát trắng:** Dùng tỷ lệ `100g đường phèn = 90g đường cát trắng` (vì đường cát ngọt đậm hơn).",
            "**Thay Đường nâu bằng Đường trắng + Mật mía/Mật ong:** Trộn `1 muỗng canh đường trắng + 1/2 muỗng cà phê mật ong` cho các món ướp nướng.",
            "**Thay Mật ong khi ướp nướng:** Dùng `nước đường thắng nhẹ` hoặc `sữa đặc` giúp thịt nướng vẫn mềm và lên màu vàng óng.",
        ],
    },
    {
        "keywords": ["chanh", "giấm", "giam", "me chua", "quất", "tắc", "chất chua"],
        "ingredient": "Chanh / Giấm / Me chua",
        "substitutes": [
            "**Chanh ↔ Quất (Tắc):** `2 quả tắc = 1 quả chanh vừa`, mùi tinh dầu tắc rất hợp khi pha nước chấm hoặc bún/phở.",
            "**Chanh ↔ Giấm gạo / Giấm táo:** `1 muỗng canh giấm = 1 muỗng canh nước cốt chanh`.",
            "**Thay Me chua khi nấu canh chua:** Dùng **dứa (thơm) chín**, **cà chua**, **khế chua** hoặc **sấu/dọc mùng** tạo vị chua thanh tự nhiên.",
        ],
    },
    {
        "keywords": ["dầu hào", "dau hao", "bơ lạt", "bo lat"],
        "ingredient": "Dầu hào / Bơ lạt",
        "substitutes": [
            "**Thay 1 muỗng canh Dầu hào:** Pha `1 muỗng canh nước tương + 1/2 muỗng cà phê đường + 1/4 muỗng cà phê bột năng`.",
            "**Thay Bơ lạt:** Dùng `Dầu ô-liu` hoặc `Dầu thực vật` theo tỷ lệ `10g bơ = 8ml dầu ăn`.",
        ],
    },
    {
        "keywords": ["hành tím", "hanh tim", "hành khô", "hanh kho", "tỏi", "toi", "hành tây", "hanh tay"],
        "ingredient": "Hành tím / Tỏi / Hành tây",
        "substitutes": [
            "**Thay Hành tím (Hành khô):** Dùng **phần đầu trắng của hành lá** hoặc **hành tây băm nhỏ** (phi thơm tương tự hành tím).",
            "**Thay Hành tây:** Dùng **cần tây**, **tỏi tây (hành boa-rô)** hoặc **củ cải trắng** (nếu hầm lấy nước ngọt).",
        ],
    },
    {
        "keywords": ["sữa tươi", "sua tuoi", "kem tươi", "whipping cream", "sữa đặc", "sua dac"],
        "ingredient": "Sữa tươi / Kem tươi (Whipping Cream)",
        "substitutes": [
            "**Thay Kem tươi (Whipping Cream) trong súp/sốt:** Pha `160ml sữa tươi không đường + 40g bơ lạt đun chảy + 1 muỗng cà phê bột mì`.",
            "**Thay Sữa tươi:** Pha loãng `sữa đặc với nước ấm theo tỷ lệ 1:4` (nhớ giảm bớt lượng đường trong công thức).",
        ],
    },
    {
        "keywords": ["màu điều", "mau dieu", "nước hàng", "nuoc hang", "nước màu", "bột nghệ", "bot nghe"],
        "ingredient": "Nước màu (Nước hàng) / Dầu màu điều / Bột nghệ",
        "substitutes": [
            "**Thay Nước màu kho thịt/cá:** Tự thắng nhanh `2 muỗng canh đường + 1 muỗng canh nước` trên chảo đến khi chuyển màu cánh gián, hoặc dùng `nước tương đen (hắc xì dầu)`.",
            "**Thay Dầu màu điều:** Phi thơm `gấc chín`, `bột ớt Paprika` hoặc `cà chua băm nhuyễn` với dầu ăn để lấy màu đỏ cam tự nhiên.",
        ],
    },
    {
        "keywords": ["trứng gà", "trung ga", "trứng", "trung"],
        "ingredient": "Trứng gà (trong tẩm bột / làm bánh / kết dính)",
        "substitutes": [
            "**Khi trộn chả / mọc cần độ kết dính:** Thay 1 quả trứng bằng `1 muỗng canh bột năng` hoặc `bột bắp`.",
            "**Khi chiên tẩm bột:** Pha bột chiên giòn với `nước cốt dừa` hoặc `bia lạnh` giúp vỏ giòn rụm vàng ươm không cần trứng.",
        ],
    },
]


# ============================================================
# CƠ SỞ TRI THỨC: XỬ LÝ SỰ CỐ MÓN ĂN ("CẤP CỨU NHÀ BẾP" - NHÓM 2)
# ============================================================

KITCHEN_RESCUE_KNOWLEDGE = [
    {
        "keywords": [
            "bị cháy",
            "bi chay",
            "cháy nồi",
            "chay noi",
            "cháy khét",
            "chay khet",
            "bị khét",
            "bi khet",
            "bị khê",
            "bi khe",
            "cơm khê",
            "com khe",
            "kho bị cháy",
        ],
        "problem": "Món ăn / Nồi kho / Cơm bị cháy hoặc có mùi khê khét",
        "solutions": [
            "**Bước 1 — Tắt bếp ngay & TUYỆT ĐỐI KHÔNG ĐẢO/KHUẤY:** Đừng cạo hay đảo đáy nồi vì sẽ làm phần cháy đen và vị đắng lan ra toàn bộ món ăn.",
            "**Bước 2 — Gắp phần chưa cháy sang nồi sạch mới:** Nhẹ nhàng múc phần thịt/cá/thức ăn ở lớp trên (chưa bị bén lửa) sang một chiếc nồi mới.",
            "**Bước 3 — Khử mùi khê khét tức thì:**\n"
            "  • *Với cơm bị khê:* Đặt ngay **1–2 lát bánh mì sandwich**, hoặc **1 bát nhỏ nước lạnh**, hoặc **vài gốc hành lá tươi** lên mặt cơm rồi đậy nắp 5–10 phút — mùi khê sẽ bị hút sạch.\n"
            "  • *Với món thịt/cá kho bị cháy sốt:* Bỏ phần nước sốt cũ bị khét, pha lại nước sốt mới (nước dừa tươi/nước lọc + chút nước mắm + đường + vài lát gừng/hành tím) đun liu riu 5 phút để lấy lại hương thơm.",
            "**Bước 4 — Mẹo cọ nồi bị cháy không tốn sức:** Đổ nước ngập đáy nồi cháy, cho `2 muỗng canh muối nở (Baking Soda) + 3 muỗng giấm trắng` (hoặc vài lát chanh), đun sôi 5 phút rồi ngâm 20 phút, mảng cháy sẽ tự bong ra dễ dàng!",
        ],
    },
    {
        "keywords": ["bị mặn", "bi man", "mặn quá", "man qua", "chữa mặn", "chua man", "quá mặn"],
        "problem": "Món canh / Món kho / Món xào bị mặn quá",
        "solutions": [
            "**Mẹo khoai tây sống (Hiệu quả nhất):** Gọt vỏ `1 củ khoai tây sống`, cắt lát dày khoảng 1cm thả vào nồi canh hoặc nồi kho, đun nhỏ lửa 10 phút rồi vớt ra — khoai tây sẽ hút lượng muối thừa cực nhạy mà không làm đổi vị món ăn!",
            "**Với món canh/súp:** Châm thêm nước sôi, thả thêm **cà chua**, **đậu hũ non** hoặc **nấm/rau củ** để giãn độ mặn; có thể vắt vài giọt cốt chanh (vị chua dịu làm giảm cảm giác mặn ở đầu lưỡi).",
            "**Với món thịt/cá kho:** Thêm `nước dừa tươi` (hoặc nước lọc) + `1 muỗng cà phê đường phèn/mật ong` đun lại cho cân bằng vị mặn – ngọt.",
        ],
    },
    {
        "keywords": ["bị nhão", "bi nhao", "cơm nhão", "com nhao", "cơm sống", "com song", "cơm sượng", "com suong"],
        "problem": "Cơm bị nhão (ướt) hoặc bị sống / sượng",
        "solutions": [
            "**Xử lý cơm bị nhão:** Mở nắp nồi để thoát bớt hơi nước, đặt **1–2 lát bánh mì ruột trắng** lên trên mặt cơm, đậy nắp ở chế độ `Warm` 10 phút — bánh mì sẽ hút hết nước thừa giúp hạt cơm ráo tơi.",
            "**Xử lý cơm bị sống / sượng:** Xới tơi cơm sang nồi khác hoặc tạo các lỗ thoáng trên mặt cơm, rưới đều `2–3 muỗng canh nước ấm pha 1 muỗng cà phê rượu trắng` theo tỷ lệ 1:10 rồi bấm nút `Cook` lại. Rượu sẽ bay hơi hết và giúp cơm chín mềm đều.",
        ],
    },
    {
        "keywords": ["bị đục", "bi duc", "nước dùng đục", "nuoc pho duc", "nước lèo đục", "nuoc dung duc"],
        "problem": "Nước dùng Phở / Bún / Canh hầm xương bị đục",
        "solutions": [
            "**Tuyệt chiêu lòng trắng trứng gà:** Đánh tan `1 lòng trắng trứng gà` với chút nước nguội, đổ vào nồi nước dùng đang ấm rồi khuấy đều. Khi nước sôi lăn tăn, lòng trắng đông tụ sẽ cuốn theo toàn bộ cặn đục nổi lên mặt — chỉ cần vớt bỏ hoặc lọc qua rây là nước dùng trong veo!",
            "**Thả vài lát khoai tây sống hoặc củ cải trắng:** Giúp hút bọt cặn và tăng độ ngọt thanh.",
            "**Nguyên tắc phòng tránh:** Luôn chần xương với nước sôi + gừng + muối trong 3 phút đầu, rửa sạch máu bầm rồi mới ninh lửa nhỏ và **mở hé nắp nồi**.",
        ],
    },
    {
        "keywords": ["bị dai", "bi dai", "thịt dai", "thit bo dai", "thịt cứng", "thit cung", "lâu mềm"],
        "problem": "Thịt bò / Thịt hầm bị dai hoặc khô cứng",
        "solutions": [
            "**Khi đang hầm trên bếp:** Cho vào nồi `vài lát dứa (thơm) chín`, `1 miếng đu đủ xanh nhỏ` hoặc `1 muỗng cà phê nước cốt chanh` — enzyme tự nhiên (Bromelain/Papain) sẽ phá vỡ sợi cơ cứng giúp thịt mềm nhanh gấp đôi.",
            "**Bí quyết ướp thịt bò xào không bị dai:** Cắt ngang thớ, ướp với `1 muỗng dầu ăn + 1/2 muỗng bột bắp + tỏi gừng`; chỉ nêm nước mắm/muối khi xào trên lửa thật lớn gần chín tới.",
        ],
    },
    {
        "keywords": ["bị tanh", "bi tanh", "cá tanh", "ca tanh", "hải sản tanh", "khu mui tanh", "bị hôi", "thịt hôi"],
        "problem": "Cá, Hải sản hoặc Thịt bị tanh / hôi",
        "solutions": [
            "**Khi sơ chế cá/hải sản:** Ngâm rửa với **nước vo gạo**, hoặc chà xát **muối hạt + gừng đập dập + rượu trắng/chanh**, đặc biệt phải cạo sạch lớp màng đen trong bụng cá và máu dọc xương sống.",
            "**Khi món đang nấu bị tanh:** Cho thêm `gừng thái chỉ`, `sả đập dập`, `thì là`, `vài múi cà chua/dứa` hoặc `2 muỗng canh nước chè xanh đặc` vào nồi kho/canh.",
        ],
    },
    {
        "keywords": ["cay quá", "cay qua", "quá cay", "bị cay", "chua quá", "chua qua", "bị chua", "quá chua", "ngọt quá", "quá ngọt"],
        "problem": "Món ăn bị quá cay, quá chua hoặc quá ngọt",
        "solutions": [
            "**Chữa món quá cay:** Thêm `nước cốt dừa`, `sữa tươi không đường`, `một ít đường` hoặc `cà chua` — chất béo trong sữa/cốt dừa hòa tan hoạt chất cay Capsaicin ngay lập tức.",
            "**Chữa món quá chua:** Thêm `1/2 – 1 muỗng cà phê đường phèn` hoặc `một nhúm rất nhỏ muối nở (Baking Soda)` để trung hòa axit chua.",
            "**Chữa món quá ngọt:** Thêm `vài giọt nước cốt chanh / giấm táo` và một chút nước mắm để cân bằng lại hậu vị.",
        ],
    },
    {
        "keywords": ["dính chảo", "dinh chao", "bắn dầu", "ban dau", "rã nát", "chiên cá", "chien ca", "rau bị đen", "rau bị vàng"],
        "problem": "Chiên cá bị dính chảo/bắn dầu hoặc Rau luộc bị vàng úa",
        "solutions": [
            "**Chiên cá/đậu không dính chảo & không bắn dầu:** Thấm thật khô thực phẩm bằng giấy bếp; làm nóng chảo trước rồi mới cho dầu, rắc vào dầu **1/4 muỗng cà phê bột mì hoặc vài hạt muối** và xát 1 lát gừng tươi lên mặt chảo trước khi thả cá.",
            "**Giữ rau luộc xanh mướt không bị thâm:** Nước phải thật sôi mới thả rau, thêm `1/2 muỗng cà phê muối + vài giọt dầu ăn`, luộc mở nắp trên lửa lớn rồi vớt ra đĩa thoáng (không đậy lồng bàn khi còn bốc khói).",
        ],
    },
]


# ============================================================
# CÁC HÀM TIỆN ÍCH CHUẨN HÓA & ĐỊNH DẠNG
# ============================================================

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
    }


def _find_mentioned_recipes(msg_norm: str, all_recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matched = []
    for r in all_recipes:
        title_norm = _normalize(r["title"])
        if title_norm and title_norm in msg_norm:
            matched.append(r)
            continue
        words = [w for w in title_norm.split() if len(w) >= 2]
        if len(words) >= 2:
            short_title = " ".join(words[:2])
            if len(short_title) >= 5 and short_title in msg_norm:
                matched.append(r)
    return matched


def _is_off_topic(msg_norm: str) -> bool:
    return any(kw in msg_norm for kw in OFF_TOPIC_KEYWORDS)


# ============================================================
# NHÓM 1.1: TỦ LẠNH CÓ GÌ? — GỢI Ý MÓN TỪ NGUYÊN LIỆU SẴN CÓ
# ============================================================

def _handle_fridge_search(
    message: str, msg_norm: str, all_recipes: List[Dict[str, Any]], all_ingredients: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    detected_ing_names: List[str] = []
    for ing in all_ingredients:
        ing_norm = _normalize(ing["name"])
        if ing_norm and re.search(r"\b" + re.escape(ing_norm) + r"\b", msg_norm):
            detected_ing_names.append(ing["name"])

    # Từ điển đồng nghĩa nguyên liệu tiếng Việt mở rộng
    synonym_keywords = {
        "thit bo": "Thịt bò",
        "bo": "Thịt bò",
        "thit heo": "Thịt heo",
        "thit lon": "Thịt heo",
        "ba chi": "Thịt ba chỉ",
        "suon": "Sườn heo",
        "thit ga": "Thịt gà",
        "uc ga": "Thịt gà",
        "trung": "Trứng gà",
        "trung ga": "Trứng gà",
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
        "bap cai": "Bắp cải",
        "rau muong": "Rau muống",
        "bun": "Bún tươi",
        "banh pho": "Bánh phở",
        "com": "Gạo / Cơm",
        "gao": "Gạo",
        "nuoc cot dua": "Nước cốt dừa",
    }
    for kw, label in synonym_keywords.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", msg_norm):
            if not any(_normalize(label) in _normalize(x) or _normalize(x) in _normalize(label) for x in detected_ing_names):
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
        f"🧊 **Với nguyên liệu bạn đang có ({', '.join(detected_ing_names)})**, bạn có thể nấu ngay **{len(scored_recipes)} món ngon** sau đây:\n"
    ]
    cards = []
    for idx, (match_cnt, ratio, r, have_l, miss_l) in enumerate(top, 1):
        miss_preview = ", ".join(miss_l[:4]) + ("..." if len(miss_l) > 4 else "")
        status_note = (
            "✅ **Đã đủ nguyên liệu chính!**"
            if not miss_l
            else f"🧂 *Cần thêm gia vị / nguyên liệu phụ:* {miss_preview}"
        )
        lines.append(
            f"{idx}. **{r['title']}** (`{r.get('calories', 350)} kcal` • {r.get('totalTime', 30)} phút • Độ khó: {r.get('difficulty', 'Dễ')})\n"
            f"   - Nguyên liệu khớp (**{match_cnt}/{len(r.get('ingredients', []))}**): *{', '.join(have_l)}*\n"
            f"   - {status_note}"
        )
        cards.append(_format_recipe_card(r))

    lines.append("\n👉 *Nhấn vào thẻ món ăn bên dưới để xem định lượng chi tiết và các bước chế biến!*")
    return {
        "intent": "fridge_match",
        "reply": "\n".join(lines),
        "recipes": cards,
        "suggestions": [
            f"Quy đổi {top[0][2]['title']} cho 6 người",
            f"Cách nấu {top[0][2]['title']}",
            "Món ăn bị cháy hoặc mặn xử lý sao?",
        ],
    }


# ============================================================
# NHÓM 1.2: TƯ VẤN MÓN ĂN THEO CALO & DINH DƯỠNG (UC06-B)
# ============================================================

def _handle_nutrition_query(
    message: str, msg_norm: str, all_recipes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    cal_match = re.search(r"(\d{3,4})\s*(?:kcal|calo|cal)", msg_norm)
    target_cal = int(cal_match.group(1)) if cal_match else None

    if "thuc don" in msg_norm or "3 bua" in msg_norm or (target_cal and target_cal >= 1000):
        daily_budget = target_cal or 1500
        breakfasts = [r for r in all_recipes if r.get("categoryId") in (1, 2, 7)] or all_recipes[:3]
        mains = [r for r in all_recipes if r.get("categoryId") in (3, 4)] or all_recipes[3:6]
        soups = [r for r in all_recipes if r.get("categoryId") in (5, 6)] or all_recipes[6:9]

        b_dish = min(breakfasts, key=lambda r: abs(int(r.get("calories", 350)) - daily_budget * 0.3))
        m_dish = min(mains, key=lambda r: abs(int(r.get("calories", 450)) - daily_budget * 0.4))
        s_dish = min(soups, key=lambda r: abs(int(r.get("calories", 250)) - daily_budget * 0.3))

        chosen = [b_dish, m_dish, s_dish]
        total_c = sum(int(r.get("calories", 350)) for r in chosen)
        reply = (
            f"🥗 **Gợi ý Thực đơn 3 bữa cân bằng dinh dưỡng (~{daily_budget} kcal/ngày):**\n\n"
            f"- 🌅 **Bữa sáng:** **{b_dish['title']}** — `{b_dish.get('calories')} kcal` (Đạm: {b_dish.get('nutrition', {}).get('protein', '15g')})\n"
            f"- ☀️ **Bữa trưa:** **{m_dish['title']}** — `{m_dish.get('calories')} kcal` (Đạm: {m_dish.get('nutrition', {}).get('protein', '22g')})\n"
            f"- 🌙 **Bữa tối thanh đạm:** **{s_dish['title']}** — `{s_dish.get('calories')} kcal` (Chất xơ: {s_dish.get('nutrition', {}).get('fiber', '4g')})\n\n"
            f"🔥 **Tổng năng lượng 3 bữa:** **{total_c} kcal / người**."
        )
        return {
            "intent": "nutrition_plan",
            "reply": reply,
            "recipes": [_format_recipe_card(r) for r in chosen],
            "suggestions": [
                "Món ăn dưới 350 kcal giảm cân",
                "Món giàu Protein tăng cơ",
                "Có ức gà, trứng, cà chua nấu món gì?",
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
            "suggestions": ["Thực đơn 3 bữa 1500 kcal", "Món ăn dưới 350 kcal", "Thịt bò bị dai xử lý sao?"],
        }

    low_cal = [r for r in all_recipes if int(r.get("calories", 350)) <= max_cal]
    if not low_cal:
        low_cal = sorted(all_recipes, key=lambda r: int(r.get("calories", 350)))[:3]
    else:
        low_cal = sorted(low_cal, key=lambda r: int(r.get("calories", 350)))[:3]

    lines = [
        f"🌿 **Các món ngon thanh đạm dưới {max_cal} kcal/khẩu phần (phù hợp Eat Clean & giảm cân):**\n"
    ]
    for idx, r in enumerate(low_cal, 1):
        nut = r.get("nutrition") or {}
        lines.append(
            f"{idx}. **{r['title']}** — `{r.get('calories')} kcal` | Đạm: {nut.get('protein', '12g')} | Chất xơ: {nut.get('fiber', '3g')} ({r.get('totalTime', 25)} phút)"
        )
    return {
        "intent": "nutrition_plan",
        "reply": "\n".join(lines),
        "recipes": [_format_recipe_card(r) for r in low_cal],
        "suggestions": [
            "Lên thực đơn 3 bữa 1500 kcal",
            "Món giàu Protein tăng cơ",
            "Thiếu nước cốt dừa thay bằng gì?",
        ],
    }


# ============================================================
# NHÓM 1.3: TÍNH TOÁN & QUY ĐỔI KHẨU PHẦN ĂN (UC06-A)
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
        f"(Tổng toàn nồi {target_servings} người: **{scaled['totalCaloriesForServings']} kcal**)."
    )
    return {
        "intent": "portion_scale",
        "reply": reply,
        "recipes": [_format_recipe_card(target_recipe)],
        "scaledData": scaled,
        "suggestions": [
            f"Cách nấu {target_recipe['title']}",
            f"Quy đổi {target_recipe['title']} cho 10 người",
            "Khi nấu món ăn bị cháy xử lý thế nào?",
        ],
    }


# ============================================================
# NHÓM 2.1 & 2.2: CẤP CỨU MÓN ĂN & THAY THẾ NGUYÊN LIỆU
# ============================================================

def _handle_kitchen_rescue(msg_norm: str) -> Optional[Dict[str, Any]]:
    for item in KITCHEN_RESCUE_KNOWLEDGE:
        if any(_normalize(kw) in msg_norm for kw in item["keywords"]):
            bullets = "\n".join(f"- {s}" for s in item["solutions"])
            return {
                "intent": "kitchen_rescue",
                "reply": (
                    f"🆘 **Xử lý sự cố món ăn — {item['problem']}:**\n\n"
                    f"{bullets}"
                ),
                "recipes": [],
                "suggestions": [
                    "Khi làm món ăn bị cháy xử lý như nào?",
                    "Canh bị mặn quá chữa sao?",
                    "Thiếu nước cốt dừa thay bằng gì?",
                ],
            }
    if any(w in msg_norm for w in ["cap cuu", "chua chay", "bi loi", "xu ly", "xu li", "bi chay", "chay"]):
        # Default to burned dish rescue when user asks about burning or general kitchen error
        burned = KITCHEN_RESCUE_KNOWLEDGE[0]
        bullets = "\n".join(f"- {s}" for s in burned["solutions"])
        return {
            "intent": "kitchen_rescue",
            "reply": f"🆘 **Xử lý sự cố món ăn — {burned['problem']}:**\n\n{bullets}",
            "recipes": [],
            "suggestions": [
                "Canh bị mặn quá chữa sao?",
                "Cơm bị nhão làm thế nào?",
                "Nước phở bị đục xử lý sao?",
            ],
        }
    return None


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
                    f"🔄 **Gợi ý thay thế khi thiếu \"{item['ingredient']}\":**\n\n"
                    f"{bullets}\n\n"
                    f"💡 *Lưu ý đầu bếp: Khi dùng nguyên liệu thay thế, bạn nên nếm thử từ 2/3 định lượng trước để điều chỉnh độ mặn/ngọt vừa miệng nhé!*"
                ),
                "recipes": [],
                "suggestions": [
                    "Thiếu bột năng thì thay bằng gì?",
                    "Ăn chay thay nước mắm bằng gì?",
                    "Không có rượu nấu ăn khử mùi bằng gì?",
                ],
            }
    overview = "\n".join(
        f"- **Thiếu {it['ingredient']}:** {it['substitutes'][0]}"
        for it in SUBSTITUTION_KNOWLEDGE[:6]
    )
    return {
        "intent": "ingredient_substitution",
        "reply": (
            "🔄 **Bảng gợi ý thay thế các nguyên liệu thường thiếu trong bếp:**\n\n"
            + overview
            + "\n\n*Bạn đang thiếu nguyên liệu cụ thể nào? Hãy nhắn tên nguyên liệu đó (VD: \"Thiếu dầu hào\", \"Hết nước cốt dừa\") để mình chỉ cách thay thế chuẩn nhất nhé!*"
        ),
        "recipes": [],
        "suggestions": [
            "Hết nước cốt dừa thay bằng gì?",
            "Thiếu bột năng thay bằng bột gì?",
            "Thiếu dầu hào thay bằng gì?",
        ],
    }


# ============================================================
# NHÓM 2.3: HỎI ĐÁP CÁCH NẤU THEO MÓN ĂN / NGỮ CẢNH ĐANG XEM
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
                    f"💡 *Mẹo nhỏ:* Giữ mức lửa ổn định và chuẩn bị sẵn gia vị trước khi thao tác bước này để món ăn không bị quá lửa nhé!"
                ),
                "recipes": [_format_recipe_card(recipe)],
                "suggestions": [
                    f"Toàn bộ cách nấu {recipe['title']}",
                    f"Quy đổi {recipe['title']} cho 6 người",
                    "Khi làm món ăn bị cháy xử lý như nào?",
                ],
            }

    ing_summary = ", ".join(
        f"{i['name']} (`{i['amount']} {i['unit']}`)" for i in recipe.get("ingredients", [])
    )
    step_lines = [
        f"- **Bước {s.get('step', idx + 1)}:** {s.get('description', '')}"
        for idx, s in enumerate(steps)
    ]
    nut = recipe.get("nutrition") or {}
    reply = (
        f"🍲 **Hướng dẫn nấu món \"{recipe['title']}\"** (Độ khó: {recipe.get('difficulty', 'Dễ')} • "
        f"Chuẩn bị {recipe.get('prepTime', 15)}p + Nấu {recipe.get('cookTime', 25)}p • Khẩu phần {recipe.get('servings', 4)} người):\n\n"
        f"**1. Nguyên liệu cần chuẩn bị:**\n{ing_summary}\n\n"
        f"**2. Các bước thực hiện ({len(steps)} bước):**\n"
        + "\n".join(step_lines)
        + f"\n\n**3. Giá trị dinh dưỡng / khẩu phần:** `{recipe.get('calories', 350)} kcal` "
        f"(Đạm: {nut.get('protein', '15g')}, Béo: {nut.get('fat', '10g')}, Tinh bột: {nut.get('carbs', '40g')})."
    )
    return {
        "intent": "recipe_context",
        "reply": reply,
        "recipes": [_format_recipe_card(recipe)],
        "suggestions": [
            f"Quy đổi {recipe['title']} cho 8 người",
            "Thiếu nguyên liệu thì thay thế bằng gì?",
            "Món kho bị cháy xử lý thế nào?",
        ],
    }


# ============================================================
# MAIN ROUTER — CHỈ GIẢI ĐÁP VỀ MÓN ĂN (TÍCH HỢP NHÓM 1 & 2)
# ============================================================

def generate_chatbot_response(
    message: str,
    context: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Trợ lý AI chuyên biệt về món ăn (Nhóm 1 & Nhóm 2):
      - Có nguyên liệu này nấu món gì? (`fridge_match`)
      - Tư vấn dinh dưỡng & Calo (`nutrition_plan`)
      - Quy đổi định lượng khẩu phần (`portion_scale`)
      - Xử lý sự cố khi nấu ăn: cháy, mặn, nhão, khê, đục, dai, tanh (`kitchen_rescue`)
      - Thay thế nguyên liệu khi thiếu (`ingredient_substitution`)
      - Giải đáp chi tiết cách nấu món ăn (`recipe_context`)
      - Từ chối câu hỏi ngoài phạm vi ẩm thực (`off_topic`)
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
                "Xin chào! Mình là **Trợ lý Đầu bếp AI của CookMate** 👨‍🍳 (Chuyên giải đáp về Món ăn & Kỹ thuật nấu nướng).\n\n"
                "Bạn có thể hỏi mình ngay về:\n"
                "1. 🧊 **Có nguyên liệu này nấu món gì?** *(VD: \"Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?\")*\n"
                "2. 🆘 **Xử lý sự cố khi nấu ăn:** *(VD: \"Khi làm món ăn bị cháy thì xử lý như nào?\", \"Canh bị mặn chữa sao?\")*\n"
                "3. 🔄 **Thay thế nguyên liệu bị thiếu:** *(VD: \"Thiếu nước cốt dừa thay bằng gì?\", \"Hết bột năng thay bằng gì?\")*\n"
                "4. ⚖️ **Quy đổi khẩu phần & Dinh dưỡng:** *(VD: \"Phở bò cho 8 người\", \"Thực đơn 3 bữa 1500 kcal\")*"
            ),
            "recipes": [_format_recipe_card(r) for r in all_recipes[:2]],
            "suggestions": [
                "Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?",
                "Khi làm món ăn bị cháy thì xử lý như nào?",
                "Thiếu nước cốt dừa thì thay bằng gì?",
                "Phở bò Hà Nội nấu cho 8 người",
            ],
        }

    # 0. Guardrail: Từ chối lịch sự nếu câu hỏi nằm ngoài chủ đề món ăn / ẩm thực
    if _is_off_topic(msg_norm):
        return {
            "intent": "off_topic",
            "reply": (
                "🙏 Xin lỗi bạn, mình là **Trợ lý Đầu bếp AI của CookMate** nên **chỉ giải đáp các câu hỏi liên quan đến món ăn, nguyên liệu, dinh dưỡng và kỹ thuật nấu nướng**.\n\n"
                "Bạn hãy thử hỏi mình những câu như:\n"
                "- *\"Tôi có thịt heo, trứng, cà chua thì nấu món gì?\"*\n"
                "- *\"Khi làm món ăn bị cháy hoặc bị mặn thì xử lý như thế nào?\"*\n"
                "- *\"Thiếu nước cốt dừa / bột năng thì thay thế bằng nguyên liệu nào?\"*"
            ),
            "recipes": [],
            "suggestions": [
                "Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?",
                "Khi làm món ăn bị cháy thì xử lý như nào?",
                "Thiếu nước cốt dừa thì thay bằng gì?",
            ],
        }

    # 1. Xử lý sự cố nhà bếp ("Cấp cứu món ăn": cháy, khê, mặn, nhão, đục, dai, tanh...) — Nhóm 2
    rescue = _handle_kitchen_rescue(msg_norm)
    if rescue:
        return rescue

    # 2. Thay thế nguyên liệu khi thiếu — Nhóm 2
    sub = _handle_substitution(msg_norm)
    if sub:
        return sub

    # 3. Tính toán & quy đổi khẩu phần ăn (UC06-A) — Nhóm 1
    if any(kw in msg_norm for kw in ["quy doi", "khau phan", "nguoi an", "cho ", "suat"]):
        scaled_resp = _handle_portion_scaling(
            raw_msg, msg_norm, all_recipes, current_recipe_id=current_recipe_id
        )
        if scaled_resp:
            return scaled_resp

    # 4. Tư vấn món ăn theo Calo & Dinh dưỡng (UC06-B) — Nhóm 1
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

    # 5. Có nguyên liệu này nấu món gì? (Fridge / Ingredient Matcher) — Nhóm 1
    fridge = _handle_fridge_search(raw_msg, msg_norm, all_recipes, all_ingredients)
    if fridge:
        return fridge

    # 6. Hỏi đáp chi tiết cách nấu món ăn / món đang xem trên màn hình — Nhóm 2
    ctx_resp = _handle_recipe_context_question(
        raw_msg, msg_norm, all_recipes, current_recipe_id=current_recipe_id
    )
    if ctx_resp:
        return ctx_resp

    # 7. Phản hồi hướng dẫn mặc định tập trung hoàn toàn vào Nhóm 1 & Nhóm 2
    featured = [r for r in all_recipes if r.get("featured")] or all_recipes[:3]
    return {
        "intent": "general_recommend",
        "reply": (
            "👨‍🍳 **Mình sẵn sàng giải đáp mọi thắc mắc về món ăn và nấu nướng cho bạn!**\n\n"
            "Hãy cho mình biết:\n"
            "- 🧊 **Nguyên liệu bạn đang có:** *\"Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?\"*\n"
            "- 🆘 **Sự cố món ăn đang gặp:** *\"Món ăn bị cháy xử lý sao?\"*, *\"Canh bị mặn chữa thế nào?\"*\n"
            "- 🔄 **Nguyên liệu đang thiếu:** *\"Thiếu nước cốt dừa / bột năng thay bằng gì?\"*\n"
            "- ⚖️ **Định lượng & Dinh dưỡng:** *\"Phở bò cho 8 người\"*, *\"Món ăn dưới 400 kcal\"*"
        ),
        "recipes": [_format_recipe_card(r) for r in featured[:3]],
        "suggestions": [
            "Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?",
            "Khi làm món ăn bị cháy thì xử lý như nào?",
            "Thiếu nước cốt dừa thì thay bằng gì?",
            "Thực đơn 3 bữa 1500 kcal",
        ],
    }
