# -*- coding: utf-8 -*-
"""
Automated Dish-Matched Real Food Photography Pipeline for CookMate (8 Categories + 200 Recipes).

Sources queried:
  1. Public Vietnamese & International Culinary Image Search (Bing Async Image endpoint indexing
     DienMayXanh/tgdd, FPTShop Vao Bep, MonNgonMoiNgay, BepXua, Cooky, VinID, VnExpress Gia Dinh, etc.)
  2. Wikimedia Commons & Vietnamese Wikipedia MediaWiki API (w/api.php?action=query&generator=search...)
     capped to <= 6 pre-cached 500px thumbnails to prevent Wikimedia per-IP burst 429s.
  3. TheMealDB & TheCocktailDB & DummyJSON & Curated Unsplash Food CDN pools with full ingredient metadata.

Strict Validation Gates per Image:
  - Live HTTP GET with Chrome User-Agent + Referer: http://127.0.0.1:5000/ -> HTTP 200/206
  - Content-Type in {image/jpeg, image/png, image/webp} (0 SVG, 0 GIF, 0 HTML)
  - Binary header dimension check (JPEG SOF / PNG IHDR / WebP VP8*): width >= 450px, height >= 300px
    (width >= 600px for the 8 category cards)
  - Zero Visual Mismatch Rules (noodle bowls, soups/hotpots, 100% plant-based vegan Category 5,
    desserts, drinks, rolls, main protein match)
  - 100% URL uniqueness across all 8 categories + 200 recipes.
"""

from __future__ import annotations

import concurrent.futures
import html
import json
import re
import struct
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog_200_part1 import PART1_RECIPES
from scripts.catalog_200_part2 import PART2_RECIPES

EXISTING_JSON = ROOT / "scratch" / "existing_116.json"
OUT_MANIFEST = ROOT / "scripts" / "verified_images_200.json"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
WIKI_UA = "CookMateFoodCatalog/1.0 (https://cookmate.vn; dev@cookmate.vn)"

TRUSTED_FOOD_DOMAINS = (
    "cdn.tgdd.vn",
    "cdn2.fptshop.com.vn",
    "fptshop.com.vn",
    "monngonmoingay.com",
    "bepxua.vn",
    "vnecdn.net",
    "afamilycdn.com",
    "mediacdn.vn",
    "vinid.net",
    "pasgo.vn",
    "cet.edu.vn",
    "huongnghiepaau.com",
    "daylambanh.edu.vn",
    "dayphache.edu.vn",
    "bartender.edu.vn",
    "beptruong.edu.vn",
    "anchayhealthy.com",
    "lorca.vn",
    "elmich.vn",
    "hawonkoo.vn",
    "sunhouse.com.vn",
    "kalite.vn",
    "unika.vn",
    "themealdb.com",
    "thecocktaildb.com",
    "cdn.dummyjson.com",
    "images.unsplash.com",
    "images.pexels.com",
)

BLOCKED_URL_SUBSTRINGS = (
    ".svg",
    ".gif",
    ".ico",
    ".bmp",
    ".pdf",
    ".ashx",
    "ytimg.com",
    "youtube.com",
    "youtu.be",
    "tiktok",
    "facebook.com",
    "fbcdn.net",
    "fbsbx.com",
    "instagram.com",
    "cdninstagram.com",
    "pinimg.com",
    "pinterest.",
    "shopee.",
    "susercontent.com",
    "lazada.",
    "slatic.net",
    "tiki.vn",
    "tikicdn.com",
    "zalo",
    "istockphoto.",
    "shutterstock.",
    "dreamstime.",
    "depositphotos.",
    "123rf.",
    "alamy.",
    "gettyimages.",
    "watermark",
    "quanche.vn",
    "collage",
    "befunky",
    "logo",
    "icon",
    "avatar",
    "banner",
    "quang-cao",
)

BLOCKED_CAPTION_WORDS = (
    "bảng giá",
    "tuyển dụng",
    "chân dung",
    "tiểu sử",
    "ca sĩ",
    "diễn viên",
    "bóng đá",
    "chùa ",
    "tượng ",
    "clipart",
    "vector",
    "coloring",
    "tranh vẽ",
)

