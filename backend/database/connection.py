"""Connection and transaction helpers for MySQL Connector/Python."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from backend.extensions import get_connection


@contextmanager
def cursor(*, dictionary: bool = True) -> Iterator[tuple[Any, Any]]:
    connection = get_connection()
    db_cursor = None
    try:
        db_cursor = connection.cursor(dictionary=dictionary, buffered=True)
        yield connection, db_cursor
    finally:
        if db_cursor is not None:
            db_cursor.close()
        connection.close()


@contextmanager
def transaction(*, dictionary: bool = True) -> Iterator[tuple[Any, Any]]:
    connection = get_connection()
    db_cursor = None
    try:
        db_cursor = connection.cursor(dictionary=dictionary, buffered=True)
        yield connection, db_cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if db_cursor is not None:
            db_cursor.close()
        connection.close()


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with cursor() as (_, cur):
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with cursor() as (_, cur):
        cur.execute(sql, params)
        return cur.fetchone()


def check_database() -> bool:
    with cursor(dictionary=False) as (_, cur):
        cur.execute("SELECT 1")
        return cur.fetchone()[0] == 1

