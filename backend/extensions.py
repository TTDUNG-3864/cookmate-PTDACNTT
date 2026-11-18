"""Shared MySQL connection pool. SQLite is never used by the runtime app."""

from __future__ import annotations

from threading import Lock
from typing import Any

from backend.config import Config

_pool: Any = None
_pool_lock = Lock()


def get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                try:
                    from mysql.connector.pooling import MySQLConnectionPool
                except ImportError as exc:
                    raise RuntimeError("mysql-connector-python is required; install requirements.txt") from exc
                _pool = MySQLConnectionPool(
                    pool_name="cookmate_pool",
                    pool_size=max(1, min(Config.MYSQL_POOL_SIZE, 32)),
                    pool_reset_session=True,
                    host=Config.MYSQL_HOST,
                    port=Config.MYSQL_PORT,
                    user=Config.MYSQL_USER,
                    password=Config.MYSQL_PASSWORD,
                    database=Config.MYSQL_DATABASE,
                    charset="utf8mb4",
                    collation="utf8mb4_unicode_ci",
                    use_unicode=True,
                    autocommit=False,
                    connection_timeout=5,
                )
    return _pool


def get_connection():
    return get_pool().get_connection()


def reset_pool_for_tests() -> None:
    global _pool
    with _pool_lock:
        _pool = None

