# -*- coding: utf-8 -*-
"""
CookMate ChefBot — Trợ Lý AI Chuyên Sâu Giải Đáp Món Ăn, Sự Cố Bếp & Nguyên Liệu
=================================================================================
Phân tích chính xác ý định câu hỏi tiếng Việt (có dấu & không dấu) của người dùng:
  1. Xử lý sự cố món ăn & Sơ chế khử mùi (Cháy/khét, thịt gà/heo/bò bị hôi, cá tanh,
     canh/kho bị mặn, cơm nhão/sống/khê, nước đục, thịt dai/khô, quá cay/chua/đắng, dính chảo...)
  2. Thay thế nguyên liệu khi thiếu (Xì dầu/nước tương, nước mắm, dầu hào, cốt dừa, bột năng,
     rượu nấu ăn, hạt nêm, đường phèn, chanh/giấm/me, hành/tỏi/gừng/sả, bơ/sữa, màu điều...
     + Tự động bóc tách tên nguyên liệu người dùng vừa nhập để trả lời đúng trọng tâm)
  3. Có nguyên liệu này nấu món gì? (Đối chiếu CSDL CookMate + Gợi ý món ăn gia đình sát thực tế)
  4. Quy đổi khẩu phần ăn (UC06-A) & Tư vấn Calo / Dinh dưỡng (UC06-B)
  5. Hướng dẫn cách nấu / ướp / luộc / kho chi tiết cho từng món ăn
"""

import json
import os
import re
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from backend import database as db


OFF_TOPIC_KEYWORDS = [
    "lap trinh",
    "code python",
    "javascript",
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
    "cai win",
    "sua may tinh",
]


# ============================================================
# 1. CƠ SỞ TRI THỨC XỬ LÝ SỰ CỐ & SƠ CHẾ KHỬ MÙI (NHÓM 2)
# ============================================================

