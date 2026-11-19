"""Environment-backed application configuration."""

from __future__ import annotations

import os
import hmac
import re
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from datetime import timedelta

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = PROJECT_ROOT
ENV_FILE = PROJECT_ROOT / ".env"
_PROCESS_ENV = {
    name: os.environ.get(name, "")
    for name in ("APP_ENV", "GEMINI_API_KEY", "GOOGLE_API_KEY", "DEMO_MODE", "TRUST_PROXY_HEADERS")
}
_DOTENV = dict(dotenv_values(ENV_FILE))
_RUNTIME_APP_ENV = str(_PROCESS_ENV["APP_ENV"] or _DOTENV.get("APP_ENV") or "development").strip().lower()
_LOCAL_DEVELOPMENT = _RUNTIME_APP_ENV == "development"

# Local development intentionally prefers the project .env over stale shell values.
# Production keeps process environment variables as the higher-priority source.
load_dotenv(ENV_FILE, override=_LOCAL_DEVELOPMENT)
os.environ["APP_ENV"] = _RUNTIME_APP_ENV


def _clean_secret(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    return text


def resolve_demo_mode(
    process_env: dict[str, object], dotenv_values_map: dict[str, object], *, development: bool
) -> bool:
    """Resolve DEMO_MODE safely: ignore stray local .env DEMO_MODE in production."""
    if not development:
        return _clean_secret(process_env.get("DEMO_MODE")).lower() == "true"
    dotenv_val = _clean_secret(dotenv_values_map.get("DEMO_MODE"))
    if dotenv_val:
        return dotenv_val.lower() == "true"
    return _clean_secret(process_env.get("DEMO_MODE")).lower() == "true"


def resolve_trust_proxy_headers(
    process_env: dict[str, object], dotenv_values_map: dict[str, object], *, development: bool
) -> bool:
    """Resolve TRUST_PROXY_HEADERS safely (default False; ignore .env in production)."""
    if not development:
        return _clean_secret(process_env.get("TRUST_PROXY_HEADERS")).lower() == "true"
    dotenv_val = _clean_secret(dotenv_values_map.get("TRUST_PROXY_HEADERS"))
    if dotenv_val:
        return dotenv_val.lower() == "true"
    return _clean_secret(process_env.get("TRUST_PROXY_HEADERS")).lower() == "true"


def apply_environment_defaults(config: dict[str, object], overrides: dict[str, object] | None = None) -> None:
    """Re-evaluate security defaults when APP_ENV is set or overridden on create_app()."""
    override_keys = set((overrides or {}).keys())
    app_env = str(config.get("APP_ENV") or "development").strip().lower()
    config["APP_ENV"] = app_env
    is_production = app_env == "production"
    if is_production:
        if "DEMO_MODE" not in override_keys:
            config["DEMO_MODE"] = resolve_demo_mode(_PROCESS_ENV, _DOTENV, development=False)
        if "SESSION_COOKIE_SECURE" not in override_keys:
            config["SESSION_COOKIE_SECURE"] = True
        if "SESSION_COOKIE_SAMESITE" not in override_keys:
            config["SESSION_COOKIE_SAMESITE"] = "None"
        if "TRUST_PROXY_HEADERS" not in override_keys:
            config["TRUST_PROXY_HEADERS"] = resolve_trust_proxy_headers(_PROCESS_ENV, _DOTENV, development=False)
    elif "APP_ENV" in override_keys:
        is_development = app_env == "development"
        if "DEMO_MODE" not in override_keys:
            config["DEMO_MODE"] = resolve_demo_mode(_PROCESS_ENV, _DOTENV, development=is_development)
        if "SESSION_COOKIE_SECURE" not in override_keys:
            config["SESSION_COOKIE_SECURE"] = False
        if "SESSION_COOKIE_SAMESITE" not in override_keys:
            config["SESSION_COOKIE_SAMESITE"] = "Lax"
        if "TRUST_PROXY_HEADERS" not in override_keys:
            config["TRUST_PROXY_HEADERS"] = resolve_trust_proxy_headers(_PROCESS_ENV, _DOTENV, development=is_development)


def resolve_gemini_api_key(
    process_env: dict[str, object], dotenv_values_map: dict[str, object], *, development: bool
) -> tuple[str, str, bool, tuple[str, ...]]:
    """Choose one explicit key source and report conflicts without exposing values."""
    names = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    process = {name: _clean_secret(process_env.get(name)) for name in names}
    dotenv = {name: _clean_secret(dotenv_values_map.get(name)) for name in names}
    candidates = [(f"PROCESS_ENV:{name}", value) for name, value in process.items() if value]
    candidates += [(f"PROJECT_DOTENV:{name}", value) for name, value in dotenv.items() if value]
    distinct = []
    for _, value in candidates:
        if not any(hmac.compare_digest(value, found) for found in distinct):
            distinct.append(value)
    conflict = len(distinct) > 1

    priority = (("PROJECT_DOTENV", dotenv), ("PROCESS_ENV", process)) if development else (
        ("PROCESS_ENV", process), ("PROJECT_DOTENV", dotenv)
    )
    for source, values in priority:
        for name in names:
            value = values[name]
            if value:
                return value, f"{source}:{name}", conflict, tuple(label for label, _ in candidates)
    return "", "MISSING", conflict, tuple(label for label, _ in candidates)


_GEMINI_API_KEY, _GEMINI_API_KEY_SOURCE, _GEMINI_API_KEY_CONFLICT, _GEMINI_KEY_SOURCES = resolve_gemini_api_key(
    _PROCESS_ENV, _DOTENV, development=_LOCAL_DEVELOPMENT
)
_DEMO_MODE = resolve_demo_mode(_PROCESS_ENV, _DOTENV, development=_LOCAL_DEVELOPMENT)
_TRUST_PROXY_HEADERS = resolve_trust_proxy_headers(_PROCESS_ENV, _DOTENV, development=_LOCAL_DEVELOPMENT)


def allowed_origins() -> tuple[str, ...]:
    values = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
    return tuple(origin.strip().rstrip("/") for origin in values.split(",") if origin.strip())


class Config:
    SECRET_KEY = os.getenv("COOKMATE_SECRET_KEY", "")
    APP_ENV = os.getenv("APP_ENV", "development").lower()
    PORT = int(os.getenv("PORT", "5000"))
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "cookmate")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_POOL_SIZE = int(os.getenv("MYSQL_POOL_SIZE", "5"))
    GEMINI_API_KEY = _GEMINI_API_KEY
    GEMINI_API_KEY_SOURCE = _GEMINI_API_KEY_SOURCE
    GEMINI_API_KEY_CONFLICT = _GEMINI_API_KEY_CONFLICT
    GEMINI_KEY_SOURCES = _GEMINI_KEY_SOURCES
    _raw_primary = (os.getenv("GEMINI_PRIMARY_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash").strip().strip("\"'")
    _raw_secondary = (
        os.getenv("GEMINI_SECONDARY_MODEL")
        or os.getenv("GEMINI_FALLBACK_MODEL")
        or "gemini-2.5-flash-lite"
    ).strip().strip("\"'")
    GEMINI_PRIMARY_MODEL = "gemini-2.5-flash" if _raw_primary in ("gemini-3.6-flash", "") else _raw_primary
    GEMINI_FALLBACK_MODEL = "gemini-2.5-flash-lite" if _raw_secondary in ("gemini-4-hydrogen", "") else _raw_secondary
    GEMINI_SECONDARY_MODEL = GEMINI_FALLBACK_MODEL
    GEMINI_TIMEOUT = max(1, int(os.getenv("GEMINI_TIMEOUT", "28")))
    GEMINI_MAX_RETRIES = max(0, min(3, int(os.getenv("GEMINI_MAX_RETRIES", "1"))))
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b").strip()
    OLLAMA_TIMEOUT = max(1, int(os.getenv("OLLAMA_TIMEOUT", "90")))
    OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "15m").strip() or "15m"
    OLLAMA_NUM_CTX = max(1024, min(8192, int(os.getenv("OLLAMA_NUM_CTX", "4096"))))
    OLLAMA_NUM_PREDICT = max(128, min(2048, int(os.getenv("OLLAMA_NUM_PREDICT", "960"))))
    OLLAMA_AUTO_START = os.getenv("OLLAMA_AUTO_START", "true").lower() == "true"
    OLLAMA_AUTO_PULL = os.getenv("OLLAMA_AUTO_PULL", "false").lower() == "true"
    CHATBOT_HISTORY_TURNS = max(1, min(8, int(os.getenv("CHATBOT_HISTORY_TURNS", "4"))))
    CHATBOT_ENABLED = os.getenv("CHATBOT_ENABLED", "true").lower() == "true"
    CHATBOT_DOMAIN_GUARD = os.getenv("CHATBOT_DOMAIN_GUARD", "true").lower() == "true"
    CHATBOT_RAG_ENABLED = os.getenv("CHATBOT_RAG_ENABLED", "true").lower() == "true"
    CORS_ALLOWED_ORIGINS = allowed_origins()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "None" if APP_ENV == "production" else "Lax"
    SESSION_COOKIE_SECURE = APP_ENV == "production"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    DEMO_MODE = _DEMO_MODE
    TRUST_PROXY_HEADERS = _TRUST_PROXY_HEADERS
    OTP_LENGTH = max(6, int(os.getenv("OTP_LENGTH", "6")))
    OTP_EXPIRY_MINUTES = max(1, int(os.getenv("OTP_EXPIRY_MINUTES", "5")))
    OTP_MAX_ATTEMPTS = max(1, int(os.getenv("OTP_MAX_ATTEMPTS", "5")))
    OTP_RESEND_COOLDOWN_SECONDS = max(0, int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60")))
    OTP_RATE_LIMIT_MAX_REQUESTS = max(1, int(os.getenv("OTP_RATE_LIMIT_MAX_REQUESTS", "5")))
    OTP_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("OTP_RATE_LIMIT_WINDOW_SECONDS", "900")))
    OTP_IP_RATE_LIMIT_MAX = max(1, int(os.getenv("OTP_IP_RATE_LIMIT_MAX", "30")))
    OTP_IP_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("OTP_IP_RATE_LIMIT_WINDOW_SECONDS", "300")))
    TEMP_PASSWORD_LENGTH = max(16, int(os.getenv("TEMP_PASSWORD_LENGTH", "16")))
    RECIPE_UPLOAD_DIR = os.getenv("RECIPE_UPLOAD_DIR", str(BASE_DIR / "static" / "uploads" / "recipes"))
    RECIPE_IMAGE_MAX_BYTES = max(1024, int(os.getenv("RECIPE_IMAGE_MAX_BYTES", str(5 * 1024 * 1024))))

    @classmethod
    def validate(cls) -> None:
        if not cls.SECRET_KEY:
            raise RuntimeError("COOKMATE_SECRET_KEY is required. Set it in the root .env file.")
        if not cls.MYSQL_HOST or not cls.MYSQL_DATABASE or not cls.MYSQL_USER:
            raise RuntimeError("MYSQL_HOST, MYSQL_DATABASE and MYSQL_USER must be configured.")