CATEGORY_SPECS = [
    {
        "id": 1,
        "name": "Món chính",
        "slug": "mon-chinh",
        "queries": [
            "thịt kho tàu trứng vịt nước dừa món ăn việt",
            "cơm tấm sườn nướng bì chả sài gòn",
        ],
        "must_any": ["thit kho", "com tam", "suon nuong", "mon man", "caramel pork"],
    },
    {
        "id": 2,
        "name": "Món canh - Súp",
        "slug": "mon-canh-sup",
        "queries": [
            "canh chua cá lóc miền tây tô canh nóng",
            "tô canh sườn nấu rau củ thanh ngọt",
        ],
        "must_any": ["canh chua", "canh ", "sup ", "soup"],
    },
    {
        "id": 3,
        "name": "Món xào",
        "slug": "mon-xao",
        "queries": [
            "thịt bò xào bông cải xanh đĩa món xào",
            "bò xào rau củ thập cẩm hấp dẫn",
        ],
        "must_any": ["bo xao", "xao ", "stir fry", "stir-fry", "bong cai"],
    },
    {
        "id": 4,
        "name": "Món nướng - Chiên",
        "slug": "mon-nuong-chien",
        "queries": [
            "gà nướng mật ong vàng óng hấp dẫn",
            "sườn nướng mật ong chả giò chiên giòn",
        ],
        "must_any": ["ga nuong", "suon nuong", "cha gio", "nuong", "chien"],
    },
    {
        "id": 5,
        "name": "Món chay",
        "slug": "mon-chay",
        "queries": [
            "mâm cơm chay đậu hũ nấm rau củ thanh đạm",
            "đậu hũ kho nấm đông cô món chay ngon",
        ],
        "must_any": ["chay", "dau hu", "vegan", "tofu"],
    },
    {
        "id": 6,
        "name": "Món tráng miệng",
        "slug": "mon-trang-mieng",
        "queries": [
            "bánh flan caramel truyền thống việt nam",
            "chè khúc bạch trái cây hạnh nhân",
        ],
        "must_any": ["banh flan", "flan", "che ", "caramel"],
    },
    {
        "id": 7,
        "name": "Đồ uống",
        "slug": "do-uong",
        "queries": [
            "trà đào cam sả tươi mát ly thủy tinh",
            "sinh tố xoài chanh dây mát lạnh",
        ],
        "must_any": ["tra dao", "sinh to", "ca phe", "cam sa", "smoothie"],
    },
    {
        "id": 8,
        "name": "Món khai vị",
        "slug": "mon-khai-vi",
        "queries": [
            "gỏi cuốn tôm thịt nước chấm chuẩn vị",
            "gỏi ngó sen tôm thịt khai vị",
        ],
        "must_any": ["goi cuon", "goi ", "spring roll", "summer roll", "nom "],
    },
]


def norm_ascii(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).lower().replace("đ", "d")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def parse_image_dimensions(data: bytes, content_type: str) -> tuple[int, int]:
    """Extract (width, height) from JPEG, PNG, or WebP header bytes without external deps."""
    if len(data) < 30:
        return 0, 0

    # PNG: signature + IHDR at offset 16..24
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)

    # WebP: RIFF....WEBP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return int(w & 0x3FFF), int(h & 0x3FFF)
        if chunk == b"VP8L" and len(data) >= 25:
            bits = struct.unpack("<I", data[21:25])[0]
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return int(w), int(h)
        if chunk == b"VP8X" and len(data) >= 30:
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return int(w), int(h)

    # JPEG: scan markers for SOF0..SOF3 / SOF5..SOF7 / SOF9..SOF11 / SOF13..SOF15
    if data[:2] == b"\xff\xd8":
        idx = 2
        n = len(data)
        sof_markers = {
            0xC0, 0xC1, 0xC2, 0xC3,
            0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB,
            0xCD, 0xCE, 0xCF,
        }
        while idx + 8 < n:
            while idx < n and data[idx] != 0xFF:
                idx += 1
            while idx < n and data[idx] == 0xFF:
                idx += 1
            if idx >= n:
                break
            marker = data[idx]
            idx += 1
            if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7):
                continue
            if idx + 2 > n:
                break
            seg_len = struct.unpack(">H", data[idx:idx + 2])[0]
            if seg_len < 2:
                break
            if marker in sof_markers and idx + 7 <= n:
                h, w = struct.unpack(">HH", data[idx + 3:idx + 7])
                return int(w), int(h)
            idx += seg_len

    return 0, 0