RESCUE_RULES = [
    {
        "id": "poultry_odor",
        "patterns": [
            r"\b(ga|uc ga|dui ga|vit|ngan)\b.*\b(hoi|tanh|mui|so che|lam sach)\b",
            r"\b(hoi|tanh|mui long|khu mui)\b.*\b(ga|uc ga|dui ga|vit|ngan)\b",
        ],
        "title": "Thịt gà / Vịt bị hôi hoặc có mùi lông",
        "solutions": [
            "**Cách 1 — Chà Gừng đập dập + Muối hạt + Chanh/Giấm (hoặc Rượu trắng):** Đập dập 1 củ gừng tươi, trộn với 1 muỗng muối hạt và nửa quả chanh (hoặc 2 muỗng rượu trắng/giấm), chà xát kỹ khắp bề mặt thịt gà trong 3–5 phút rồi xả sạch bằng nước lạnh — khử sạch 95% mùi hôi.",
            "**Cách 2 — Cắt bỏ tuyến dầu ở phao câu & rửa máu bầm:** Nếu làm gà nguyên con, bắt buộc cắt bỏ 2 u tuyến bã nhờn ở phao câu và cạo sạch phần máu đông sát xương sống (đây là nguyên nhân chính gây mùi hôi).",
            "**Cách 3 — Chần sơ với hành gừng:** Đun sôi nước với **vài lát gừng + 1 củ hành tím đập dập + chút muối**, chần thịt gà 1–2 phút cho săn và ra hết bọt bẩn trước khi đem kho, luộc hoặc nấu canh.",
            "**Mẹo khi chế biến:** Thêm **lá chanh thái chỉ, sả đập dập hoặc gừng non** vào món ăn sẽ giúp thịt gà dậy mùi thơm đặc trưng.",
        ],
    },
    {
        "id": "pork_beef_odor",
        "patterns": [
            r"\b(heo|lon|suon|ba chi|bo|long|da day)\b.*\b(hoi|tanh|mui|gay|so che|lam sach)\b",
            r"\b(hoi|mui hoi|khu mui)\b.*\b(thit|heo|lon|suon|bo|long)\b",
            r"\b(bi hoi|mui hoi|khu mui hoi)\b",
        ],
        "title": "Thịt heo / Thịt bò / Sườn bị hôi khi sơ chế hoặc chế biến",
        "solutions": [
            "**Với Thịt heo / Sườn heo bị hôi:**\n"
            "  • Ngâm thịt trong **nước muối loãng ấm pha vài lát gừng và 1 muỗng giấm/rượu trắng** khoảng 10 phút.\n"
            "  • Bỏ thịt vào nồi từ lúc **nước còn lạnh** (kèm 1 củ hành tím đập dập), đun sôi từ từ để bọt bẩn và mùi hôi tiết hết ra ngoài, sau đó đổ bỏ nước đầu và rửa lại bằng nước ấm.",
            "**Với Thịt bò (khử mùi gây):** Chà nhẹ miếng gừng nướng thơm lên bề mặt thịt, không rửa thịt bò quá lâu dưới vòi nước mạnh để tránh mất vị ngọt; khi ướp thêm tỏi băm, gừng và chút dầu mè.",
            "**Với Lòng / Dạ dày:** Bóp kỹ 2 lần với **bột mì (để hút sạch nhớt) + muối hạt + chanh/giấm**, sau đó chần qua nước sôi có gừng và sả.",
        ],
    },
    {
        "id": "fish_seafood_odor",
        "patterns": [
            r"\b(tanh|bi tanh|mui tanh|ca tanh|tom tanh|hai san tanh|bi nhot|sach nhot)\b",
            r"\b(ca|tom|muc|hai san|luon|ech)\b.*\b(tanh|hoi|nhot|khu mui|so che)\b",
        ],
        "title": "Cá / Tôm / Hải sản bị tanh hoặc nhiều nhớt",
        "solutions": [
            "**Khử nhớt & mùi tanh khi sơ chế:**\n"
            "  • **Nước vo gạo hoặc Muối + Chanh/Giấm:** Ngâm cá trong nước vo gạo 10 phút, hoặc chà xát muối hạt với nước cốt chanh/giấm (hoặc tro bếp/bột mì đối với cá da trơn).\n"
            "  • **Làm sạch màng đen trong bụng cá:** Cạo thật sạch lớp màng đen trong khoang bụng và cục máu đông dọc sống lưng cá — đây là nơi tích tụ mùi tanh nặng nhất.",
            "**Xử lý khi món cá đang nấu bị tanh:** Cho ngay vào nồi **vài lát gừng tươi, sả đập dập, 1 muỗng rượu trắng**, hoặc **2–3 muỗng nước chè xanh đặc / cà chua / dứa (thơm)** và mở nắp nồi 2 phút để hơi tanh bay đi.",
        ],
    },
    {
        "id": "burned_food",
        "patterns": [
            r"\b(bi chay|chay noi|chay khet|bi khet|bi khe|com khe|khet|chay day)\b",
            r"\b(lam mon an|mon an|thit kho|ca kho|nau|com)\b.*\b(chay|khet|khe)\b",
        ],
        "title": "Món ăn / Nồi kho / Cơm bị cháy hoặc có mùi khê khét",
        "solutions": [
            "**Bước 1 — Tắt bếp ngay & TUYỆT ĐỐI KHÔNG ĐẢO/KHUẤY:** Đừng dùng đũa cạo hay đảo phần đáy nồi bị cháy vì sẽ làm cặn đen và vị đắng khét lan ra toàn bộ món ăn.",
            "**Bước 2 — Chuyển ngay phần chưa cháy sang nồi sạch mới:** Nhẹ nhàng gắp phần thức ăn ở phía trên (chưa bén lửa) sang một chiếc nồi khác, bỏ hoàn toàn lớp đáy cháy.",
            "**Bước 3 — Khử sạch mùi khê khét trên thức ăn:**\n"
            "  • *Nếu là Cơm bị khê:* Đặt ngay **1–2 lát bánh mì sandwich**, hoặc **vài gốc hành lá tươi**, hoặc **1 chiếc bát nhỏ đựng nước lạnh** lên mặt cơm, đậy nắp 5–10 phút — mùi khê sẽ bị hút sạch!\n"
            "  • *Nếu là Thịt kho / Cá kho bị cháy sốt:* Rửa sơ miếng thịt qua nước ấm nếu dính cặn đen, sau đó pha nước sốt mới (nước dừa tươi/nước lọc + nước mắm + đường + gừng/hành tím) đun liu riu 5–7 phút.",
            "**Bước 4 — Mẹo làm sạch nồi bị cháy không cần cọ mạnh:** Đổ nước ngập vết cháy, cho `2 muỗng canh Baking Soda + 3 muỗng giấm trắng` đun sôi 5 phút rồi ngâm 15 phút, lớp cháy sẽ tự bong tróc!",
        ],
    },
    {
        "id": "too_salty",
        "patterns": [
            r"\b(bi man|man qua|chua man|qua man|man chát)\b",
            r"\b(canh|kho|xao|mon|nuoc dung|sup)\b.*\b(man)\b",
        ],
        "title": "Món canh / Món kho / Món xào bị mặn quá",
        "solutions": [
            "**Cách 1 — Thả khoai tây sống cắt lát (Hiệu quả nhất):** Gọt vỏ `1 củ khoai tây sống`, thái lát dày 1cm thả vào nồi canh hoặc nồi kho đun nhỏ lửa 10 phút rồi vớt ra — khoai tây hút muối thừa cực nhạy mà không làm hỏng vị món ăn.",
            "**Cách 2 — Với món Canh / Súp:** Châm thêm nước sôi, bổ sung nguyên liệu nhạt như **đậu hũ non, cà chua, nấm, bầu/bí** để trung hòa độ mặn; có thể vắt vài giọt cốt chanh để dịu vị gắt.",
            "**Cách 3 — Với món Thịt kho / Cá kho:** Thêm **nước dừa tươi** (hoặc nước sôi) + **1 muỗng cà phê đường phèn / mật ong** rồi đun nhỏ lửa cho vị dịu lại.",
        ],
    },
    {
        "id": "rice_mushy_or_raw",
        "patterns": [
            r"\b(com nhao|bi nhao|nhao qua|com uot|com song|bi song|com suong|bi suong)\b",
        ],
        "title": "Cơm bị nhão (ướt) hoặc bị sống / sượng",
        "solutions": [
            "**Khi cơm bị nhão / ướt:** Mở nắp nồi 2 phút cho thoát bớt hơi nước, đặt **1–2 lát bánh mì ruột trắng** lên mặt cơm rồi đậy nắp để chế độ `Warm` 10 phút — bánh mì sẽ hút hết nước thừa giúp hạt cơm ráo tơi.",
            "**Khi cơm bị sống / sượng:** Xới tơi cơm, dùng đũa chọc vài lỗ thoáng từ mặt xuống đáy nồi, rưới đều hỗn hợp `2 muỗng canh nước ấm + 1 muỗng cà phê rượu trắng` (tỷ lệ 1 muỗng rượu cho mỗi 500g gạo) rồi bấm nút `Cook` lại. Rượu sẽ bay hơi hết không để lại mùi và giúp cơm chín dẻo đều.",
        ],
    },
    {
        "id": "cloudy_broth",
        "patterns": [
            r"\b(bi duc|nuoc duc|nuoc dung duc|nuoc pho duc|nuoc leo duc|lam trong nuoc)\b",
        ],
        "title": "Nước dùng Phở / Bún / Canh hầm xương bị đục",
        "solutions": [
            "**Tuyệt chiêu lòng trắng trứng gà:** Đánh tan `1 lòng trắng trứng` với chút nước nguội, đổ vào nồi nước dùng đang ấm và khuấy đều. Khi nước sôi lăn tăn, lòng trắng kết tủa sẽ cuốn sạch toàn bộ vẩn đục nổi lên mặt — chỉ cần vớt bỏ hoặc lọc qua rây là nước dùng trong veo!",
            "**Thả vài lát khoai tây sống hoặc củ cải trắng:** Hút cặn lơ lửng và giúp nước ngọt thanh hơn.",
            "**Lưu ý khi ninh xương:** Luôn chần xương 3 phút với nước sôi + muối + gừng, rửa sạch máu bầm rồi mới ninh lửa nhỏ và **mở hé nắp nồi**.",
        ],
    },
    {
        "id": "tough_dry_meat",
        "patterns": [
            r"\b(bi dai|thit dai|bo dai|bi kho|uc ga kho|thit cung|bi cung|lau mem)\b",
        ],
        "title": "Thịt bò / Ức gà / Thịt hầm bị dai hoặc khô bã",
        "solutions": [
            "**Khi món hầm đang bị dai:** Cho vào nồi `vài miếng dứa (thơm) chín`, `1 miếng đu đủ xanh nhỏ` hoặc `1 muỗng cà phê nước cốt chanh` — enzyme tự nhiên sẽ làm mềm thớ thịt nhanh gấp đôi.",
            "**Mẹo chế biến Ức gà mềm mọng không bị khô:** Ngâm ức gà trong nước muối loãng 15 phút trước khi nấu (Brining), hoặc ướp với **1 muỗng sữa tươi / sữa chua không đường + 1/2 muỗng bột bắp + chút dầu ăn**; áp chảo lửa vừa mỗi mặt đúng 3–4 phút rồi đậy nắp nghỉ 3 phút.",
            "**Mẹo xào Thịt bò mềm tan:** Luôn thái ngang thớ, ướp với **dầu ăn + chút bột năng + tỏi**, không ướp muối trước và xào nhanh trên lửa thật lớn.",
        ],
    },
    {
        "id": "too_spicy_sour_sweet_bitter",
        "patterns": [
            r"\b(bi cay|cay qua|qua cay|bi chua|chua qua|qua chua|bi ngot|ngot qua|qua ngot|bi dang|dang qua|canh kho qua)\b",
        ],
        "title": "Món ăn bị quá cay, quá chua, quá ngọt hoặc bị đắng",
        "solutions": [
            "**Chữa món quá cay:** Thêm **nước cốt dừa, sữa tươi không đường, bơ lạt** hoặc **1 muỗng đường + cà chua** (chất béo hòa tan chất cay Capsaicin ngay lập tức).",
            "**Chữa món quá chua:** Thêm **1/2 – 1 muỗng cà phê đường phèn** hoặc **1 nhúm rất nhỏ muối nở (Baking Soda)** khuấy đều để trung hòa axit chua.",
            "**Chữa món quá ngọt:** Thêm **vài giọt nước cốt chanh / giấm gạo** và một chút nước mắm để cân bằng vị.",
            "**Giảm vị đắng (khổ qua / măng / cùi bưởi):** Cạo sạch lớp màng trắng bên trong khổ qua, bóp muối xả nước lạnh hoặc chần sơ qua nước sôi có pha chút muối và đường trước khi nấu.",
        ],
    },
    {
        "id": "sticking_splattering_soggy",
        "patterns": [
            r"\b(dinh chao|ban dau|vang dau|bi nat|khong gion|bi iu|rau bi den|rau bi tham|rau bi vang|von cuc)\b",
        ],
        "title": "Chiên rán bị dính chảo / bắn dầu / ỉu hoặc Rau luộc bị thâm",
        "solutions": [
            "**Chiên cá / đậu không dính chảo & không bắn dầu:** Thấm thật khô nước trên thực phẩm; đun nóng chảo trước rồi mới đổ dầu, rắc vào dầu **1/4 muỗng cà phê bột mì (hoặc vài hạt muối)** và chà 1 lát gừng tươi lên mặt chảo trước khi cho cá vào.",
            "**Giữ đồ chiên giòn lâu không bị ỉu:** Pha thêm vài giọt nước cốt chanh hoặc 1 muỗng bia vào bột chiên, và **chiên 2 lửa** (lần 1 chín tới, lần 2 dầu nóng già trước khi ăn).",
            "**Giữ rau luộc xanh mướt:** Nước phải sôi bùng mới thả rau, cho `1/2 muỗng muối + vài giọt dầu ăn`, luộc mở vung trên lửa lớn rồi vớt ra đĩa thoáng.",
        ],
    },
]


