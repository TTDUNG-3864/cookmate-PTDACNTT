"""Cooking-domain classifier used before any model call."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_MESSAGE_LENGTH = 2000
OFF_TOPIC_REPLY = (
    "Xin lỗi, CookMate ChefBot chỉ hỗ trợ các câu hỏi liên quan đến món ăn, nguyên liệu, "
    "công thức nấu ăn, dinh dưỡng và kỹ thuật chế biến.\n\n"
    "Mình không hỗ trợ giải toán, lập trình hoặc các chủ đề ngoài lĩnh vực ẩm thực. "
    "Bạn có thể hỏi cách nấu một món ăn, thay thế nguyên liệu hoặc xử lý vấn đề khi nấu nướng nhé!"
)
UNCERTAIN_REPLY = "Bạn muốn hỏi về món ăn, nguyên liệu hay bước nấu nào? Hãy cho mình biết thêm một chút nhé."
EMPTY_REPLY = "Bạn hãy nhập câu hỏi về món ăn hoặc nấu nướng trước nhé."

_GREETINGS = {
    "xin chao", "chao", "chao ban", "hello", "hi", "hey", "cam on", "cam on ban",
    "tam biet", "hen gap lai", "xin cam on",
}
_OFF_TOPIC = (
    r"\b(giai toan|toan hoc|phuong trinh|bac hai|dai so|hinh hoc|tich phan|dao ham|"
    r"viet code|lap trinh|debug|sua loi code|python|java|javascript|c\+\+|html css|"
    r"bitcoin|crypto|chung khoan|co phieu|bau cu|chinh tri|thoi tiet|tin tuc|the thao|"
    r"bai tap tieng anh|viet van|bai luan|essay|dich sang tieng anh)\b"
)
_FOOD = (
    r"\b(nau|che bien|mon an|mon gi|mon chay|an chay|thuan chay|cong thuc|thuc don|"
    r"nguyen lieu|gia vi|thit|ga|bo|heo|lon|vit|ngan|ngong|de|cuu|ca|tom|cua|ghe|muc|oc|"
    r"trung|dau hu|dau phu|nam|rau|cu|qua|pho|bun|com|chao|xoi|mien|hu tieu|mi|banh|"
    r"canh|sup|lau|goi|cuon|che|banh flan|sua chua|rau cau|sinh to|nuoc ep|tra dao|sua hat|"
    r"nuoc cham|nuoc mam|xi dau|nuoc tuong|tuong|sa te|me|chao|nuoc dung|nuoc leo|"
    r"bot nang|bot mi|bot gao|bot nep|dua|nuoc cot dua|"
    r"calo|calories|kcal|dinh duong|chat dam|protein|chat beo|tinh bot|chat xo|khau phan|"
    r"eat clean|giam can|tang can|tieu duong|it dau|khong dau|mam co|ngay ram|dip le|tet|"
    r"so che|uop|bao quan|ra dong|khu mui|khu tanh|hoi|tanh|man|nhat|ngot|chay khet|khet|"
    r"chin|luoc|hap|kho|rim|om|ham|ninh|chien|xao|nuong|noi chien|dao bep|lo nuong|thay the)\b"
)
_COOKING_INTENT = re.compile(
    r"\b(cach|lam sao|the nao|huong dan|giup|tu van|goi y|nau|lam|che bien|xu ly|cuu|"
    r"thay|doi|quy doi|tinh|toi co|minh co|nha co|trong bep|bao nhieu|can gi|co the|bi|"
    r"nen|mon gi|cong thuc|thuc don|khau phan|calo|kcal|bao quan|so che)\b"
)
_INJECTION = re.compile(
    r"(ignore (all )?(previous|prior) instructions|bo qua (cac )?chi dan|"
    r"system prompt|reveal.*prompt|act as|pretend to be|hay bo qua vai tro|"
    r"khong con la chefbot|do anything now)", re.I
)


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(ch for ch in text if ch.isprintable())
    text = text.lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class DomainDecision:
    classification: str
    normalized: str
    message: str = ""
    contains_injection: bool = False


def classify_message(value: str) -> DomainDecision:
    raw = unicodedata.normalize("NFKC", str(value or ""))
    raw = "".join(ch for ch in raw if ch.isprintable()).strip()
    if not raw:
        return DomainDecision("EMPTY", "", EMPTY_REPLY)
    if len(raw) > MAX_MESSAGE_LENGTH:
        return DomainDecision("TOO_LONG", "", f"Câu hỏi tối đa {MAX_MESSAGE_LENGTH} ký tự.")
    normalized = normalize_text(raw)
    if normalized in _GREETINGS:
        return DomainDecision("GREETING", normalized, "Chào bạn! Mình là CookMate ChefBot, sẵn sàng hỗ trợ chuyện nấu nướng.")
    # A clear non-food request wins even when the user adds food words as bait.
    if re.search(_OFF_TOPIC, normalized):
        return DomainDecision("OFF_TOPIC", normalized, OFF_TOPIC_REPLY, bool(_INJECTION.search(raw)))
    food_match = re.search(_FOOD, normalized)
    cooking_intent = _COOKING_INTENT.search(normalized)
    if food_match and cooking_intent:
        return DomainDecision("FOOD_RELATED", normalized, contains_injection=bool(_INJECTION.search(raw)))
    if food_match and len(normalized.split()) <= 5:
        return DomainDecision("FOOD_RELATED", normalized, contains_injection=bool(_INJECTION.search(raw)))
    if _INJECTION.search(raw):
        # Do not pass control-changing requests to the model. A concrete food question can still be answered safely.
        return DomainDecision("UNCERTAIN", normalized, UNCERTAIN_REPLY, True)
    return DomainDecision("UNCERTAIN", normalized, UNCERTAIN_REPLY)

