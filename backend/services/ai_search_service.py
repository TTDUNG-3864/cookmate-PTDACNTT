"""Grounded recipe discovery. Sources come only from Gemini Search grounding metadata."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.config import Config
from backend.database.repositories import get_search_cache, list_recipes, save_search_cache
from backend.gemini_manager import generate_grounded_response

logger = logging.getLogger(__name__)


def search_online(query: str) -> dict[str, Any]:
    query = " ".join(str(query or "").split())[:200]
    local = list_recipes({"q": query, "limit": 10})
    cached = get_search_cache(query)
    if cached:
        return {"success": True, "cached": True, "internalRecipes": local, **cached}
    if not Config.GEMINI_API_KEY:
        return {"success": False, "status": "unavailable", "message": "Tìm kiếm AI cần GEMINI_API_KEY trong cấu hình máy chủ.", "internalRecipes": local, "recipes": [], "sources": []}
    if not query:
        raise ValueError("Hãy nhập tên món ăn cần tìm.")
    try:
        prompt=("Tìm trên web một hoặc hai công thức nấu ăn có nguồn thật cho món: " + query + ". "
                "Chỉ trả JSON object: {recipes:[{title,description,servings,prep_time,cook_time,difficulty,calories,protein,carbs,fat,fiber,ingredients:[{name,amount,unit}],steps:[string]}]}. "
                "Không tự tạo URL hoặc danh sách nguồn; nguồn sẽ được lấy từ metadata tìm kiếm. Nếu không thấy dữ liệu đáng tin, recipes để mảng rỗng.")
        generated=generate_grounded_response(prompt,system_instruction="Trả về JSON hợp lệ, dùng Google Search grounding và không tự tạo URL nguồn.")
        response=generated["_raw_response"]
        sources=_grounded_sources(response)
        recipes=_parse_recipes(getattr(response,"text","") or "")
        if not sources or not recipes:
            return {"success":False,"status":"no_grounded_results","message":"Không có kết quả công thức kèm nguồn web xác minh được.",
                    "internalRecipes":local,"recipes":[],"sources":[]}
        for recipe in recipes:
            recipe["sources"]=sources
        result={"recipes":recipes,"sources":sources,"status":"grounded"}
        save_search_cache(query,result,recipes)
        return {"success":True,"cached":False,"internalRecipes":local,**result}
    except ValueError:
        raise
    except Exception as exc:
        logger.error("Gemini grounded recipe search failed (%s)",type(exc).__name__)
        return {"success":False,"status":"unavailable","message":"Tìm kiếm AI đang tạm thời không khả dụng.",
                "internalRecipes":local,"recipes":[],"sources":[]}


def _grounded_sources(response: Any) -> list[dict[str, Any]]:
    candidates=getattr(response,"candidates",None) or []
    if not candidates:
        return []
    metadata=getattr(candidates[0],"grounding_metadata",None) or getattr(candidates[0],"groundingMetadata",None)
    chunks=getattr(metadata,"grounding_chunks",None) or getattr(metadata,"groundingChunks",None) or []
    sources=[]; seen=set()
    for chunk in chunks:
        web=getattr(chunk,"web",None) or getattr(chunk,"retrieved_context",None) or getattr(chunk,"retrievedContext",None)
        if not web:
            continue
        url=str(getattr(web,"uri",None) or getattr(web,"url",None) or "")
        title=str(getattr(web,"title",None) or url)
        if url.startswith(("https://","http://")) and url not in seen:
            seen.add(url); sources.append({"name":title[:255],"url":url,"relevance":0.7})
    return sources


def _parse_recipes(text: str) -> list[dict[str, Any]]:
    text=text.strip()
    text=re.sub(r"^```(?:json)?\s*|\s*```$","",text,flags=re.I)
    try:
        payload=json.loads(text)
    except ValueError:
        match=re.search(r"\{.*\}",text,re.S)
        if not match:
            return []
        try:
            payload=json.loads(match.group(0))
        except ValueError:
            return []
    result=[]
    for item in payload.get("recipes",[]) if isinstance(payload,dict) else []:
        if not isinstance(item,dict) or not str(item.get("title") or "").strip():
            continue
        ingredients=item.get("ingredients") or []
        steps=item.get("steps") or []
        if not ingredients or not steps:
            continue
        safe={"title":str(item["title"])[:255],"description":str(item.get("description") or "")[:3000],
              "servings":_number(item.get("servings"),4,1,50),"prep_time":_number(item.get("prep_time"),0,0,1440),
              "cook_time":_number(item.get("cook_time"),0,0,1440),"difficulty":str(item.get("difficulty") or "Dễ")[:50],
              "calories":_number(item.get("calories"),0,0,5000),"protein":_number(item.get("protein"),0,0,1000),
              "carbs":_number(item.get("carbs"),0,0,1000),"fat":_number(item.get("fat"),0,0,1000),"fiber":_number(item.get("fiber"),0,0,1000),
              "ingredients":[{"name":str(x.get("name") or "")[:200],"amount":str(x.get("amount") or "")[:80],"unit":str(x.get("unit") or "")[:40]} for x in ingredients if isinstance(x,dict)],
              "steps":[str(x)[:5000] for x in steps if isinstance(x,str) and x.strip()]}
        if safe["ingredients"] and safe["steps"]:
            result.append(safe)
    return result[:3]


def _number(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low,min(high,int(value)))
    except (TypeError,ValueError):
        return default