# ============================================================
# 2. CƠ SỞ TRI THỨC THAY THẾ NGUYÊN LIỆU CHI TIẾT (35+ LOẠI)
# ============================================================

SUBSTITUTION_CATALOG = [
    {
        "names": ["xì dầu", "xi dau", "nước tương", "nuoc tuong", "hắc xì dầu", "hac xi dau"],
        "label": "Xì dầu (Nước tương)",
        "substitutes": [
            "**Khi dùng để ướp thịt hoặc xào nấu:** Thay `1 muỗng canh xì dầu` bằng **`2/3 muỗng canh nước mắm + 1/3 muỗng cà phê đường + vài giọt nước màu (hoặc 1/2 muỗng dầu hào)`** để giữ trọn vị mặn dịu và màu nâu óng đẹp mắt.",
            "**Khi dùng để pha nước chấm:** Bạn có thể chuyển sang pha **nước mắm chua ngọt** (`1 mắm : 1 đường : 1 cốt chanh : 4 nước ấm + tỏi ớt`) hoặc dùng **dầu hào pha loãng với chút nước ấm, đường và ớt tươi**.",
            "**Khi nấu món chay (không có xì dầu):** Thay bằng **`muối biển + chút đường nâu (hoặc nước hàng thắng nhẹ) + hạt nêm nấm hương`**.",
        ],
    },
    {
        "names": ["nước mắm", "nuoc mam", "mắm", "mam chay"],
        "label": "Nước mắm",
        "substitutes": [
            "**Thay bằng Xì dầu (Nước tương) + Muối:** Pha **`1 muỗng canh xì dầu + 1/4 muỗng cà phê muối`** cho mỗi muỗng canh nước mắm để món ăn giữ được độ đậm đà.",
            "**Khi nấu canh / súp:** Thay bằng **`Muối hạt + Hạt nêm (theo tỷ lệ 1:1)`** để nước canh ngọt thanh và trong.",
            "**Khi ăn chay:** Dùng **nước tương (xì dầu)** hoặc **nước mắm chay nấu từ dứa (thơm) và nấm đông cô**.",
        ],
    },
    {
        "names": ["dầu hào", "dau hao"],
        "label": "Dầu hào",
        "substitutes": [
            "**Công thức thay thế 1 muỗng canh Dầu hào chuẩn nhất:** Pha **`1 muỗng canh xì dầu (nước tương) + 1/2 muỗng cà phê đường + 1/4 muỗng cà phê bột năng (hoặc bột bắp)`** — khi xào lên sẽ tạo độ sánh bóng và vị ngọt mặn y hệt dầu hào!",
            "**Thay thế nhanh khi ướp thịt:** Dùng **`2/3 muỗng canh nước mắm + 1/2 muỗng cà phê đường (hoặc mật ong)`**.",
        ],
    },
    {
        "names": ["nước cốt dừa", "nuoc cot dua", "cốt dừa", "cot dua"],
        "label": "Nước cốt dừa",
        "substitutes": [
            "**Sữa tươi không đường + Bơ lạt (Khuyên dùng):** Pha **`200ml sữa tươi không đường + 15g bơ lạt đun chảy`** — tái tạo được 85–90% độ béo ngậy và sánh mịn cho món cà ri, kho, bánh.",
            "**Sữa đặc + Sữa tươi:** Pha **`180ml sữa tươi + 2 muỗng canh sữa đặc`** khi nấu các món chè hoặc sinh tố.",
            "**Kem tươi (Whipping Cream / Cooking Cream):** Thay thế trực tiếp theo tỷ lệ `1:1`.",
        ],
    },
    {
        "names": ["nước dừa", "nuoc dua", "dừa tươi", "dua tuoi", "dừa xiêm"],
        "label": "Nước dừa tươi (khi kho thịt / hầm)",
        "substitutes": [
            "**Nước lọc ấm + Đường phèn (hoặc Đường thốt nốt):** Pha **`300ml nước ấm + 1 muỗng canh đường phèn`** sẽ tạo vị ngọt thanh tự nhiên và giúp thịt kho lên màu trong bóng gần giống nước dừa xiêm.",
            "**Nước mía nguyên chất pha loãng (1 phần nước mía : 2 phần nước lọc):** Bí quyết kho cá/thịt cực ngon của đầu bếp miền Nam.",
        ],
    },
    {
        "names": ["bột năng", "bot nang", "bột bắp", "bot bap", "bột sắn", "bot san", "bột đao"],
        "label": "Bột năng / Bột bắp (Tạo độ sánh)",
        "substitutes": [
            "**Bột năng ↔ Bột bắp ↔ Bột sắn dây:** Thay thế trực tiếp cho nhau theo tỷ lệ **`1:1`** (nhớ hòa tan với nước lạnh trước rồi mới rưới từ từ vào nồi đang sôi).",
            "**Thay bằng Bột mì đa dụng:** Dùng lượng gấp đôi (`2 muỗng bột mì = 1 muỗng bột năng`), phù hợp để làm sánh nước sốt xào hoặc súp.",
            "**Thay bằng Bột gạo:** Có thể dùng tạm cho món sốt nhưng độ trong sẽ kém hơn bột năng một chút.",
        ],
    },
    {
        "names": ["bột chiên giòn", "bot chien gion", "bột chiên xù", "bot chien xu", "bột mì", "bot mi"],
        "label": "Bột chiên giòn / Bột mì",
        "substitutes": [
            "**Tự pha Bột chiên giòn tại nhà:** Trộn **`3 muỗng canh bột mì (hoặc bột gạo) + 1 muỗng canh bột năng (hoặc bột bắp) + 1/4 muỗng cà phê muối + chút bột nở (nếu có)`**, pha với nước đá lạnh hoặc bia sẽ chiên giòn rụm!",
            "**Thay Bột chiên xù:** Dùng **bánh mì sandwich sấy khô bóp vụn**, **bánh phồng tôm sống giã nhỏ** hoặc **ngũ cốc bắp (Cornflakes) nghiền vụn**.",
        ],
    },
    {
        "names": ["rượu nấu ăn", "ruou nau an", "rượu trắng", "ruou trang", "rượu mirin", "mirin", "rượu"],
        "label": "Rượu nấu ăn / Rượu trắng",
        "substitutes": [
            "**Khi cần khử mùi tanh thịt/cá:** Dùng **`Gừng tươi đập dập + 1 muỗng canh Giấm gạo (hoặc nước cốt chanh)`** chà xát hoặc cho vào nước chần.",
            "**Khi thay rượu ngọt Mirin (món Nhật/Hàn/Sốt):** Pha **`1 muỗng canh nước táo ép (hoặc nước lọc) + 1/2 muỗng cà phê đường + vài giọt giấm gạo`**.",
        ],
    },
    {
        "names": ["hạt nêm", "hat nem", "bột ngọt", "bot ngot", "mì chính", "mi chinh"],
        "label": "Hạt nêm / Bột ngọt (Mì chính)",
        "substitutes": [
            "**Thay 1 muỗng cà phê Hạt nêm:** Pha **`1/2 muỗng cà phê muối + 1/2 muỗng cà phê đường`** (hoặc dùng `1 muỗng cà phê nước mắm ngon`).",
            "**Tạo vị ngọt tự nhiên không cần Bột ngọt:** Ninh nước dùng với **củ cải trắng, cà rốt, bắp Mỹ (ngô ngọt), hành tây nướng hoặc nấm hương/tôm khô**.",
        ],
    },
    {
        "names": ["đường phèn", "duong phen", "đường nâu", "duong nau", "đường thốt nốt", "duong thot not", "mật ong", "mat ong", "đường", "duong"],
        "label": "Đường phèn / Đường nâu / Mật ong",
        "substitutes": [
            "**Thay Đường phèn:** Dùng **đường cát trắng** theo tỷ lệ `90g đường cát = 100g đường phèn`.",
            "**Thay Mật ong (khi ướp nướng):** Dùng **`Sữa đặc`** hoặc **`Đường nâu / Đường trắng pha chút nước ấm`** giúp thịt nướng vẫn mềm mọng và lên màu cánh gián đẹp.",
            "**Thay Đường khi ăn kiêng / hết đường:** Dùng **mật ong**, **sữa đặc** hoặc vị ngọt tự nhiên từ **hành tây xào, cà rốt, táo/lê ép**.",
        ],
    },
    {
        "names": ["chanh", "giấm", "giam", "me", "me chua", "quất", "tắc", "tac", "sấu"],
        "label": "Chanh / Giấm / Me chua",
        "substitutes": [
            "**Chanh ↔ Quất (Tắc):** `2 quả tắc = 1 quả chanh vừa`, rất thơm khi pha nước chấm hoặc ăn phở/bún.",
            "**Chanh ↔ Giấm gạo / Giấm táo:** Thay thế tỷ lệ `1:1` (`1 muỗng canh giấm = 1 muỗng canh nước cốt chanh`).",
            "**Thay Me chua khi nấu canh chua:** Dùng **cà chua chín + dứa (thơm)**, **khế chua**, **sấu** hoặc **nước cốt chanh** (nếu dùng chanh thì tắt bếp mới vắt vào để không bị đắng).",
        ],
    },
    {
        "names": ["bơ", "bo lat", "bơ lạt", "dầu ăn", "dau an", "mỡ heo", "mo heo"],
        "label": "Bơ lạt / Dầu ăn / Mỡ",
        "substitutes": [
            "**Thay Bơ lạt khi xào/áp chảo:** Dùng **dầu ăn, dầu ô-liu hoặc mỡ heo** theo tỷ lệ `8ml dầu = 10g bơ`.",
            "**Thay Dầu ăn khi hết dầu:** Dùng **bơ**, **mỡ heo/mỡ gà**, hoặc nếu chiên thịt ba chỉ/sườn thì chỉ cần áp chảo khô trên lửa nhỏ để mỡ tự tiết ra.",
        ],
    },
    {
        "names": ["sữa tươi", "sua tuoi", "sữa đặc", "sua dac", "kem tươi", "whipping cream", "sữa chua", "sua chua"],
        "label": "Sữa tươi / Sữa đặc / Kem tươi",
        "substitutes": [
            "**Thay Sữa tươi:** Pha loãng **`1 muỗng canh sữa đặc với 4 muỗng canh nước ấm`** (hoặc dùng **nước cốt dừa loãng / sữa hạt**).",
            "**Thay Sữa đặc:** Dùng **`Sữa tươi đun nhỏ lửa với đường`** theo tỷ lệ `100ml sữa tươi + 30g đường + 5g bơ`.",
            "**Thay Kem tươi (Whipping Cream) trong nấu súp/sốt:** Pha **`160ml sữa tươi không đường + 40g bơ lạt đun chảy + 1 muỗng cà phê bột mì`**.",
        ],
    },
    {
        "names": ["hành tím", "hanh tim", "hành khô", "hanh kho", "tỏi", "toi", "hành tây", "hanh tay", "hành lá", "hanh la", "rau mùi", "ngò"],
        "label": "Hành tím / Tỏi / Hành tây / Hành lá",
        "substitutes": [
            "**Thay Hành tím (Hành khô):** Dùng **phần gốc trắng của hành lá đập dập**, **hành tây băm nhỏ** hoặc **hành boa-rô (tỏi tây)** để phi thơm.",
            "**Thay Tỏi:** Dùng **hành tím băm + 1 lát gừng nhỏ** hoặc **bột tỏi** (`1/4 muỗng cà phê bột tỏi = 1 tép tỏi tươi`).",
            "**Thay Hành lá / Ngò rí:** Dùng **hẹ tươi, cần tây, rau răm hoặc thì là** tùy theo món canh/xào.",
        ],
    },
    {
        "names": ["gừng", "gung", "sả", "sa", "riềng", "rieng", "lá chanh", "la chanh", "ớt", "ot", "tiêu", "tieu"],
        "label": "Gừng / Sả / Riềng / Ớt / Tiêu",
        "substitutes": [
            "**Thay Gừng tươi:** Dùng **sả đập dập**, **riềng**, **tiêu hạt đập dập** hoặc **vỏ chanh/cam bào mỏng** để tạo hương ấm và khử mùi tanh.",
            "**Thay Sả:** Dùng **gừng tươi + vài lá chanh thái chỉ** (hoặc vỏ chanh bào).",
            "**Thay Ớt tươi:** Dùng **ớt bột, tương ớt, sa tế hoặc hạt tiêu xay** để tạo vị cay.",
        ],
    },
    {
        "names": ["nước hàng", "nuoc hang", "nước màu", "nuoc mau", "màu điều", "mau dieu", "bột nghệ", "bot nghe", "ngũ vị hương", "ngu vi huong"],
        "label": "Nước màu (Nước hàng) / Dầu màu điều / Bột nghệ / Ngũ vị hương",
        "substitutes": [
            "**Khi không có Nước màu (Nước hàng) kho thịt/cá:** Cho `2 muỗng canh đường + 1 muỗng canh nước (hoặc dầu ăn)` vào chảo thắng lửa nhỏ 2 phút đến khi lên màu cánh gián; hoặc thay bằng **xì dầu (nước tương) + mật ong**.",
            "**Thay Dầu màu điều:** Dùng **bột nghệ**, **bột ớt Paprika** hoặc **cà chua chín băm nhuyễn xào với dầu ăn** để lấy màu đỏ vàng đẹp mắt.",
            "**Thay Ngũ vị hương:** Trộn **`tiêu xay + bột quế (nếu có) + tỏi sả băm + chút dầu hào`**.",
        ],
    },
    {
        "names": ["trứng gà", "trung ga", "trứng", "trung", "cà chua", "ca chua", "tương ớt", "tuong ot", "tương cà", "tuong ca"],
        "label": "Trứng / Cà chua / Tương cà",
        "substitutes": [
            "**Thay Trứng gà khi trộn chả/mọc:** Dùng **`1 muỗng canh bột năng (hoặc bột bắp) + 1 muỗng canh nước lạnh`** để tạo độ kết dính dai giòn.",
            "**Thay Cà chua tươi khi nấu canh/sốt:** Dùng **`2 muỗng canh tương cà (Ketchup) pha nước`** hoặc dùng **dứa (thơm) / me chua**.",
        ],
    },
]


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
# BỘ XỬ LÝ SỰ CỐ MÓN ĂN & SƠ CHẾ KHỬ MÙI (NHÓM 2)
# ============================================================