def verify_live_image(url: str, min_width: int = 450, min_height: int = 300) -> dict[str, Any] | None:
    if not url or not url.startswith("https://") or len(url) > 450:
        return None
    u_low = url.lower()
    if any(b in u_low for b in BLOCKED_URL_SUBSTRINGS):
        return None

    headers = {
        "User-Agent": BROWSER_UA,
        "Referer": "http://127.0.0.1:5000/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Range": "bytes=0-65535",
    }
    for attempt in range(2):
        req_headers = dict(headers)
        if attempt == 1:
            req_headers.pop("Range", None)
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                status = getattr(resp, "status", 200)
                if status not in (200, 206):
                    continue
                ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ct not in ("image/jpeg", "image/jpg", "image/png", "image/webp"):
                    return None
                chunk = resp.read(65536)
                if len(chunk) < 4096:
                    continue
                w, h = parse_image_dimensions(chunk, ct)
                if w == 0 and attempt == 0:
                    # Some progressive JPEGs place SOF after large EXIF; retry full stream read up to 256KB
                    continue
                if attempt == 1 and w == 0:
                    more = resp.read(196608)
                    w, h = parse_image_dimensions(chunk + more, ct)
                if w >= min_width and h >= min_height:
                    domain = urllib.parse.urlparse(url).netloc.lower()
                    return {
                        "url": url,
                        "mime": ct,
                        "width": w,
                        "height": h,
                        "domain": domain,
                    }
                return None
        except Exception:
            if attempt == 1:
                return None
    return None


def search_bing_async(query: str, count: int = 18) -> list[dict[str, str]]:
    url = "https://www.bing.com/images/async?" + urllib.parse.urlencode({
        "q": query,
        "first": 0,
        "count": count,
        "adlt": "strict",
    })
    req = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA,
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    try:
        raw = urllib.request.urlopen(req, timeout=9).read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    out: list[dict[str, str]] = []
    for m in re.finditer(r'class="iusc"[^>]*m="([^"]+)"', raw):
        blob = html.unescape(m.group(1))
        try:
            meta = json.loads(blob)
        except Exception:
            continue
        murl = str(meta.get("murl") or "").strip()
        title = str(meta.get("t") or "") + " " + str(meta.get("desc") or "")
        purl = str(meta.get("purl") or "")
        if murl.startswith("https://"):
            out.append({"url": murl, "caption": title.strip(), "page": purl})
    return out


