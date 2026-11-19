"""Thread-safe, DB-backed (with memory fallback) OTP rate limiting helper."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict

from backend.database.connection import transaction

logger = logging.getLogger(__name__)

_TRANSIENT_LOCK_ERRNOS = frozenset({1213, 1205, 1062})


class _RateLimitContentionError(RuntimeError):
    """Raised when transient DB lock contention exhausts all bounded retries."""


def _hash_rate_key(scope: str, value: str, secret_key: str) -> str:
    key_bytes = (secret_key or "cookmate-otp-rate-limit").encode("utf-8")
    msg_bytes = f"{scope}:{value}".encode("utf-8")
    return hmac.new(key_bytes, msg_bytes, hashlib.sha256).hexdigest()


class OTPRateLimiter:
    """Enforces per-normalized-email cooldown/window caps and per-IP burst limits."""

    def __init__(
        self,
        secret_key: str = "",
        *,
        use_db: bool = False,
        sweep_interval: float = 1.0,
    ) -> None:
        self._secret_key = str(secret_key or "")
        self._use_db = bool(use_db)
        self._sweep_interval = max(0.1, float(sweep_interval))
        self._lock = threading.Lock()
        self._email_hits: dict[str, list[float]] = defaultdict(list)
        self._ip_hits: dict[str, list[float]] = defaultdict(list)
        self._email_expiries: dict[str, float] = {}
        self._ip_expiries: dict[str, float] = {}
        self._last_sweep = time.monotonic()
        self._ops_since_sweep = 0
        self._last_db_sweep = 0.0
        self._seen_db_keys: set[tuple[str, str]] = set()

    def _evict_expired_memory_locked(self, now: float) -> None:
        for key, exp in list(self._email_expiries.items()):
            if exp <= now:
                self._email_expiries.pop(key, None)
                self._email_hits.pop(key, None)
        for key in list(self._email_hits.keys()):
            if key not in self._email_expiries or not self._email_hits[key]:
                self._email_hits.pop(key, None)
                self._email_expiries.pop(key, None)

        for key, exp in list(self._ip_expiries.items()):
            if exp <= now:
                self._ip_expiries.pop(key, None)
                self._ip_hits.pop(key, None)
        for key in list(self._ip_hits.keys()):
            if key not in self._ip_expiries or not self._ip_hits[key]:
                self._ip_hits.pop(key, None)
                self._ip_expiries.pop(key, None)

        self._last_sweep = now
        self._ops_since_sweep = 0

    def _check_and_record_memory(
        self,
        email_key: str,
        ip_key: str,
        *,
        cooldown_seconds: int,
        max_requests: int,
        window_seconds: int,
        ip_max_requests: int,
        ip_window_seconds: int,
    ) -> bool:
        now = time.monotonic()
        email_win = max(1, int(window_seconds))
        ip_win = max(1, int(ip_window_seconds))

        with self._lock:
            self._ops_since_sweep += 1
            if (now - self._last_sweep) >= self._sweep_interval or self._ops_since_sweep >= 64:
                self._evict_expired_memory_locked(now)

            email_cutoff = now - email_win
            email_history = [ts for ts in self._email_hits.get(email_key, []) if ts > email_cutoff]
            if email_history:
                self._email_hits[email_key] = email_history
            else:
                self._email_hits.pop(email_key, None)
                self._email_expiries.pop(email_key, None)

            ip_cutoff = now - ip_win
            ip_history = [ts for ts in self._ip_hits.get(ip_key, []) if ts > ip_cutoff]
            if ip_history:
                self._ip_hits[ip_key] = ip_history
            else:
                self._ip_hits.pop(ip_key, None)
                self._ip_expiries.pop(ip_key, None)

            if cooldown_seconds > 0 and email_history and (now - email_history[-1]) < cooldown_seconds:
                return False
            if max_requests > 0 and len(email_history) >= max_requests:
                return False
            if ip_max_requests > 0 and len(ip_history) >= ip_max_requests:
                return False

            email_history.append(now)
            ip_history.append(now)
            self._email_hits[email_key] = email_history
            self._ip_hits[ip_key] = ip_history
            self._email_expiries[email_key] = now + email_win
            self._ip_expiries[ip_key] = now + ip_win
            return True

    def _seed_missing_db_rows(
        self,
        *,
        missing_email: bool,
        missing_ip: bool,
        email_hash: str,
        ip_hash: str,
        email_win: int,
        ip_win: int,
    ) -> None:
        rows_to_seed: list[tuple[str, str, int]] = []
        if missing_email:
            rows_to_seed.append(("email", email_hash, max(60, email_win)))
        if missing_ip:
            rows_to_seed.append(("ip", ip_hash, max(60, ip_win)))
        for scope, key_hash, ttl in rows_to_seed:
            try:
                with transaction() as (_, cur):
                    cur.execute(
                        "INSERT INTO otp_rate_limits "
                        "(scope, key_hash, hit_count, window_started_at, last_hit_at, expires_at) "
                        "VALUES "
                        "(%s, %s, 0, DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 SECOND), "
                        " DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 SECOND), "
                        " DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND))",
                        (scope, key_hash, ttl),
                    )
            except Exception as exc:
                if getattr(exc, "errno", None) == 1062:
                    continue
                raise

    def _check_and_record_db(
        self,
        email_key: str,
        ip_key: str,
        *,
        secret_key: str,
        cooldown_seconds: int,
        max_requests: int,
        window_seconds: int,
        ip_max_requests: int,
        ip_window_seconds: int,
    ) -> bool:
        email_win = max(1, int(window_seconds))
        ip_win = max(1, int(ip_window_seconds))
        cooldown = max(0, int(cooldown_seconds))
        email_hash = _hash_rate_key("email", email_key, secret_key)
        ip_hash = _hash_rate_key("ip", ip_key, secret_key)

        with self._lock:
            self._seen_db_keys.add(("email", email_hash))
            self._seen_db_keys.add(("ip", ip_hash))
            now = time.monotonic()
            should_sweep = (now - self._last_db_sweep) >= min(60.0, float(email_win), float(ip_win))
            if should_sweep:
                self._last_db_sweep = now

        if should_sweep:
            try:
                with transaction() as (_, cur):
                    cur.execute("DELETE FROM otp_rate_limits WHERE expires_at <= UTC_TIMESTAMP() LIMIT 500")
            except Exception as sweep_exc:
                if getattr(sweep_exc, "errno", None) == 1146:
                    raise

        max_attempts = 6
        last_transient_exc: Exception | None = None
        for attempt in range(max_attempts):
            missing_email = False
            missing_ip = False
            try:
                with transaction() as (_, cur):
                    cur.execute(
                        "SELECT scope, key_hash, hit_count, window_started_at, last_hit_at, expires_at, "
                        "       (window_started_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s SECOND)) AS email_expired, "
                        "       (window_started_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s SECOND)) AS ip_expired, "
                        "       (CASE WHEN %s > 0 AND last_hit_at > DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s SECOND) "
                        "             THEN 1 ELSE 0 END) AS in_cooldown "
                        "FROM otp_rate_limits "
                        "WHERE (scope = 'email' AND key_hash = %s) "
                        "   OR (scope = 'ip' AND key_hash = %s) "
                        "ORDER BY scope ASC "
                        "FOR UPDATE",
                        (email_win, ip_win, cooldown, cooldown, email_hash, ip_hash),
                    )
                    rows = {str(row["scope"]): row for row in cur.fetchall()}
                    missing_email = "email" not in rows
                    missing_ip = "ip" not in rows
                    if not missing_email and not missing_ip:
                        email_row = rows["email"]
                        ip_row = rows["ip"]

                        email_count = int(email_row.get("hit_count") or 0)
                        ip_count = int(ip_row.get("hit_count") or 0)
                        email_fresh = email_count <= 0 or bool(email_row.get("email_expired"))
                        ip_fresh = ip_count <= 0 or bool(ip_row.get("ip_expired"))

                        if not email_fresh:
                            if cooldown > 0 and bool(email_row.get("in_cooldown")):
                                return False
                            if max_requests > 0 and email_count >= max_requests:
                                return False

                        if not ip_fresh:
                            if ip_max_requests > 0 and ip_count >= ip_max_requests:
                                return False

                        if email_fresh:
                            cur.execute(
                                "UPDATE otp_rate_limits "
                                "SET hit_count = 1, window_started_at = UTC_TIMESTAMP(), "
                                "    last_hit_at = UTC_TIMESTAMP(), "
                                "    expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND) "
                                "WHERE scope = 'email' AND key_hash = %s",
                                (email_win, email_hash),
                            )
                        else:
                            cur.execute(
                                "UPDATE otp_rate_limits "
                                "SET hit_count = hit_count + 1, "
                                "    last_hit_at = UTC_TIMESTAMP(), "
                                "    expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND) "
                                "WHERE scope = 'email' AND key_hash = %s",
                                (email_win, email_hash),
                            )

                        if ip_fresh:
                            cur.execute(
                                "UPDATE otp_rate_limits "
                                "SET hit_count = 1, window_started_at = UTC_TIMESTAMP(), "
                                "    last_hit_at = UTC_TIMESTAMP(), "
                                "    expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND) "
                                "WHERE scope = 'ip' AND key_hash = %s",
                                (ip_win, ip_hash),
                            )
                        else:
                            cur.execute(
                                "UPDATE otp_rate_limits "
                                "SET hit_count = hit_count + 1, "
                                "    last_hit_at = UTC_TIMESTAMP(), "
                                "    expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND) "
                                "WHERE scope = 'ip' AND key_hash = %s",
                                (ip_win, ip_hash),
                            )
                        return True
            except Exception as exc:
                if getattr(exc, "errno", None) not in _TRANSIENT_LOCK_ERRNOS:
                    raise
                last_transient_exc = exc
                if attempt + 1 < max_attempts:
                    time.sleep(0.005 * (attempt + 1) + secrets.randbelow(10) * 0.001)
                continue

            try:
                self._seed_missing_db_rows(
                    missing_email=missing_email,
                    missing_ip=missing_ip,
                    email_hash=email_hash,
                    ip_hash=ip_hash,
                    email_win=email_win,
                    ip_win=ip_win,
                )
            except Exception as exc:
                if getattr(exc, "errno", None) not in _TRANSIENT_LOCK_ERRNOS:
                    raise
                last_transient_exc = exc
                if attempt + 1 < max_attempts:
                    time.sleep(0.005 * (attempt + 1) + secrets.randbelow(10) * 0.001)

        raise _RateLimitContentionError(
            f"OTP rate limiter DB contention persisted after {max_attempts} attempts"
        ) from last_transient_exc

    def check_and_record(
        self,
        email: str,
        client_ip: str,
        *,
        secret_key: str | None = None,
        cooldown_seconds: int = 60,
        max_requests: int = 5,
        window_seconds: int = 900,
        ip_max_requests: int = 30,
        ip_window_seconds: int = 300,
    ) -> bool:
        email_key = str(email or "").strip().lower()
        ip_key = str(client_ip or "unknown").strip() or "unknown"
        resolved_secret = str(secret_key if secret_key is not None else self._secret_key)

        if self._use_db:
            try:
                return self._check_and_record_db(
                    email_key,
                    ip_key,
                    secret_key=resolved_secret,
                    cooldown_seconds=cooldown_seconds,
                    max_requests=max_requests,
                    window_seconds=window_seconds,
                    ip_max_requests=ip_max_requests,
                    ip_window_seconds=ip_window_seconds,
                )
            except _RateLimitContentionError as exc:
                logger.error("OTP DB rate limiter contention exhausted retries (%s); failing closed.", exc)
                return False
            except Exception as exc:
                if getattr(exc, "errno", None) == 1146:
                    try:
                        from backend.database.schema_upgrade import ensure_runtime_schema

                        ensure_runtime_schema()
                        return self._check_and_record_db(
                            email_key,
                            ip_key,
                            secret_key=resolved_secret,
                            cooldown_seconds=cooldown_seconds,
                            max_requests=max_requests,
                            window_seconds=window_seconds,
                            ip_max_requests=ip_max_requests,
                            ip_window_seconds=ip_window_seconds,
                        )
                    except _RateLimitContentionError as retry_exc:
                        logger.error(
                            "OTP DB rate limiter contention exhausted retries (%s); failing closed.",
                            retry_exc,
                        )
                        return False
                    except Exception as retry_exc:
                        exc = retry_exc
                if getattr(exc, "errno", None) in _TRANSIENT_LOCK_ERRNOS:
                    logger.error("OTP DB rate limiter transient lock error (%s); failing closed.", exc)
                    return False
                logger.warning("OTP DB rate limiter unavailable (%s); using in-memory fallback.", type(exc).__name__)

        return self._check_and_record_memory(
            email_key,
            ip_key,
            cooldown_seconds=cooldown_seconds,
            max_requests=max_requests,
            window_seconds=window_seconds,
            ip_max_requests=ip_max_requests,
            ip_window_seconds=ip_window_seconds,
        )

    def reset(self) -> None:
        with self._lock:
            self._email_hits.clear()
            self._ip_hits.clear()
            self._email_expiries.clear()
            self._ip_expiries.clear()
            self._ops_since_sweep = 0
            seen = list(self._seen_db_keys)
            self._seen_db_keys.clear()

        if self._use_db:
            try:
                with transaction() as (_, cur):
                    cur.execute("DELETE FROM otp_rate_limits WHERE expires_at <= UTC_TIMESTAMP()")
                    for scope, key_hash in seen:
                        cur.execute(
                            "DELETE FROM otp_rate_limits WHERE scope = %s AND key_hash = %s",
                            (scope, key_hash),
                        )
            except Exception:
                pass


def reset_otp_rate_limits(app=None) -> None:
    """Reset the rate limiter state for the given Flask app (or current_app)."""
    if app is None:
        from flask import current_app
        app = current_app
    limiter = app.extensions.get("otp_rate_limiter")
    if isinstance(limiter, OTPRateLimiter):
        limiter.reset()