def _handle_kitchen_rescue(raw_msg: str, msg_norm: str) -> Optional[Dict[str, Any]]:
    for rule in RESCUE_RULES:
        for pat in rule["patterns"]:
            if re.search(pat, msg_norm):
                bullets = "\n".join(f"- {s}" for s in rule["solutions"])
                return {
                    "intent": "kitchen_rescue",
                    "reply": f"🆘 **Cách xử lý: {rule['title']}**\n\n{bullets}",
                    "recipes": [],
                    "suggestions": [
                        "Khi làm món ăn bị cháy thì xử lý như nào?",
                        "Canh bị mặn quá chữa sao?",
                        "Tôi không có xì dầu thì thay bằng gì?",
                    ],
                }

    # Nếu câu hỏi có từ khóa hỏi cách xử lý sự cố chung ("cấp cứu", "bị lỗi", "chữa cháy")
    if any(w in msg_norm for w in ["cap cuu", "chua chay", "bi loi"]):
        burned = RESCUE_RULES[3]
        bullets = "\n".join(f"- {s}" for s in burned["solutions"])
        return {
            "intent": "kitchen_rescue",
            "reply": f"🆘 **Cách xử lý: {burned['problem'] if 'problem' in burned else burned['title']}**\n\n{bullets}",
            "recipes": [],
            "suggestions": [
                "Thịt gà bị hôi xử lý bằng gì?",
                "Canh bị mặn quá chữa sao?",
                "Cơm bị nhão làm thế nào?",
            ],
        }
    return None


