# -*- coding: utf-8 -*-
"""
Extend verified dish photography manifest from 200 -> 300 unique HTTP-200 HTTPS photos.
Reuses verified IDs 1..200 + 8 categories from scripts/verified_images_200.json,
discovers & verifies 100 unique dish-matched real photos for regional dishes 201..300,
and writes scripts/verified_images_300.json.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog_300_regional import REGIONAL_100_RECIPES
from scripts.fetch_verified_dish_images import (
    BLOCKED_URL_SUBSTRINGS,
    TRUSTED_FOOD_DOMAINS,
    extract_dish_requirements,
    norm_ascii,
    score_candidate,
    search_bing_async,
    verify_live_image,
)

IN_MANIFEST_200 = ROOT / "scripts" / "verified_images_200.json"
OUT_MANIFEST_300 = ROOT / "scripts" / "verified_images_300.json"


def _core_dish_name(title: str) -> str:
    # Strip trailing poetic adjectives for broader culinary search if needed
    words = title.replace("/", " ").split()
    return " ".join(words[:5])


def main() -> None:
    t0 = time.time()
    base = json.loads(IN_MANIFEST_200.read_text(encoding="utf-8"))
    categories_out: dict[str, str] = dict(base["categories"])
    categories_audit: list[dict[str, Any]] = list(base.get("categories_audit") or [])
    existing_audit: list[dict[str, Any]] = list(base.get("recipes_audit") or [])

    used_urls: set[str] = set(categories_out.values())
    results_by_id: dict[int, dict[str, Any]] = {}
    for item in existing_audit:
        rid = int(item["id"])
        results_by_id[rid] = item
        used_urls.add(item["url"])
    for r_id_str, u in (base.get("recipes_by_id") or {}).items():
        rid = int(r_id_str)
        used_urls.add(u)
        if rid not in results_by_id:
            results_by_id[rid] = {"id": rid, "title": "", "url": u}

    print(f"Loaded {len(results_by_id)} existing verified recipe photos + {len(categories_out)} category photos.")
    lock = threading.Lock()

    def resolve_regional(spec: dict[str, Any]) -> dict[str, Any]:
        rid = int(spec["id"])
        title = spec["title"]
        cat_id = int(spec["category_id"])
        req = extract_dish_requirements(title, cat_id)
        core_name = _core_dish_name(title)

        queries = [
            f"{title} cách làm món ăn",
            f"món {core_name} ngon chuẩn vị",
            f"cách nấu {core_name} đặc sản",
            f"{core_name} ẩm thực việt nam",
        ]
        if req["is_vegan"]:
            queries.insert(0, f"{core_name} món chay ngon")

        seen_local: set[str] = set()
        for q_idx, q in enumerate(queries):
            cands = search_bing_async(q, count=22)
            ranked: list[tuple[int, dict[str, str]]] = []
            for c in cands:
                u = c["url"]
                if not u.startswith("https://") or u in seen_local:
                    continue
                seen_local.add(u)
                if any(b in u.lower() for b in BLOCKED_URL_SUBSTRINGS) or len(u) > 460:
                    continue
                sc = score_candidate(c, req, cat_id)
                if sc <= 0 and q_idx >= 2:
                    # Relaxed domain+keyword score on 3rd/4th query while still enforcing vegan & non-SVG
                    cn = norm_ascii(c["caption"] + " " + urllib.parse.unquote(u))
                    if req["is_vegan"] and any(bad in cn for bad in ("thit ", "tom ", "ca ", "bo ", "ga ", "heo ", "muc ")):
                        continue
                    core_toks = [t for t in norm_ascii(core_name).split() if len(t) >= 3]
                    hits = sum(1 for t in core_toks if t in cn)
                    if hits >= 2:
                        dom = urllib.parse.urlparse(u).netloc.lower()
                        sc = 18 + (15 if any(td in dom for td in TRUSTED_FOOD_DOMAINS) else 0) + hits * 4
                if sc > 0:
                    ranked.append((sc, c))

            ranked.sort(key=lambda x: x[0], reverse=True)
            for sc, cand in ranked:
                with lock:
                    if cand["url"] in used_urls:
                        continue
                v = verify_live_image(cand["url"], min_width=420, min_height=280)
                if v and v["url"].startswith("https://"):
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

        raise RuntimeError(f"Could not resolve verified https photo for regional dish #{rid}: {title}")

    print("=== Resolving 100 New Regional Specialty Photos (IDs 201..300) ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(resolve_regional, spec): spec for spec in REGIONAL_100_RECIPES}
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            res = fut.result()
            results_by_id[res["id"]] = res
            done += 1
            if done % 20 == 0 or done == 100:
                print(f"  Verified {done}/100 new regional photos...")

    ordered_audit = [results_by_id[rid] for rid in range(1, 301)]
    recipes_by_id = {str(item["id"]): item["url"] for item in ordered_audit}
    recipes_by_title = {item["title"]: item["url"] for item in ordered_audit if item.get("title")}

    unique_urls = len(set(recipes_by_id.values()))
    assert len(recipes_by_id) == 300, f"Expected 300 recipes, got {len(recipes_by_id)}"
    assert unique_urls == 300, f"Expected 300 unique recipe URLs, got {unique_urls}"

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "unique_category_urls": len(set(categories_out.values())),
        "unique_recipe_urls": unique_urls,
        "categories": categories_out,
        "recipes_by_id": recipes_by_id,
        "recipes_by_title": recipes_by_title,
        "categories_audit": categories_audit,
        "recipes_audit": ordered_audit,
    }
    OUT_MANIFEST_300.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSUCCESS in {time.time() - t0:.1f}s -> Saved {OUT_MANIFEST_300}")
    print(f"  8/8 Category URLs + {unique_urls}/300 Unique Recipe URLs HTTP-200 verified!")


if __name__ == "__main__":
    main()