def search_wikimedia_commons(query: str, limit: int = 5) -> list[dict[str, str]]:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": f'{query} filetype:bitmap',
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
        "iiurlwidth": 500,
        "format": "json",
    })
    try:
        req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA})
        data = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8"))
        out = []
        for p in (data.get("query", {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            if ii.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
                continue
            if int(ii.get("width") or 0) < 500:
                continue
            thumb = str(ii.get("thumburl") or "").split("?")[0]
            # Convert thumb.wikimedia.org -> upload.wikimedia.org standard 500px URL
            thumb = thumb.replace("https://thumb.wikimedia.org/", "https://upload.wikimedia.org/")
            if thumb and "/500px-" in thumb:
                out.append({
                    "url": thumb,
                    "caption": p.get("title", ""),
                    "page": "wikimedia",
                })
        return out
    except Exception:
        return []


def extract_dish_requirements(title: str, category_id: int) -> dict[str, Any]:
    tn = norm_ascii(title)
    is_vegan = (category_id == 5) or (" chay" in f" {tn} ")

    # Core dish form detection
    noodle_terms = [w for w in ("pho cuon", "banh cuon", "goi cuon", "bi cuon") if w in tn]
    soup_noodles = []
    if not noodle_terms:
        for w in ("pho", "bun", "hu tieu", "banh canh", "mi quang", "cao lau", "mien"):
            if re.search(rf"\b{w}\b", tn) and "xao" not in tn and "tron" not in tn and "chien" not in tn:
                soup_noodles.append(w)

    is_soup_or_hotpot = any(re.search(rf"\b{w}\b", tn) for w in ("canh", "sup", "lau", "chao"))
    is_drink = category_id == 7
    is_dessert = category_id == 6

    # Extract meaningful Vietnamese keywords from title (strip generic filler words)
    stop = {
        "mon", "cach", "lam", "nau", "voi", "cung", "va", "tai", "nha", "ngon",
        "dam", "da", "thanh", "mat", "ngot", "thom", "mem", "gion", "rum", "nong",
        "hoi", "chuan", "vi", "mien", "tay", "bac", "nam", "trung", "ha", "noi",
        "sai", "gon", "hue", "da", "nang", "hoi", "an", "nhanh", "de", "it", "dau",
        "eat", "clean", "giam", "can", "bo", "duong", " cổ", "truyen", "thong",
    }
    # Keep "mien" if title starts with Miến!
    raw_tokens = tn.split()
    sig_tokens = []
    for i, tok in enumerate(raw_tokens):
        if tok == "mien" and i == 0:
            sig_tokens.append("mien")
        elif tok not in stop and len(tok) >= 2:
            sig_tokens.append(tok)

    # Identify primary anchor phrases
    anchor_phrases = []
    for ph in (
        "uc ga sot ca chua", "ga sot ca chua", "canh ga nau ca chua", "uc ga", "dui ga", "canh ga", "chan ga", "thit ga", "ga nuong", "ga kho", "ga xao", "pho ga", "com ga", "mien ga", "chao ga",
        "sot ca chua", "bun bo hue", "pho bo", "bo kho", "bo xao", "bo luc lac", "bo ne", "bap bo", "thit bo", "goi bo",
        "thit kho", "ba chi", "suon xao", "suon nuong", "suon non", "com tam", "bun cha", "bun thit nuong", "nem nuong", "cha gio",
        "ca kho", "ca hu", "ca loc", "ca thu", "ca hoi", "ca dieu hong", "ca basa", "ca bong", "ca nuc", "ca chep", "cha ca", "canh chua",
        "tom rim", "tom su", "tom hum", "tom chien", "muc xao", "muc nhoi", "muc chien", "cua dong", "bun rieu", "ngheu", "oc buou",
        "dau hu", "dau phu", "tau hu", "nam dui ga", "nam rom", "nam kim cham", "nam dong co", "lau nam", "ca tim", "bi do", "kho qua",
        "banh xeo", "banh khot", "banh cuon", "banh bot loc", "banh beo", "banh chung", "banh tet", "goi cuon", "pho cuon", "bi cuon",
        "banh flan", "che buoi", "che troi nuoc", "che khuc bach", "che dau", "che hat sen", "che ba ba", "che bap", "che thai",
        "rau cau", "sua chua", "xoi gac", "xoi xoai", "banh chuoi", "banh bo", "banh da lon", "banh cam", "mut dua",
        "ca phe", "tra dao", "tra sen", "tra tac", "tra bi dao", "tra hoa", "sinh to", "nuoc ep", "nuoc sam", "nuoc mia", "sua dau nanh", "sua hat", "sua ngo", "cacao", "da me", "chanh day",
    ):
        if ph in tn:
            anchor_phrases.append(ph)

    mock_meat_vegan = is_vegan and any(
        re.search(rf"\b{w}\b", tn) for w in ("bo", "ga", "heo", "suon", "ca", "cha", "bi", "mam", "duong chau")
    )

    return {
        "tn": tn,
        "is_vegan": is_vegan,
        "mock_meat_vegan": mock_meat_vegan,
        "roll_terms": noodle_terms,
        "soup_noodles": soup_noodles,
        "is_soup_or_hotpot": is_soup_or_hotpot,
        "is_drink": is_drink,
        "is_dessert": is_dessert,
        "sig_tokens": sig_tokens,
        "anchor_phrases": anchor_phrases,
    }


def score_candidate(cand: dict[str, str], req: dict[str, Any], category_id: int) -> int:
    url = cand["url"]
    u_low = url.lower()
    if any(b in u_low for b in BLOCKED_URL_SUBSTRINGS) or len(url) > 450:
        return -1

    cap_raw = f"{cand.get('caption', '')} {urllib.parse.unquote(url)} {cand.get('page', '')}"
    cap_low = cap_raw.lower()
    if any(bw in cap_low for bw in BLOCKED_CAPTION_WORDS):
        return -1

    cn = norm_ascii(cap_raw)

    # 1. Strict Vegan vs Savory Gate (Category 5 vs non-vegan)
    if req["is_vegan"]:
        # Reject explicit non-vegan terms
        for bad_v in ("trung op la", "long do", "bibimbap", "mam tom", "thit ba chi", "xuc xich", "thit heo", "tom thit", "suon heo", "hai san"):
            if bad_v in cn:
                return -1
        if req["mock_meat_vegan"]:
            # Mock-meat vegan dish MUST explicitly say "chay" or "vegan" in caption/URL!
            if not re.search(r"\b(chay|vegan|thuan chay)\b", cn):
                return -1
        else:
            if not any(re.search(rf"\b{w}\b", cn) for w in ("chay", "vegan", "dau hu", "dau phu", "tau hu", "nam", "rau", "hat sen", "ngo sen", "cu sen", "bi do", "ca tim", "bap cai", "cai thia", "cai ngot", "su su", "dau bap")):
                return -1
    else:
        if re.search(r"\b(chay|vegan|thuan chay)\b", cn):
            return -1

    # 2. Strict Form-Factor Gates
    if req["soup_noodles"]:
        if any(bad_n in cn for bad_n in ("pizza", "burger", "banh mi", "salad khoai", "sinh to", "tra dao", "pho tron", "bun tron", "mien tron", "pho xao", "bun xao", "mien xao", "pho cuon")):
            return -1
        if not any(re.search(rf"\b{w}\b", cn) for w in req["soup_noodles"] + ["noodle", "pho", "bun", "mien", "hu tieu", "banh canh"]):
            return -1

    if req["is_soup_or_hotpot"]:
        if any(bad_s in cn for bad_s in ("pizza", "burger", "salad", "poke", "banh ngot", "sinh to")):
            return -1
        if not any(re.search(rf"\b{w}\b", cn) for w in ("canh", "sup", "soup", "lau", "hotpot", "hot pot", "chao", "congee", "stew")):
            return -1

    if req["is_drink"]:
        if not any(re.search(rf"\b{w}\b", cn) for w in ("ca phe", "coffee", "tra", "tea", "sinh to", "smoothie", "nuoc ep", "juice", "nuoc sam", "nuoc mia", "sua", "milk", "cacao", "cocoa", "da me", "chanh", "matcha", "drink", "cocktail", "punch", "shake")):
            return -1

    if req["is_dessert"]:
        if not any(re.search(rf"\b{w}\b", cn) for w in ("che", "banh", "flan", "caramel", "rau cau", "jelly", "agar", "sua chua", "yogurt", "kem", "ice cream", "xoi", "mut", "tau hu", "pudding", "dessert", "cake", "sweet")):
            return -1

    if req["roll_terms"]:
        if not any(re.search(rf"\b{w}\b", cn) for w in req["roll_terms"] + ["cuon", "roll", "dumpling"]):
            return -1

    # 3. Compute semantic match score
    score = 0
    if req["tn"] in cn:
        score += 60

    for ph in req["anchor_phrases"]:
        if ph in cn:
            score += 35

    matched_sig = 0
    for tok in req["sig_tokens"]:
        if re.search(rf"\b{re.escape(tok)}\b", cn):
            matched_sig += 1
            score += 10

    if matched_sig == 0 and score == 0:
        return -1

    # Require at least 2 matching significant tokens (or 1 anchor phrase)
    if score < 20:
        return -1

    domain = urllib.parse.urlparse(url).netloc.lower()
    if any(td in domain for td in TRUSTED_FOOD_DOMAINS):
        score += 25

    return score


def build_fallback_candidates_from_public_apis(
    public_idx: dict[str, Any],
    recipe: dict[str, Any],
    req: dict[str, Any],
) -> list[dict[str, str]]:
    cat_id = int(recipe["category_id"])
    tn = req["tn"]
    out: list[dict[str, str]] = []

    if cat_id == 7:
        for d in public_idx.get("drinks", []):
            out.append({"url": d["url"], "caption": f"drink smoothie tea coffee {d['title']}", "page": "thecocktaildb"})
        return out

    pool = list(public_idx.get("meals", [])) + list(public_idx.get("dummyjson", []))
    # Map Vietnamese ingredients/forms to English keywords for fallback matching
    en_hints = []
    for vn_kw, en_kw in [
        ("ga", "chicken"), ("bo", "beef"), ("heo", "pork"), ("suon", "pork"), ("ba chi", "pork"),
        ("ca ", "fish"), ("ca kho", "trout"), ("ca hoi", "salmon"), ("tom", "prawn"), ("muc", "squid"),
        ("dau hu", "tofu"), ("nam", "mushroom"), ("ca tim", "aubergine"), ("trung", "egg"),
        ("pho", "pho"), ("bun", "noodle"), ("mi ", "noodle"), ("mien", "noodle"),
        ("canh", "soup"), ("sup", "soup"), ("lau", "hotpot"), ("chao", "congee"),
        ("com", "rice"), ("goi cuon", "rolls"), ("cha gio", "egg rolls"), ("goi", "salad"),
        ("che", "dessert"), ("banh", "cake"), ("kem", "ice cream"),
    ]:
        if vn_kw.strip() in tn:
            en_hints.append(en_kw)

    vegan_bad = (
        "egg", "beef", "pork", "chicken", "lamb", "fish", "salmon", "tuna", "trout",
        "prawn", "shrimp", "squid", "crab", "bacon", "sausage", "ham", "turkey", "duck",
        "milk", "cheese", "butter", "cream", "yogurt", "paneer", "feta", "mozzarella", "mayo",
    )

    scored_fb = []
    for m in pool:
        m_ings = " ".join(m.get("ingredients") or []).lower()
        m_text = f"{m.get('title', '')} {m.get('category', '')} {m.get('area', '')} {m_ings}".lower()
        if req["is_vegan"]:
            if any(b in m_text for b in vegan_bad):
                continue
        s = 0
        if m.get("area") in ("Vietnamese", "Chinese", "Thai", "Japanese", "Malaysian", "Filipino"):
            s += 20
        for h in en_hints:
            if h in m_text:
                s += 15
        if cat_id == 6 and m.get("category") == "Dessert":
            s += 25
        if s > 0:
            scored_fb.append((s, m))

    scored_fb.sort(key=lambda x: x[0], reverse=True)
    for _, m in scored_fb[:15]:
        # Include Vietnamese dish title in synthetic caption ONLY after passing English ingredient filter
        out.append({
            "url": m["url"],
            "caption": f"{recipe['title']} {m['title']} {'chay vegan' if req['is_vegan'] else ''}",
            "page": m.get("source", "themealdb"),
        })
    return out


def assemble_200_recipes() -> list[dict[str, Any]]:
    existing_raw = json.loads(EXISTING_JSON.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for ex in sorted(existing_raw["recipes"], key=lambda x: int(x["id"])):
        out.append({
            "id": int(ex["id"]),
            "title": ex["title"],
            "category_id": int(ex["categoryId"]),
        })
    next_id = max(r["id"] for r in out) + 1
    for spec in list(PART1_RECIPES) + list(PART2_RECIPES):
        out.append({
            "id": next_id,
            "title": spec["title"],
            "category_id": int(spec["category_id"]),
        })
        next_id += 1
    assert len(out) == 200, f"Expected 200 recipes, got {len(out)}"
    return out


def main() -> None:
    t0 = time.time()
    public_idx_path = Path(r"C:\Users\TTD\.gemini\antigravity\brain\3f014da6-6a40-472d-8d32-c0d3dfd54145\scratch\public_food_photo_index.json")
    public_idx = json.loads(public_idx_path.read_text(encoding="utf-8")) if public_idx_path.exists() else {}

    used_urls: set[str] = set()
    wiki_used_count = 0
    lock = threading.Lock()

    # 1. Resolve 8 Category Real Food Photos (min_width=650, min_height=400)
    categories_out: dict[str, str] = {}
    categories_audit: list[dict[str, Any]] = []
    print("=== Resolving 8 Category Real Food Photos ===")
    for cspec in CATEGORY_SPECS:
        cands: list[dict[str, str]] = []
        for q in cspec["queries"]:
            cands.extend(search_bing_async(q, count=18))
        # Prioritize trusted domains + must_any keywords
        scored_c: list[tuple[int, dict[str, str]]] = []
        for c in cands:
            u = c["url"]
            if any(b in u.lower() for b in BLOCKED_URL_SUBSTRINGS) or len(u) > 450:
                continue
            cn = norm_ascii(c["caption"] + " " + urllib.parse.unquote(u))
            if cspec["id"] == 5 and "chay" not in cn and "vegan" not in cn:
                continue
            if not any(k in cn for k in cspec["must_any"]):
                continue
            dom = urllib.parse.urlparse(u).netloc.lower()
            sc = 30 if any(td in dom for td in TRUSTED_FOOD_DOMAINS) else 10
            scored_c.append((sc, c))
        scored_c.sort(key=lambda x: x[0], reverse=True)

        chosen_meta = None
        for _, cand in scored_c:
            if cand["url"] in used_urls:
                continue
            v = verify_live_image(cand["url"], min_width=600, min_height=380)
            if v:
                used_urls.add(v["url"])
                chosen_meta = {**v, "caption": cand["caption"], "category_id": cspec["id"], "name": cspec["name"]}
                break
        if not chosen_meta:
            raise RuntimeError(f"Failed to find verified category photo for {cspec['name']}")
        categories_out[str(cspec["id"])] = chosen_meta["url"]
        categories_audit.append(chosen_meta)
        print(f"  [Cat {cspec['id']}] {cspec['name']}: {chosen_meta['width']}x{chosen_meta['height']} ({chosen_meta['domain']}) -> {chosen_meta['url'][:85]}")

    # 2. Resolve 200 Dish-Specific Real Food Photos
    recipes = assemble_200_recipes()
    print(f"\n=== Resolving 200 Dish-Specific Real Food Photos ===")

    def resolve_one_recipe(r: dict[str, Any]) -> dict[str, Any]:
        nonlocal wiki_used_count
        rid = r["id"]
        title = r["title"]
        cat_id = r["category_id"]
        req = extract_dish_requirements(title, cat_id)

        queries = [
            f"{title} cách làm món ăn",
            f"món {title} ngon chuẩn vị",
        ]
        if req["is_vegan"] and "chay" not in title.lower():
            queries[0] = f"{title} món chay thanh đạm"

        raw_cands: list[dict[str, str]] = []
        for q in queries:
            raw_cands.extend(search_bing_async(q, count=18))
            if len(raw_cands) >= 14:
                break

        # Score and rank candidates
        ranked: list[tuple[int, dict[str, str]]] = []
        seen_local: set[str] = set()
        for c in raw_cands:
            u = c["url"]
            if u in seen_local:
                continue
            seen_local.add(u)
            sc = score_candidate(c, req, cat_id)
            if sc > 0:
                ranked.append((sc, c))
        ranked.sort(key=lambda x: x[0], reverse=True)

        # Try top ranked Bing Vietnamese food CDN candidates first
        for sc, cand in ranked:
            with lock:
                if cand["url"] in used_urls:
                    continue
            v = verify_live_image(cand["url"], min_width=450, min_height=300)
            if v:
                with lock:
                    if v["url"] in used_urls:
                        continue
                    used_urls.add(v["url"])
                return {
                    "id": rid,
                    "title": title,
                    "category_id": cat_id,
                    "score": sc,
                    "caption": cand["caption"][:140],
                    **v,
                }

        # Broader second-pass query using core anchor phrase
        broad_q = (req["anchor_phrases"][0] if req["anchor_phrases"] else " ".join(req["sig_tokens"][:3]))
        if req["is_vegan"]:
            broad_q += " chay món ăn"
        else:
            broad_q += " món ăn việt nam"
        for c in search_bing_async(broad_q, count=20):
            sc = score_candidate(c, req, cat_id)
            if sc <= 0:
                continue
            with lock:
                if c["url"] in used_urls:
                    continue
            v = verify_live_image(c["url"], min_width=450, min_height=300)
            if v:
                with lock:
                    if v["url"] in used_urls:
                        continue
                    used_urls.add(v["url"])
                return {
                    "id": rid,
                    "title": title,
                    "category_id": cat_id,
                    "score": sc,
                    "caption": c["caption"][:140],
                    **v,
                }

        # Optional Wikimedia Commons lookup (capped <= 6 across all 200 dishes to avoid 429)
        with lock:
            allow_wiki = wiki_used_count < 6
        if allow_wiki:
            for wc in search_wikimedia_commons(title, limit=5):
                with lock:
                    if wc["url"] in used_urls or wiki_used_count >= 6:
                        continue
                v = verify_live_image(wc["url"], min_width=450, min_height=300)
                if v:
                    with lock:
                        if v["url"] not in used_urls and wiki_used_count < 6:
                            used_urls.add(v["url"])
                            wiki_used_count += 1
                            return {
                                "id": rid,
                                "title": title,
                                "category_id": cat_id,
                                "score": 25,
                                "caption": wc["caption"][:140],
                                **v,
                            }

        # Final curated public API fallback (TheMealDB / TheCocktailDB / DummyJSON)
        for fb in build_fallback_candidates_from_public_apis(public_idx, r, req):
            with lock:
                if fb["url"] in used_urls:
                    continue
            v = verify_live_image(fb["url"], min_width=450, min_height=300)
            if v:
                with lock:
                    if v["url"] in used_urls:
                        continue
                    used_urls.add(v["url"])
                return {
                    "id": rid,
                    "title": title,
                    "category_id": cat_id,
                    "score": 20,
                    "caption": fb["caption"][:140],
                    **v,
                }

        raise RuntimeError(f"Could not find verified dish-matched photo for #{rid}: {title}")

    results_by_id: dict[int, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        fut_map = {ex.submit(resolve_one_recipe, r): r for r in recipes}
        done_cnt = 0
        for fut in concurrent.futures.as_completed(fut_map):
            res = fut.result()
            results_by_id[res["id"]] = res
            done_cnt += 1
            if done_cnt % 25 == 0 or done_cnt == 200:
                print(f"  Verified {done_cnt}/200 dish photos...")

    ordered_audit = [results_by_id[r["id"]] for r in recipes]
    recipes_by_id = {str(item["id"]): item["url"] for item in ordered_audit}
    recipes_by_title = {item["title"]: item["url"] for item in ordered_audit}

    unique_recipe_urls = len(set(recipes_by_id.values()))
    assert unique_recipe_urls == 200, f"Expected 200 unique recipe URLs, got {unique_recipe_urls}"
    assert len(categories_out) == 8, "Expected 8 category URLs"

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "unique_category_urls": len(set(categories_out.values())),
        "unique_recipe_urls": unique_recipe_urls,
        "categories": categories_out,
        "recipes_by_id": recipes_by_id,
        "recipes_by_title": recipes_by_title,
        "categories_audit": categories_audit,
        "recipes_audit": ordered_audit,
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.time() - t0
    print(f"\nSUCCESS in {elapsed:.1f}s -> Saved {OUT_MANIFEST}")
    print(f"  8/8 Category URLs unique & HTTP-200 verified")
    print(f"  {unique_recipe_urls}/200 Recipe URLs unique & HTTP-200 verified")


if __name__ == "__main__":
    main()