# ============================================================
# BỘ XỬ LÝ THAY THẾ NGUYÊN LIỆU KHI THIẾU (NHÓM 2)
# ============================================================

def _extract_missing_ingredient_phrase(raw_msg: str) -> Optional[str]:
    patterns = [
        r"(?:không có|khong co|thiếu|thieu|hết|het|thay thế|thay the|thay)\s+([a-zA-ZÀ-ỹ\s]{2,25}?)(?:\s+thì|\s+thi|\s+bằng|\s+bang|\s+được|\s+duoc|\?|$)",
    ]
    for pat in patterns:
        m = re.search(pat, raw_msg, flags=re.IGNORECASE)
        if m:
            extracted = m.group(1).strip(" .,?!\"'")
            if len(extracted) >= 2:
                return extracted
    return None


def _handle_substitution(raw_msg: str, msg_norm: str) -> Optional[Dict[str, Any]]:
    has_sub_intent = any(
        w in msg_norm
        for w in ["thay", "het ", "khong co", "thieu", "an chay", "mam chay"]
    )
    if not has_sub_intent:
        return None

    for item in SUBSTITUTION_CATALOG:
        for name_kw in item["names"]:
            norm_kw = _normalize(name_kw)
            if norm_kw and re.search(r"\b" + re.escape(norm_kw) + r"\b", msg_norm):
                bullets = "\n".join(f"- {s}" for s in item["substitutes"])
                return {
                    "intent": "ingredient_substitution",
                    "reply": (
                        f"🔄 **Giải pháp thay thế khi bạn không có / thiếu \"{item['label']}\":**\n\n"
                        f"{bullets}\n\n"
                        f"💡 *Mẹo nhỏ: Khi nêm nguyên liệu thay thế, bạn hãy cho khoảng 2/3 lượng dự kiến trước rồi nếm lại cho vừa khẩu vị nhé!*"
                    ),
                    "recipes": [],
                    "suggestions": [
                        "Tôi không có dầu hào thì thay bằng gì?",
                        "Thiếu nước cốt dừa thì thay bằng gì?",
                        "Thịt gà bị hôi xử lý bằng gì?",
                    ],
                }

    # Nếu người dùng hỏi một nguyên liệu nằm ngoài danh mục 17 nhóm trên, bóc tách trực tiếp tên nguyên liệu để trả lời đúng trọng tâm
    extracted = _extract_missing_ingredient_phrase(raw_msg)
    if extracted:
        return {
            "intent": "ingredient_substitution",
            "reply": (
                f"🔄 **Gợi ý khi bạn không có \"{extracted}\":**\n\n"
                f"- **Nếu \"{extracted}\" đóng vai trò tạo vị mặn/đậm đà:** Có thể thay bằng **nước mắm, xì dầu (nước tương), muối + hạt nêm** hoặc **dầu hào**.\n"
                f"- **Nếu \"{extracted}\" đóng vai trò tạo mùi thơm / rau gia vị:** Có thể thay bằng các loại gia vị dậy hương sẵn có trong bếp như **hành tím, tỏi phi, gừng, sả, tiêu xay hoặc hành lá**.\n"
                f"- **Nếu \"{extracted}\" là nguyên liệu rau củ / thịt phụ:** Bạn hoàn toàn có thể lược bỏ hoặc thay bằng loại rau củ/nấm sẵn có trong tủ lạnh theo tỷ lệ khối lượng `1:1` mà không làm hỏng cấu trúc món ăn!"
            ),
            "recipes": [],
            "suggestions": [
                "Tôi không có xì dầu",
                "Thiếu nước cốt dừa thay bằng gì?",
                "Thiếu bột năng thay bằng gì?",
            ],
        }

    return None


