"""Opaque-box direct MySQL helper using .env credentials via python-dotenv."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import mysql.connector
from dotenv import dotenv_values
from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


def _load_db_config() -> dict[str, Any]:
    raw = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    return {
        "host": str(raw.get("MYSQL_HOST") or os.environ.get("MYSQL_HOST") or "127.0.0.1"),
        "port": int(raw.get("MYSQL_PORT") or os.environ.get("MYSQL_PORT") or 3306),
        "user": str(raw.get("MYSQL_USER") or os.environ.get("MYSQL_USER") or "root"),
        "password": str(raw.get("MYSQL_PASSWORD") if raw.get("MYSQL_PASSWORD") is not None else os.environ.get("MYSQL_PASSWORD", "")),
        "database": str(raw.get("MYSQL_DATABASE") or os.environ.get("MYSQL_DATABASE") or "cookmate"),
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "autocommit": True,
        "connection_timeout": 5,
    }


def _load_secret_key() -> str:
    raw = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    secret = str(
        raw.get("COOKMATE_SECRET_KEY")
        if raw.get("COOKMATE_SECRET_KEY") is not None
        else os.environ.get("COOKMATE_SECRET_KEY", "")
    ).strip()
    if len(secret) >= 2 and secret[0] == secret[-1] and secret[0] in ("'", '"'):
        secret = secret[1:-1].strip()
    return secret or "cookmate-otp-rate-limit"


def _hash_rate_limit_key(scope: str, value: str, secret_key: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        f"{scope}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class DbHelper:
    """Direct MySQL helper for isolated E2E test user setup, inspection, and cleanup."""

    def __init__(self) -> None:
        self.config = _load_db_config()
        self._secret_key = _load_secret_key()
        self._created_emails: list[str] = []
        self._rate_limit_emails: list[str] = []

    def connect(self):
        return mysql.connector.connect(**self.config)

    def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(sql, params)
                return list(cur.fetchall())
            finally:
                cur.close()
        finally:
            conn.close()

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.query_all(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        conn = self.connect()
        try:
            cur = conn.cursor()
            try:
                cur.execute(sql, params)
                return int(cur.rowcount)
            finally:
                cur.close()
        finally:
            conn.close()

    def create_test_user(
        self,
        *,
        prefix: str = "e2e",
        password: str = "OldPass123!",
        role: str = "member",
        status: str = "active",
        full_name: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        unique = uuid.uuid4().hex[:12]
        user_email = (email or f"{prefix}_{unique}@cookmate.test").strip().lower()
        name = full_name or f"E2E User {unique[:6]}"
        pw_hash = generate_password_hash(password)

        conn = self.connect()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO users (full_name, email, password_hash, role, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP())
                    """,
                    (name, user_email, pw_hash, role, status),
                )
                user_id = int(cur.lastrowid)
            finally:
                cur.close()
        finally:
            conn.close()

        self._created_emails.append(user_email)
        return {
            "id": user_id,
            "user_id": user_id,
            "name": name,
            "full_name": name,
            "email": user_email,
            "password": password,
            "password_hash": pw_hash,
            "role": role,
            "status": status,
        }

    def track_email(self, email: str) -> None:
        norm = email.strip().lower()
        if norm and norm not in self._created_emails:
            self._created_emails.append(norm)

    def track_rate_limit_email(self, email: str) -> None:
        norm = email.strip().lower()
        if norm and norm not in self._rate_limit_emails:
            self._rate_limit_emails.append(norm)

    def clear_rate_limits(
        self,
        ip_address: str = "127.0.0.1",
        email_pattern: str = "e2e_%@cookmate.test",
        extra_emails: tuple[str, ...] = (),
    ) -> int:
        """Delete E2E IP and test-email rows from otp_rate_limits if the table exists."""
        if not self.table_exists("otp_rate_limits"):
            return 0

        deleted = 0
        deleted += self.execute("DELETE FROM otp_rate_limits WHERE expires_at <= UTC_TIMESTAMP()")

        ip_hashes = [
            _hash_rate_limit_key("ip", val, self._secret_key)
            for val in dict.fromkeys([ip_address.strip() or "127.0.0.1", "unknown"])
        ]
        ip_placeholders = ", ".join(["%s"] * len(ip_hashes))
        deleted += self.execute(
            f"DELETE FROM otp_rate_limits WHERE scope = 'ip' AND key_hash IN ({ip_placeholders})",
            tuple(ip_hashes),
        )

        candidate_emails: set[str] = {
            e.strip().lower()
            for e in (*self._created_emails, *self._rate_limit_emails, *extra_emails)
            if e and e.strip()
        }
        candidate_emails.update(
            {
                "nonexistent_e2e_99999@cookmate.test",
                "unknown_ratelimit_e2e@cookmate.test",
                "nobody@cookmate.test",
                "someone@cookmate.test",
            }
        )
        if email_pattern:
            rows = self.query_all(
                "SELECT email FROM users WHERE LOWER(email) LIKE LOWER(%s)",
                (email_pattern,),
            )
            for row in rows:
                if row.get("email"):
                    candidate_emails.add(str(row["email"]).strip().lower())

        if candidate_emails:
            email_hashes = [
                _hash_rate_limit_key("email", em, self._secret_key)
                for em in sorted(candidate_emails)
            ]
            email_placeholders = ", ".join(["%s"] * len(email_hashes))
            deleted += self.execute(
                f"DELETE FROM otp_rate_limits WHERE scope = 'email' AND key_hash IN ({email_placeholders})",
                tuple(email_hashes),
            )
        return deleted

    def cleanup(self) -> None:
        try:
            self.clear_rate_limits()
            if self._created_emails:
                emails = list(dict.fromkeys(self._created_emails))
                placeholders = ", ".join(["%s"] * len(emails))
                self.execute(f"DELETE FROM users WHERE email IN ({placeholders})", tuple(emails))
        finally:
            self._created_emails.clear()
            self._rate_limit_emails.clear()

    def delete_user_by_id(self, user_id: int) -> int:
        return self.execute("DELETE FROM users WHERE user_id = %s", (user_id,))

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM users WHERE LOWER(email) = LOWER(%s)", (email.strip(),))

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM users WHERE user_id = %s", (user_id,))

    def table_exists(self, table_name: str) -> bool:
        row = self.query_one(
            """
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            """,
            (self.config["database"], table_name),
        )
        return row is not None

    def get_table_columns(self, table_name: str) -> list[dict[str, Any]]:
        return self.query_all(
            """
            SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, COLUMN_KEY
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            (self.config["database"], table_name),
        )

    def get_foreign_keys(self, table_name: str) -> list[dict[str, Any]]:
        return self.query_all(
            """
            SELECT
                kcu.CONSTRAINT_NAME,
                kcu.COLUMN_NAME,
                kcu.REFERENCED_TABLE_NAME,
                kcu.REFERENCED_COLUMN_NAME,
                rc.DELETE_RULE,
                rc.UPDATE_RULE
            FROM information_schema.KEY_COLUMN_USAGE kcu
            JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
              ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
             AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
             AND rc.TABLE_NAME = kcu.TABLE_NAME
            WHERE kcu.TABLE_SCHEMA = %s
              AND kcu.TABLE_NAME = %s
              AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
            """,
            (self.config["database"], table_name),
        )

    def get_table_indexes(self, table_name: str) -> list[dict[str, Any]]:
        return self.query_all(
            """
            SELECT INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME, NON_UNIQUE
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY INDEX_NAME, SEQ_IN_INDEX
            """,
            (self.config["database"], table_name),
        )

    def get_utc_now(self) -> datetime:
        row = self.query_one("SELECT UTC_TIMESTAMP() AS utc_now")
        assert row is not None
        return row["utc_now"]

    def get_otps_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return self.query_all(
            """
            SELECT
                id,
                user_id,
                otp_hash,
                expires_at,
                attempts,
                created_at,
                used_at,
                TIMESTAMPDIFF(SECOND, created_at, expires_at) AS ttl_seconds
            FROM password_reset_otps
            WHERE user_id = %s
            ORDER BY id ASC
            """,
            (user_id,),
        )

    def get_latest_otp_for_user(self, user_id: int) -> dict[str, Any] | None:
        rows = self.get_otps_for_user(user_id)
        return rows[-1] if rows else None

    def backdate_latest_otp_expiry(self, user_id: int, minutes_ago: int = 10) -> int:
        latest = self.get_latest_otp_for_user(user_id)
        if not latest:
            return 0
        return self.execute(
            """
            UPDATE password_reset_otps
            SET expires_at = DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s MINUTE)
            WHERE id = %s
            """,
            (minutes_ago, latest["id"]),
        )

    def backdate_otps_created_at(self, user_id: int, seconds_ago: int = 120) -> int:
        return self.execute(
            """
            UPDATE password_reset_otps
            SET created_at = DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s SECOND)
            WHERE user_id = %s
            """,
            (seconds_ago, user_id),
        )
