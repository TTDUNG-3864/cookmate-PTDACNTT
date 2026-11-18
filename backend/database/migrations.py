"""Explicit, non-destructive migration from the legacy SQLite database to MySQL."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.database.connection import get_connection

TABLE_MAP={
    "users":"users","categories":"categories","ingredients":"ingredients","recipes":"recipes",
    "recipe_ingredients":"recipe_ingredients","recipe_steps":"recipe_steps","comments":"comments","favorites":"favorites",
}


def migrate_sqlite_to_mysql(source: str | Path, connection: Any | None = None) -> dict[str, Any]:
    source=Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source database does not exist: {source}")
    sqlite=sqlite3.connect(str(source)); sqlite.row_factory=sqlite3.Row
    mysql=connection or get_connection()
    owns_connection=connection is None
    try:
        source_counts={name:_sqlite_count(sqlite,name) for name in TABLE_MAP}
        cursor=mysql.cursor(dictionary=True,buffered=True)
        try:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()")
            target_tables=[row["table_name"] for row in cursor.fetchall()]
            target_counts={name:_mysql_count(cursor,name) for name in target_tables}
            nonempty={name:count for name,count in target_counts.items() if count}
            if nonempty:
                raise RuntimeError(f"Refusing to migrate into non-empty MySQL tables: {nonempty}. Back up and select an empty target database.")
            base_ids=_seed_recipe_ids()
            category_map={}
            ingredient_map={}

            for row in sqlite.execute("SELECT * FROM users ORDER BY id"):
                data=dict(row)
                cursor.execute("INSERT INTO users(user_id,full_name,email,password_hash,role,status,avatar_url,bio,created_at) "
                               "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (data["id"],data["name"],data["email"],data["password_hash"],"admin" if data["role"]=="admin" else "member",
                     "active" if data.get("status","active")=="active" else "inactive",data.get("avatar") or "",data.get("bio") or "",
                     data.get("joined_at") or "2024-01-01"))
            for row in sqlite.execute("SELECT * FROM categories ORDER BY id"):
                data=dict(row); category_map[data["id"]]=data["id"]
                cursor.execute("INSERT INTO categories(category_id,name,slug,icon,description,image_url) VALUES(%s,%s,%s,%s,%s,%s)",
                    (data["id"],data["name"],data["slug"],data.get("icon") or "restaurant",data.get("description") or "",data.get("image") or ""))
            for row in sqlite.execute("SELECT * FROM ingredients ORDER BY id"):
                data=dict(row); ingredient_map[data["id"]]=data["id"]
                cursor.execute("INSERT INTO ingredients(ingredient_id,ingredient_name,category,unit,calories,protein,fat,carbs,fiber,is_popular) "
                               "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (data["id"],data["name"],data.get("category") or "Khác",_unit_100(data.get("unit")),data.get("calories") or 0,
                     data.get("protein") or 0,data.get("fat") or 0,data.get("carbs") or 0,data.get("fiber") or 0,bool(data.get("popular"))))

            recipe_rows=[dict(row) for row in sqlite.execute("SELECT * FROM recipes ORDER BY id")]
            for data in recipe_rows:
                status=str(data.get("status") or "pending").upper()
                if status not in {"PENDING","APPROVED","REJECTED"}: status="PENDING"
                source_type="DB" if data["id"] in base_ids else "USER"
                created_by=data.get("author_id")
                if created_by and not _has_id(sqlite,"users","id",created_by): created_by=None
                nutrition=_json(data.get("nutrition_json"),{})
                category_id=category_map.get(data.get("category_id"))
                cursor.execute("INSERT INTO recipes(recipe_id,dish_id,category_id,title,slug,description,image_url,cuisine,servings,prep_time,cook_time,"
                    "difficulty,occasion,calories,protein,carbs,fat,fiber,rating,review_count,views,is_featured,is_new,tags_json,source_type,created_by,status,created_at,updated_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (data["id"],None,category_id,data["title"],data["slug"],data.get("description") or "",data.get("image") or "",
                     data.get("cuisine") or "Món Việt",data.get("servings") or 4,data.get("prep_time") or 0,data.get("cook_time") or 0,
                     data.get("difficulty") or "Dễ",data.get("holiday"),data.get("calories") or nutrition.get("calories",0),
                     nutrition.get("protein",0),nutrition.get("carbs",0),nutrition.get("fat",0),nutrition.get("fiber",0),
                     data.get("rating") or 0,data.get("review_count") or 0,data.get("views") or 0,bool(data.get("featured")),
                     bool(data.get("is_new")),data.get("tags_json") or "[]",source_type,created_by,status,data.get("created_at"),data.get("created_at")))
                cursor.execute("INSERT INTO dishes(dish_id,dish_name,slug,thumbnail_url,cook_time_mins,difficulty,category_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (data["id"],data["title"],data["slug"],data.get("image") or "",(data.get("prep_time") or 0)+(data.get("cook_time") or 0),data.get("difficulty") or "Dễ",category_id))
                cursor.execute("UPDATE recipes SET dish_id=%s WHERE recipe_id=%s",(data["id"],data["id"]))

            for row in sqlite.execute("SELECT * FROM recipe_ingredients ORDER BY recipe_id,sort_order,id"):
                data=dict(row)
                ingredient_id=_ingredient_id_for_name(cursor,data["name"])
                cursor.execute("INSERT INTO recipe_ingredients(recipe_id,ingredient_id,ingredient_name,amount,unit,sort_order,note) "
                               "VALUES(%s,%s,%s,%s,%s,%s,'')",
                    (data["recipe_id"],ingredient_id,data["name"],data.get("amount") or "",data.get("unit") or "",data.get("sort_order") or 0))
                if ingredient_id:
                    cursor.execute("INSERT IGNORE INTO dish_ingredients(dish_id,ingredient_id,is_required,weight_score) VALUES(%s,%s,TRUE,1.0)",
                                   (data["recipe_id"],ingredient_id))
            for row in sqlite.execute("SELECT * FROM recipe_steps ORDER BY recipe_id,step"):
                data=dict(row)
                cursor.execute("INSERT INTO recipe_steps(recipe_id,step_order,title,instruction,duration_mins,tip_note,image_url) "
                               "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (data["recipe_id"],data["step"],data.get("title") or "",data.get("description") or "",data.get("time"),data.get("tip"),data.get("image")))
            for row in sqlite.execute("SELECT * FROM comments ORDER BY id"):
                data=dict(row)
                if not _has_id(sqlite,"users","id",data["user_id"]):
                    continue
                cursor.execute("INSERT INTO comments(comment_id,recipe_id,user_id,user_name,user_avatar,rating,comment,created_at) "
                               "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (data["id"],data["recipe_id"],data["user_id"],data["user_name"],data.get("user_avatar") or "",data.get("rating") or 5,
                     data["comment"],data.get("date")))
            for row in sqlite.execute("SELECT * FROM favorites ORDER BY user_id,recipe_id"):
                data=dict(row)
                cursor.execute("INSERT INTO favorites(user_id,recipe_id,saved_at) VALUES(%s,%s,%s)",
                               (data["user_id"],data["recipe_id"],data.get("created_at")))
            migrated={name:_mysql_count(cursor,name) for name in TABLE_MAP}
            # Comments with an invalid legacy user are intentionally excluded and counted explicitly.
            expected=dict(source_counts)
            expected["comments"]=_sqlite_count(sqlite,"comments",valid_user_only=True)
            if migrated != expected:
                raise RuntimeError(f"Post-migration row counts differ. Expected {expected}; got {migrated}.")
            cursor.execute("SELECT COUNT(*) AS n FROM recipes r LEFT JOIN users u ON u.user_id=r.created_by WHERE r.created_by IS NOT NULL AND u.user_id IS NULL")
            dangling=cursor.fetchone()["n"]
            if dangling:
                raise RuntimeError(f"Migration created {dangling} recipes with a missing creator.")
            mysql.commit()
            return {"source":str(source.resolve()),"counts":migrated,"old_database_removed":False}
        except Exception:
            mysql.rollback()
            raise
        finally:
            cursor.close()
    finally:
        sqlite.close()
        if owns_connection:
            mysql.close()


def _sqlite_count(conn: sqlite3.Connection, table: str, *, valid_user_only: bool = False) -> int:
    if valid_user_only and table=="comments":
        return conn.execute("SELECT COUNT(*) FROM comments c JOIN users u ON u.id=c.user_id").fetchone()[0]
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _mysql_count(cur: Any, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
    return int(cur.fetchone()["n"])


def _has_id(conn: sqlite3.Connection, table: str, col: str, value: Any) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE {col}=? LIMIT 1",(value,)).fetchone() is not None


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError,ValueError):
        return default


def _unit_100(unit: str | None) -> str:
    unit=str(unit or "100g").lower()
    return "100ml" if "ml" in unit or "lít" in unit or "lit" in unit else "100g"


def _ingredient_id_for_name(cur: Any, name: str) -> int | None:
    cur.execute("SELECT ingredient_id FROM ingredients WHERE ingredient_name=%s LIMIT 1",(name,))
    row=cur.fetchone()
    return int(row["ingredient_id"]) if row else None


def _seed_recipe_ids() -> set[int]:
    try:
        from backend.seed import SEED_RECIPES
        return {int(row["id"]) for row in SEED_RECIPES}
    except Exception:
        return set()


def main() -> None:
    parser=argparse.ArgumentParser(description="Copy the legacy SQLite database into an empty CookMate MySQL schema.")
    parser.add_argument("--source",default="database/cookmate.db",help="Path to the existing SQLite database")
    args=parser.parse_args()
    result=migrate_sqlite_to_mysql(args.source)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()