# ============================================================
# NHÓM 1: TỦ LẠNH CÓ GÌ? — GỢI Ý MÓN TỪ NGUYÊN LIỆU SẴN CÓ
# ============================================================

def _handle_fridge_search(
    message: str, msg_norm: str, all_recipes: List[Dict[str, Any]], all_ingredients: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    # Không chạy tìm nguyên liệu tủ lạnh nếu câu hỏi mang tính hỏi sự cố / cách xử lý / tại sao
    if any(
        w in msg_norm
        for w in ["bi ", "xu li", "xu ly", "khu mui", "lam sach", "so che", "chua ", "tai sao", "nhu nao"]
    ) and not any(w in msg_norm for w in ["nau mon gi", "nau gi", "lam mon gi"]):
        return None

    detected_ing_names: List[str] = []
    for ing in all_ingredients:
        ing_norm = _normalize(ing["name"])
        if ing_norm and re.search(r"\b" + re.escape(ing_norm) + r"\b", msg_norm):
            detected_ing_names.append(ing["name"])

    synonym_keywords = {
        "thit bo": "Thịt bò",
        "bo": "Thịt bò",
        "thit heo": "Thịt heo",
        "thit lon": "Thịt heo",
        "ba chi": "Thịt ba chỉ",
        "suon": "Sườn heo",
        "thit ga": "Thịt gà",
        "uc ga": "Ức gà / Thịt gà",
        "dui ga": "Đùi gà / Thịt gà",
        "ga": "Thịt gà",
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
            matched_user = False
            for u_ing in detected_ing_names:
                u_norm = _normalize(u_ing)
                if (
                    u_norm in ri_norm
                    or ri_norm in u_norm
                    or ("ga" in u_norm and "thit ga" in ri_norm)
                    or ("heo" in u_norm and ("ba chi" in ri_norm or "suon" in ri_norm or "nac vai" in ri_norm))
                ):
                    matched_user = True
                    break
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
        f"🧊 **Với nguyên liệu bạn đang có ({', '.join(detected_ing_names)})**, bạn có thể chế biến ngay **{len(scored_recipes)} món ngon** sau đây:\n"
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

    return {
        "intent": "fridge_match",
        "reply": "\n".join(lines),
        "recipes": cards,
        "suggestions": [
            f"Quy đổi {top[0][2]['title']} cho 6 người",
            f"Cách nấu {top[0][2]['title']}",
            "Thịt gà bị hôi xử lý bằng gì?",
        ],
    }


# ============================================================
# NHÓM 1: TƯ VẤN MÓN ĂN THEO CALO & DINH DƯỠNG (UC06-B)
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
                "Tôi không có xì dầu thì thay bằng gì?",
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
            "suggestions": ["Thực đơn 3 bữa 1500 kcal", "Món ăn dưới 350 kcal", "Thịt gà bị hôi xử lý sao?"],
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
# NHÓM 1: TÍNH TOÁN & QUY ĐỔI KHẨU PHẦN ĂN (UC06-A)
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
            "Khi làm món ăn bị cháy xử lý thế nào?",
        ],
    }