def validate_gemini_configuration() -> dict[str, object]:
    """Check local configuration and SDK readiness; key validity requires a live API call."""
    errors: list[str] = []
    if not Config.GEMINI_API_KEY:
        errors.append("MISSING_API_KEY")
    for model in (Config.GEMINI_PRIMARY_MODEL, Config.GEMINI_FALLBACK_MODEL):
        if not model or not re.fullmatch(r"[A-Za-z0-9._-]+", model):
            errors.append("INVALID_MODEL_ID")
            break
    try:
        sdk_version = package_version("google-genai")
        version_parts = tuple(int(part) for part in re.findall(r"\d+", sdk_version)[:3])
        sdk_ready = version_parts >= (2, 30, 1)
    except PackageNotFoundError:
        sdk_version = ""
        sdk_ready = False
    if not sdk_ready:
        errors.append("SDK_UNAVAILABLE_OR_TOO_OLD")
    return {
        "configured": not errors,
        "api_key_status": "FOUND" if Config.GEMINI_API_KEY else "MISSING",
        "api_key_validity": "UNKNOWN",
        "api_key_source": Config.GEMINI_API_KEY_SOURCE,
        "api_key_conflict": Config.GEMINI_API_KEY_CONFLICT,
        "key_sources": Config.GEMINI_KEY_SOURCES,
        "primary_model": Config.GEMINI_PRIMARY_MODEL,
        "fallback_model": Config.GEMINI_FALLBACK_MODEL,
        "sdk_status": "READY" if sdk_ready else "ERROR",
        "sdk_version": sdk_version,
        "errors": tuple(errors),
    }