# ============================================================
# NHÓM 2: HỎI ĐÁP CÁCH NẤU THEO MÓN ĂN / NGỮ CẢNH ĐANG XEM
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
        if any(w in msg_norm for w in ["buoc", "cach nau", "mon nay", "dang xem", "tom tat", "nguyen lieu", "bao lau", "nhu nao", "the nao"]):
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
                    f"💡 *Mẹo nhỏ:* Giữ mức lửa ổn định và chuẩn bị sẵn gia vị trước khi thao tác bước này để món ăn dậy hương chuẩn nhất!"
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
            "Tôi không có xì dầu thì thay bằng gì?",
            "Thịt gà bị hôi xử lý bằng gì?",
        ],
    }


# ============================================================
# MAIN ROUTER
# ============================================================

def generate_chatbot_response(
    message: str,
    context: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
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
                "Bạn có thể hỏi mình trực tiếp bất kỳ vấn đề nào trong bếp:\n"
                "1. 🧊 **Có nguyên liệu này nấu món gì?** *(VD: \"Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?\")*\n"
                "2. 🆘 **Xử lý sự cố & Sơ chế khử mùi:** *(VD: \"Thịt gà của tôi bị hôi xử lý bằng gì?\", \"Khi làm món ăn bị cháy xử lý như nào?\")*\n"
                "3. 🔄 **Thay thế nguyên liệu bị thiếu:** *(VD: \"Tôi không có xì dầu\", \"Thiếu nước cốt dừa thay bằng gì?\")*\n"
                "4. ⚖️ **Quy đổi khẩu phần & Dinh dưỡng:** *(VD: \"Phở bò cho 8 người\", \"Thực đơn 3 bữa 1500 kcal\")*"
            ),
            "recipes": [_format_recipe_card(r) for r in all_recipes[:2]],
            "suggestions": [
                "Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?",
                "Thịt gà của tôi bị hôi có thể xử lý bằng gì?",
                "Tôi không có xì dầu thì thay bằng gì?",
                "Khi làm món ăn bị cháy thì xử lý như nào?",
            ],
        }

    # 0. Guardrail: Từ chối lịch sự câu hỏi ngoài phạm vi ẩm thực
    if _is_off_topic(msg_norm):
        return {
            "intent": "off_topic",
            "reply": (
                "🙏 Xin lỗi bạn, mình là **Trợ lý Đầu bếp AI của CookMate** nên **chỉ giải đáp các câu hỏi liên quan đến món ăn, nguyên liệu, dinh dưỡng và kỹ thuật nấu nướng**.\n\n"
                "Bạn hãy thử hỏi mình:\n"
                "- *\"Thịt gà của tôi bị hôi có thể xử lý bằng gì?\"*\n"
                "- *\"Tôi không có xì dầu / nước cốt dừa thì thay bằng gì?\"*\n"
                "- *\"Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?\"*"
            ),
            "recipes": [],
            "suggestions": [
                "Thịt gà của tôi bị hôi có thể xử lý bằng gì?",
                "Tôi không có xì dầu thì thay bằng gì?",
                "Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?",
            ],
        }

    # 1. Xử lý sự cố nhà bếp & Sơ chế khử mùi (Nhóm 2 - Ưu tiên số 1 để không nhầm với tìm nguyên liệu!)
    rescue = _handle_kitchen_rescue(raw_msg, msg_norm)
    if rescue:
        return rescue

    # 2. Thay thế nguyên liệu khi thiếu (Nhóm 2 - Ưu tiên số 2)
    sub = _handle_substitution(raw_msg, msg_norm)
    if sub:
        return sub

    # 3. Quy đổi khẩu phần ăn (Nhóm 1 - UC06-A)
    if any(kw in msg_norm for kw in ["quy doi", "khau phan", "nguoi an", "suat"]) or re.search(r"\bcho\s*\d+\s*nguoi\b", msg_norm):
        scaled_resp = _handle_portion_scaling(
            raw_msg, msg_norm, all_recipes, current_recipe_id=current_recipe_id
        )
        if scaled_resp:
            return scaled_resp

    # 4. Tư vấn món ăn theo Calo & Dinh dưỡng (Nhóm 1 - UC06-B)
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

    # 5. Hỏi đáp chi tiết cách nấu món ăn cụ thể được nhắc tên trong câu hỏi
    mentioned = _find_mentioned_recipes(msg_norm, all_recipes)
    if mentioned and any(w in msg_norm for w in ["cach nau", "cach lam", "buoc", "cong thuc", "nhu nao", "the nao"]):
        ctx_resp = _handle_recipe_context_question(
            raw_msg, msg_norm, all_recipes, current_recipe_id=current_recipe_id
        )
        if ctx_resp:
            return ctx_resp

    # 6. Có nguyên liệu này nấu món gì? (Nhóm 1 - Fridge / Ingredient Matcher)
    fridge = _handle_fridge_search(raw_msg, msg_norm, all_recipes, all_ingredients)
    if fridge:
        return fridge

    # 7. Hỏi đáp theo ngữ cảnh món đang xem trên màn hình
    ctx_resp = _handle_recipe_context_question(
        raw_msg, msg_norm, all_recipes, current_recipe_id=current_recipe_id
    )
    if ctx_resp:
        return ctx_resp

    # 8. Phản hồi mặc định
    featured = [r for r in all_recipes if r.get("featured")] or all_recipes[:3]
    return {
        "intent": "general_recommend",
        "reply": (
            "👨‍🍳 **Mình sẵn sàng giải đáp cụ thể câu hỏi về món ăn và nấu nướng của bạn!**\n\n"
            "Bạn có thể hỏi trực tiếp như:\n"
            "- 🆘 **Khử mùi / Chữa lỗi món ăn:** *\"Thịt gà bị hôi xử lý bằng gì?\"*, *\"Món ăn bị cháy / bị mặn làm sao?\"*\n"
            "- 🔄 **Thay thế nguyên liệu:** *\"Tôi không có xì dầu\"*, *\"Thiếu nước cốt dừa / bột năng thay bằng gì?\"*\n"
            "- 🧊 **Gợi ý món từ nguyên liệu:** *\"Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?\"*\n"
            "- ⚖️ **Định lượng & Calo:** *\"Phở bò cho 8 người\"*, *\"Thực đơn 3 bữa 1500 kcal\"*"
        ),
        "recipes": [_format_recipe_card(r) for r in featured[:3]],
        "suggestions": [
            "Thịt gà của tôi bị hôi có thể xử lý bằng gì?",
            "Tôi không có xì dầu thì thay bằng gì?",
            "Khi làm món ăn bị cháy thì xử lý như nào?",
            "Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?",
        ],
    }
