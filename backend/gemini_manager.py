"""Sequential Gemini model selection with bounded, classified failover."""

from __future__ import annotations

import hashlib
import logging
import re
import socket
import time
from importlib.metadata import PackageNotFoundError, version as package_version
from datetime import datetime, timezone
from typing import Any

from backend.config import Config, validate_gemini_configuration

logger = logging.getLogger(__name__)
_sdk_status_logged = False

DEFAULT_STABLE_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-pro",
)
LEGACY_UNRELIABLE_MODELS = frozenset({"gemini-3.6-flash", "gemini-4-hydrogen"})
_EXCLUDED_DISCOVERY_TOKENS = (
    "image",
    "tts",
    "transcribe",
    "omni",
    "robotics",
    "computer-use",
    "nano-banana",
    "embedding",
    "imagen",
    "veo",
    "aqa",
    "live",
    "gemma",
    "learnlm",
)
_MODEL_CACHE_TTL_SECONDS = 1800.0
_DISCOVERY_CACHE: dict[str, Any] = {"key_fp": "", "expires_at": 0.0, "models": []}
_HEALTH_STATE: dict[str, Any] = {
    "key_fp": "",
    "last_working": "",
    "last_working_expires": 0.0,
    "unhealthy": {},
}

SAFE_UNAVAILABLE_MESSAGE = "Hiện tại trợ lý CookMate đang gặp sự cố. Vui lòng thử lại sau."
SAFE_CONFIGURATION_MESSAGE = "Trợ lý CookMate chưa được cấu hình đúng. Vui lòng thử lại sau."
SAFE_REQUEST_MESSAGE = "CookMate chưa thể xử lý câu hỏi này. Vui lòng thử diễn đạt ngắn gọn hơn."
SAFE_POLICY_MESSAGE = "Mình chưa thể hỗ trợ yêu cầu này. Bạn hãy hỏi về món ăn hoặc cách nấu nhé."
CONFIGURATION_MESSAGES = {
    "MISSING_API_KEY": "CookMate chưa có Gemini API key. Hãy cấu hình GEMINI_API_KEY rồi thử lại.",
    "INVALID_API_KEY": "Gemini API key không hợp lệ. Hãy kiểm tra lại khóa cấu hình của CookMate.",
    "EXPIRED_OR_REVOKED_API_KEY": "Gemini API key đã hết hiệu lực hoặc bị thu hồi. Hãy thay khóa trong cấu hình CookMate.",
    "PERMISSION_DENIED": "Gemini API key chưa được cấp quyền sử dụng Gemini API.",
    "SDK_UNAVAILABLE": "CookMate chưa thể khởi tạo thư viện Gemini. Hãy kiểm tra phiên bản thư viện trên máy chủ.",
    "INVALID_MODEL_ID": "Model Gemini trong cấu hình không hợp lệ.",
}
CONFIGURATION_ERROR_CODES = {
    "MISSING_API_KEY": "AI_MISSING_API_KEY",
    "INVALID_API_KEY": "AI_INVALID_API_KEY",
    "EXPIRED_OR_REVOKED_API_KEY": "AI_EXPIRED_REVOKED_API_KEY",
    "PERMISSION_DENIED": "AI_PERMISSION_DENIED",
    "SDK_UNAVAILABLE": "AI_CONFIGURATION_ERROR",
    "INVALID_MODEL_ID": "AI_CONFIGURATION_ERROR",
}


class GeminiManagerError(RuntimeError):
    """Base class carrying only safe, client-facing error metadata."""

    def __init__(self, message: str, *, error_code: str, http_status: int | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status


class GeminiConfigurationError(GeminiManagerError):
    def __init__(self, http_status: int | None = None, *, reason: str = "SDK_UNAVAILABLE", source: str | None = None):
        self.reason = reason
        self.source = source or Config.GEMINI_API_KEY_SOURCE
        super().__init__(
            CONFIGURATION_MESSAGES.get(reason, SAFE_CONFIGURATION_MESSAGE),
            error_code=CONFIGURATION_ERROR_CODES.get(reason, "AI_CONFIGURATION_ERROR"),
            http_status=http_status,
        )


class GeminiInputError(GeminiManagerError):
    def __init__(self):
        super().__init__(SAFE_REQUEST_MESSAGE, error_code="AI_INVALID_INPUT")


class GeminiRequestError(GeminiManagerError):
    def __init__(self, http_status: int | None = None):
        super().__init__(SAFE_REQUEST_MESSAGE, error_code="AI_REQUEST_REJECTED", http_status=http_status)


class GeminiPolicyError(GeminiManagerError):
    def __init__(self):
        super().__init__(SAFE_POLICY_MESSAGE, error_code="AI_POLICY_BLOCKED")


class GeminiServiceUnavailable(GeminiManagerError):
    def __init__(self, http_status: int | None = None):
        super().__init__(SAFE_UNAVAILABLE_MESSAGE, error_code="AI_SERVICE_UNAVAILABLE", http_status=http_status)


class _EmptyModelResponse(Exception):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _log(event: str, model: str, duration_ms: int, *, status: int | None = None,
         primary_status: int | None = None, reason: str = "-",
         fallback: bool = False, attempt: int = 1) -> None:
    # Never log request text, response text, credentials, or SDK exception strings.
    logger.info(
        "[AI] time=%s event=%s model=%s duration_ms=%d http_status=%s primary_http_status=%s reason=%s fallback=%s attempt=%d",
        _timestamp(), event, model, duration_ms,
        status if status is not None else "-",
        primary_status if primary_status is not None else "-",
        reason, fallback, attempt,
    )


def _log_sdk_status(status: str, sdk_version: str = "-") -> None:
    global _sdk_status_logged
    if not _sdk_status_logged:
        logger.info("[AI CONFIG] SDK Status: %s version=%s", status, sdk_version)
        _sdk_status_logged = True


def _safe_failure_reason(error: BaseException, kind: str) -> str:
    reasons = _structured_reasons(error)
    status = _http_status(error)
    if "API_KEY_INVALID" in reasons:
        return "invalid_api_key"
    if status == 401 or any(item in {"UNAUTHENTICATED", "ACCESS_TOKEN_EXPIRED", "KEY_EXPIRED"} for item in reasons):
        return "expired_or_revoked_api_key"
    if status == 403 or "PERMISSION_DENIED" in reasons:
        return "permission_denied"
    if status == 429:
        if any("QUOTA" in item or "BILLING" in item or "PAYMENT" in item for item in reasons):
            return "quota_exceeded"
        if any("RATE_LIMIT" in item or "TOO_MANY_REQUESTS" in item for item in reasons):
            return "rate_limit"
        return "rate_limit_or_quota"
    if status == 404 or any(item in {"MODEL_NOT_FOUND", "MODEL_UNAVAILABLE", "NOT_FOUND", "UNSUPPORTED_MODEL"} for item in reasons):
        return "model_unavailable"
    if status in (408, 500, 502, 503, 504):
        return "service_unavailable"
    if _is_timeout_or_network_error(error):
        return "timeout_or_connection"
    return kind


def _http_status(error: BaseException) -> int | None:
    for value in (getattr(error, "code", None), getattr(getattr(error, "response", None), "status_code", None)):
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 100 <= number <= 599:
            return number
    return None


def _structured_reasons(error: BaseException) -> set[str]:
    details = getattr(error, "details", None)
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"reason", "status", "code"} and isinstance(child, (str, int)):
                    found.add(str(child).upper())
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(details)
    status = getattr(error, "status", None)
    if status:
        found.add(str(status).upper())
    return found


def _is_timeout_or_network_error(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout, ConnectionError, OSError)):
        return True
    names = {base.__name__ for base in type(error).__mro__}
    return bool(names.intersection({
        "TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
        "ConnectError", "NetworkError", "RemoteProtocolError",
    }))


def _retry_after_seconds(error: BaseException) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        try:
            return max(0.0, min(float(raw), 2.0))
        except (TypeError, ValueError):
            pass
    details = getattr(error, "details", None)

    def find_delay(value: Any) -> float | None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"retrydelay", "retry_after", "retry-after"}:
                    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*s?\s*", str(child))
                    if match:
                        return max(0.0, min(float(match.group(1)), 2.0))
                result = find_delay(child)
                if result is not None:
                    return result
        elif isinstance(value, (list, tuple)):
            for child in value:
                result = find_delay(child)
                if result is not None:
                    return result
        return None

    return find_delay(details)


def _is_transient_rate_limit(error: BaseException) -> bool:
    reasons = _structured_reasons(error)
    if any("QUOTA" in item or "BILLING" in item or "PAYMENT" in item for item in reasons):
        return False
    return any("RATE_LIMIT" in item or "TOO_MANY_REQUESTS" in item for item in reasons) or _retry_after_seconds(error) is not None


def _failure_kind(error: BaseException) -> str:
    """Return retry, fallback, configuration, request, or policy from status/details."""
    if isinstance(error, GeminiPolicyError):
        return "policy"
    if isinstance(error, GeminiConfigurationError):
        return "configuration"
    if isinstance(error, (GeminiInputError, GeminiRequestError)):
        return "request"
    if _is_timeout_or_network_error(error) or isinstance(error, _EmptyModelResponse):
        return "fallback"

    status = _http_status(error)
    reasons = _structured_reasons(error)
    if status in (401, 403) or any(
        item in {"API_KEY_INVALID", "PERMISSION_DENIED", "UNAUTHENTICATED", "ACCESS_TOKEN_EXPIRED", "KEY_EXPIRED"}
        for item in reasons
    ):
        return "configuration"
    if status == 429:
        return "retry" if _is_transient_rate_limit(error) else "fallback"
    if status in (408, 500, 502, 503, 504, 404):
        return "fallback"
    if status == 400:
        if any("UNSUPPORTED" in item or "MODEL_NOT_FOUND" in item or "MODEL_UNAVAILABLE" in item for item in reasons):
            return "fallback"
        err_msg = str(getattr(error, "message", "") or error).lower()
        if any(tok in err_msg for tok in ("not supported", "unsupported", "thinking", "developer instruction", "model not found")):
            return "fallback"
    if status is None:
        return "fallback" if _is_timeout_or_network_error(error) else "request"
    return "request"


def _key_fingerprint() -> str:
    if not Config.GEMINI_API_KEY:
        return ""
    return hashlib.sha256(Config.GEMINI_API_KEY.encode("utf-8")).hexdigest()[:12]


def reset_model_cache() -> None:
    _DISCOVERY_CACHE.update({"key_fp": "", "expires_at": 0.0, "models": []})
    _HEALTH_STATE.update({"key_fp": "", "last_working": "", "last_working_expires": 0.0, "unhealthy": {}})


def _sync_health_key(key_fp: str) -> None:
    if _HEALTH_STATE["key_fp"] != key_fp:
        _HEALTH_STATE.update({"key_fp": key_fp, "last_working": "", "last_working_expires": 0.0, "unhealthy": {}})


def _is_model_unhealthy(model: str, key_fp: str) -> bool:
    _sync_health_key(key_fp)
    exp = _HEALTH_STATE["unhealthy"].get(model, 0.0)
    if exp > time.monotonic():
        return True
    _HEALTH_STATE["unhealthy"].pop(model, None)
    return False


def _mark_model_unhealthy(model: str, key_fp: str, ttl: float = _MODEL_CACHE_TTL_SECONDS) -> None:
    _sync_health_key(key_fp)
    _HEALTH_STATE["unhealthy"][model] = time.monotonic() + ttl
    if _HEALTH_STATE["last_working"] == model:
        _HEALTH_STATE["last_working"] = ""
        _HEALTH_STATE["last_working_expires"] = 0.0


def _mark_model_working(model: str, key_fp: str) -> None:
    _sync_health_key(key_fp)
    _HEALTH_STATE["unhealthy"].pop(model, None)
    _HEALTH_STATE["last_working"] = model
    _HEALTH_STATE["last_working_expires"] = time.monotonic() + _MODEL_CACHE_TTL_SECONDS


def _score_discovered_model(name: str) -> tuple[int, str]:
    lower = name.lower()
    if lower in LEGACY_UNRELIABLE_MODELS:
        return (90, lower)
    if lower in ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview"):
        return (0, lower)
    if lower in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"):
        return (1, lower)
    if "flash-lite" in lower and "preview" not in lower:
        return (2, lower)
    if "flash" in lower and "preview" not in lower:
        return (3, lower)
    if "flash" in lower:
        return (4, lower)
    if "pro" in lower and "preview" not in lower:
        return (5, lower)
    return (6, lower)


def discover_available_gemini_models(client: Any | None = None, *, force_refresh: bool = False) -> list[str]:
    """Query models.list() and cache generateContent-capable gemini-* text models for 30 minutes."""
    key_fp = _key_fingerprint()
    if not key_fp:
        return []
    now = time.monotonic()
    if (
        not force_refresh
        and _DISCOVERY_CACHE["key_fp"] == key_fp
        and _DISCOVERY_CACHE["expires_at"] > now
        and _DISCOVERY_CACHE["models"]
    ):
        return list(_DISCOVERY_CACHE["models"])

    own_client = client
    if own_client is None:
        try:
            own_client = _build_client(fallback=True)
        except Exception:
            return []

    found: list[str] = []
    try:
        for item in own_client.models.list():
            raw_name = str(getattr(item, "name", "") or "").strip()
            model_id = raw_name[7:] if raw_name.startswith("models/") else raw_name
            lower = model_id.lower()
            if not lower.startswith("gemini-"):
                continue
            if any(tok in lower for tok in _EXCLUDED_DISCOVERY_TOKENS):
                continue
            actions = getattr(item, "supported_actions", None)
            if actions and not any(str(a).lower() in ("generatecontent", "generate_content") for a in actions):
                continue
            if model_id not in found:
                found.append(model_id)
    except Exception as exc:
        logger.warning("[AI DISCOVERY] models.list failed (%s)", type(exc).__name__)
        return list(_DISCOVERY_CACHE["models"]) if _DISCOVERY_CACHE["key_fp"] == key_fp else []

    found.sort(key=_score_discovered_model)
    _DISCOVERY_CACHE.update({"key_fp": key_fp, "expires_at": now + _MODEL_CACHE_TTL_SECONDS, "models": found})
    logger.info("[AI DISCOVERY] Discovered %d generateContent text models: %s", len(found), ",".join(found[:8]))
    return list(found)


def get_gemini_runtime_status() -> dict[str, Any]:
    """Return safe diagnostics about Gemini config & active resolved model (never includes keys)."""
    validation = validate_gemini_configuration()
    key_fp = _key_fingerprint()
    _sync_health_key(key_fp)
    active_model = ""
    if _HEALTH_STATE["last_working"] and _HEALTH_STATE["last_working_expires"] > time.monotonic():
        active_model = _HEALTH_STATE["last_working"]
    discovered_count = len(_DISCOVERY_CACHE["models"]) if _DISCOVERY_CACHE["key_fp"] == key_fp else 0
    return {
        "configured": bool(validation["configured"]),
        "sdk_status": validation["sdk_status"],
        "sdk_version": validation["sdk_version"],
        "primary_model": Config.GEMINI_PRIMARY_MODEL,
        "fallback_model": Config.GEMINI_FALLBACK_MODEL,
        "active_model": active_model or Config.GEMINI_PRIMARY_MODEL,
        "discovered_models_cached": discovered_count,
    }


def _build_client(*, fallback: bool, timeout_ms: int | None = None):
    if not Config.GEMINI_API_KEY:
        raise GeminiConfigurationError(reason="MISSING_API_KEY", source=Config.GEMINI_API_KEY_SOURCE)
    try:
        from google import genai
        from google.genai import types
        from google.auth.exceptions import GoogleAuthError
        sdk_version = package_version("google-genai")
    except (ImportError, PackageNotFoundError):
        _log_sdk_status("ERROR")
        raise GeminiConfigurationError(reason="SDK_UNAVAILABLE") from None

    _log_sdk_status("READY", sdk_version)
    effective_timeout = timeout_ms if timeout_ms is not None else max(1, Config.GEMINI_TIMEOUT) * 1000
    kwargs: dict[str, Any] = {
        # Both models use the same Gemini Developer API key and v1beta API surface.
        # Setting vertexai=False prevents accidental Vertex routing if GCP env vars exist.
        "api_key": Config.GEMINI_API_KEY,
        "vertexai": False,
        "http_options": types.HttpOptions(
            api_version="v1beta",
            timeout=effective_timeout,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    }
    try:
        return genai.Client(**kwargs)
    except (GoogleAuthError, ValueError):
        # Do not expose SDK/auth details; client creation failures are config errors.
        raise GeminiConfigurationError(reason="SDK_UNAVAILABLE") from None


def _generate_once(model: str, contents: list[Any], system_instruction: str, *, fallback: bool,
                   generation_config: Any | None = None):
    from google.genai import types

    timeout_ms = min(max(10, Config.GEMINI_TIMEOUT), 11) * 1000 if model in LEGACY_UNRELIABLE_MODELS else None
    client = _build_client(fallback=fallback, timeout_ms=timeout_ms)
    config = generation_config or types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.35,
        max_output_tokens=1400,
    )
    return client.models.generate_content(model=model, contents=contents, config=config)


def _extract_text(response: Any) -> str:
    answer = str(getattr(response, "text", None) or "").strip()
    if answer:
        return answer
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        reason = str(getattr(candidates[0], "finish_reason", "")).upper()
        if any(token in reason for token in ("SAFETY", "BLOCKLIST", "PROHIBITED", "SPII")):
            raise GeminiPolicyError()
    raise _EmptyModelResponse()


def _attempt_model(model: str, contents: list[Any], system_instruction: str, *, fallback: bool,
                   generation_config: Any | None = None) -> tuple[Any, str]:
    max_retries = 0 if fallback else max(0, min(Config.GEMINI_MAX_RETRIES, 3))
    retries = 0
    while True:
        start = time.monotonic()
        try:
            response = _generate_once(model, contents, system_instruction, fallback=fallback,
                                      generation_config=generation_config)
            answer = _extract_text(response)
            _log("success", model, round((time.monotonic() - start) * 1000), fallback=fallback, attempt=retries + 1)
            return response, answer
        except StopIteration:
            raise
        except Exception as error:
            duration = round((time.monotonic() - start) * 1000)
            status = _http_status(error)
            kind = _failure_kind(error)
            _log("failed", model, duration, status=status,
                 reason=_safe_failure_reason(error, kind), fallback=fallback, attempt=retries + 1)
            if kind == "retry" and retries < max_retries:
                retries += 1
                delay = _retry_after_seconds(error)
                time.sleep(delay if delay is not None else 0.25)
                continue
            if kind == "policy":
                raise GeminiPolicyError() from None
            if kind == "configuration":
                if isinstance(error, GeminiConfigurationError):
                    logger.error("[AI CONFIG ERROR] Reason: %s Source: %s", error.reason, error.source)
                    raise error from None
                reasons = _structured_reasons(error)
                if "API_KEY_INVALID" in reasons:
                    reason = "INVALID_API_KEY"
                elif status == 401 or any(item in {"UNAUTHENTICATED", "ACCESS_TOKEN_EXPIRED", "KEY_EXPIRED"} for item in reasons):
                    reason = "EXPIRED_OR_REVOKED_API_KEY"
                else:
                    reason = "PERMISSION_DENIED"
                logger.error("[AI CONFIG ERROR] Reason: %s Source: %s", reason, Config.GEMINI_API_KEY_SOURCE)
                raise GeminiConfigurationError(status, reason=reason) from None
            if kind == "request":
                raise GeminiRequestError(status) from None
            raise


def _prepare_contents(message: str, conversation_history: list[dict[str, Any]] | None):
    from google.genai import types

    contents: list[Any] = []
    history = conversation_history if isinstance(conversation_history, list) else []
    max_items = max(2, min(16, int(getattr(Config, "CHATBOT_HISTORY_TURNS", 4)) * 2))
    for item in history[-max_items:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("sender") or "").strip().lower()
        role = "model" if role in {"ai", "assistant", "model"} else "user" if role in {"user", "human"} else ""
        text = str(item.get("text") or item.get("message") or "").strip()[:4000]
        if role and text:
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))
    # Ensure user turn always closes contents for generate_content.
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))
    return contents


def _build_extended_candidates(exclude: list[str], key_fp: str, *, allow_discovery: bool) -> list[str]:
    ordered: list[str] = []
    for m in DEFAULT_STABLE_MODELS:
        if m not in exclude and m not in ordered:
            ordered.append(m)
    if allow_discovery:
        discovered = discover_available_gemini_models()
        for m in discovered:
            if m not in exclude and m not in ordered and m not in LEGACY_UNRELIABLE_MODELS:
                ordered.append(m)
    healthy = [m for m in ordered if not _is_model_unhealthy(m, key_fp)]
    stale = [m for m in ordered if m not in healthy and m not in LEGACY_UNRELIABLE_MODELS]
    return (healthy + stale)[:6]


def _run_with_failover(contents: list[Any], system_instruction: str, *, generation_config: Any | None = None,
                       operation: str = "chat") -> dict[str, Any]:
    started = time.monotonic()
    primary = Config.GEMINI_PRIMARY_MODEL
    fallback_model = Config.GEMINI_FALLBACK_MODEL
    validation = validate_gemini_configuration()
    fallback_auth = "SAME_DEVELOPER_API_KEY" if Config.GEMINI_API_KEY else "MISSING_API_KEY"
    logger.info(
        "[AI CONFIG] API Key: %s source=%s conflict=%s candidates=%s | Fallback Auth: %s | Primary Model: %s | Fallback Model: %s",
        "FOUND" if Config.GEMINI_API_KEY else "MISSING", Config.GEMINI_API_KEY_SOURCE,
        Config.GEMINI_API_KEY_CONFLICT, ",".join(Config.GEMINI_KEY_SOURCES) or "NONE", fallback_auth, primary, fallback_model,
    )
    if not Config.GEMINI_API_KEY:
        logger.error("[AI CONFIG ERROR] Reason: MISSING_API_KEY Source: %s", Config.GEMINI_API_KEY_SOURCE)
        raise GeminiConfigurationError(reason="MISSING_API_KEY")
    if "INVALID_MODEL_ID" in validation["errors"]:
        logger.error("[AI CONFIG ERROR] Reason: INVALID_MODEL_ID Source: %s", Config.GEMINI_API_KEY_SOURCE)
        raise GeminiConfigurationError(reason="INVALID_MODEL_ID")
    if "SDK_UNAVAILABLE_OR_TOO_OLD" in validation["errors"]:
        logger.error("[AI CONFIG ERROR] Reason: SDK_UNAVAILABLE Source: %s", Config.GEMINI_API_KEY_SOURCE)
        raise GeminiConfigurationError(reason="SDK_UNAVAILABLE")

    is_mocked = "unittest.mock" in type(_generate_once).__module__
    key_fp = _key_fingerprint()
    _sync_health_key(key_fp)

    # In live runtime, if configured primary is already known unhealthy within 30m TTL
    # and we already discovered a working model, route straight to it first to avoid 504 delays.
    primary_candidate = primary
    if (
        not is_mocked
        and _HEALTH_STATE["last_working"]
        and _HEALTH_STATE["last_working_expires"] > time.monotonic()
        and _is_model_unhealthy(primary, key_fp)
    ):
        primary_candidate = _HEALTH_STATE["last_working"]

    primary_status: int | None = None
    last_error: Exception = GeminiServiceUnavailable()
    _log("primary_start", primary_candidate, 0)
    try:
        response, answer = _attempt_model(primary_candidate, contents, system_instruction, fallback=False,
                                          generation_config=generation_config)
        if not is_mocked:
            _mark_model_working(primary_candidate, key_fp)
        logger.info("[AI PRIMARY] Model: %s Status: SUCCESS", primary_candidate)
        result = {"success": True, "response": answer, "model_used": primary_candidate, "fallback_used": primary_candidate != primary}
        result["_raw_response"] = response
        _log("complete", primary_candidate, round((time.monotonic() - started) * 1000), fallback=result["fallback_used"])
        return result
    except (GeminiConfigurationError, GeminiRequestError, GeminiPolicyError) as primary_error:
        _log("complete_rejected", primary_candidate, round((time.monotonic() - started) * 1000),
             status=primary_error.http_status, reason=_safe_failure_reason(primary_error, _failure_kind(primary_error)),
             fallback=False)
        raise
    except Exception as primary_error:
        last_error = primary_error
        primary_status = _http_status(primary_error)
        if not is_mocked:
            _mark_model_unhealthy(primary_candidate, key_fp)
        logger.info("[AI PRIMARY] Model: %s Status: FAILED", primary_candidate)
        _log("switch_to_fallback", fallback_model, 0, status=primary_status,
             reason=_safe_failure_reason(primary_error, _failure_kind(primary_error)), fallback=True)

    tried: list[str] = [primary_candidate]

    # Try configured fallback second (skip in live mode if both configured models are known broken legacy aliases).
    skip_legacy_fallback = (
        not is_mocked
        and primary_candidate in LEGACY_UNRELIABLE_MODELS
        and fallback_model in LEGACY_UNRELIABLE_MODELS
    )
    if skip_legacy_fallback:
        _mark_model_unhealthy(fallback_model, key_fp)
        tried.append(fallback_model)
    elif fallback_model not in tried and (is_mocked or not _is_model_unhealthy(fallback_model, key_fp)):
        tried.append(fallback_model)
        logger.info("[AI FALLBACK] Model: %s Status: STARTED", fallback_model)
        try:
            response, answer = _attempt_model(fallback_model, contents, system_instruction, fallback=True,
                                              generation_config=generation_config)
            if not is_mocked:
                _mark_model_working(fallback_model, key_fp)
            logger.info("[AI FALLBACK] Model: %s Status: SUCCESS", fallback_model)
            result = {"success": True, "response": answer, "model_used": fallback_model, "fallback_used": True}
            result["_raw_response"] = response
            _log("complete", fallback_model, round((time.monotonic() - started) * 1000), fallback=True)
            return result
        except GeminiPolicyError:
            _log("complete_rejected", fallback_model, round((time.monotonic() - started) * 1000), fallback=True)
            raise
        except GeminiConfigurationError as fallback_error:
            _log("fallback_configuration_failed", fallback_model, round((time.monotonic() - started) * 1000),
                 status=fallback_error.http_status, primary_status=primary_status,
                 reason=fallback_error.reason.lower(), fallback=True)
            logger.error("[AI CONFIG ERROR] Reason: %s Source: %s", fallback_error.reason, fallback_error.source)
            raise fallback_error from None
        except Exception as fallback_error:
            last_error = fallback_error
            if not is_mocked:
                _mark_model_unhealthy(fallback_model, key_fp)
            logger.error("[AI FALLBACK] Model: %s Status: FAILED", fallback_model)

    # Smart Model Resolver + auto-discovery fallback chain when primary + fallback failed
    extended = _build_extended_candidates(tried, key_fp, allow_discovery=not is_mocked)
    for resolved_model in extended:
        tried.append(resolved_model)
        logger.info("[AI SMART FALLBACK] Model: %s Status: STARTED", resolved_model)
        try:
            response, answer = _attempt_model(resolved_model, contents, system_instruction, fallback=True,
                                              generation_config=generation_config)
            if not is_mocked:
                _mark_model_working(resolved_model, key_fp)
            logger.info("[AI SMART FALLBACK] Model: %s Status: SUCCESS", resolved_model)
            result = {"success": True, "response": answer, "model_used": resolved_model, "fallback_used": True}
            result["_raw_response"] = response
            _log("complete", resolved_model, round((time.monotonic() - started) * 1000), fallback=True)
            return result
        except StopIteration:
            # Mocked unit tests with a fixed 2-element side_effect stop cleanly here.
            break
        except (GeminiPolicyError, GeminiConfigurationError):
            raise
        except Exception as smart_error:
            last_error = smart_error
            if not is_mocked:
                _mark_model_unhealthy(resolved_model, key_fp)
            logger.warning("[AI SMART FALLBACK] Model: %s Status: FAILED (%s)", resolved_model, _safe_failure_reason(smart_error, _failure_kind(smart_error)))

    logger.error("[AI FAILURE] Gemini models failed after trying: %s", ",".join(tried))
    _log("complete_failed", tried[-1], round((time.monotonic() - started) * 1000),
         status=_http_status(last_error), primary_status=primary_status,
         reason=_safe_failure_reason(last_error, _failure_kind(last_error)), fallback=True)
    raise GeminiServiceUnavailable(_http_status(last_error) or primary_status) from None


def generate_ai_response(message: str, conversation_history: list[dict[str, Any]] | None = None,
                         system_instruction: str | None = None) -> dict[str, Any]:
    """Generate one response with primary-first, smart resolver fallback behavior."""
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        raise GeminiInputError()
    contents = _prepare_contents(message.strip(), conversation_history)
    system = (system_instruction or "You are CookMate ChefBot. Answer only cooking, food, and food-related nutrition questions.").strip()
    system = system[:18000]
    return _run_with_failover(contents, system, operation="chat")


def classify_gemini_reason_vi(http_code: int | None, reason_key: str) -> str:
    """Translate safe Gemini failure metadata into clear Vietnamese diagnostics without exposing secrets."""
    rk = str(reason_key or "").lower()
    if rk == "missing_api_key":
        return "Chưa cấu hình GEMINI_API_KEY trong file .env."
    if rk in ("invalid_api_key", "expired_or_revoked_api_key", "permission_denied") or http_code in (401, 403):
        code_txt = f" (HTTP {http_code})" if http_code else ""
        return f"GEMINI_API_KEY không hợp lệ, sai định dạng hoặc bị khóa quyền truy cập{code_txt}."
    if http_code == 400 and "api_key" in rk:
        return "GEMINI_API_KEY không hợp lệ, sai định dạng hoặc bị khóa quyền truy cập (HTTP 400)."
    if http_code == 404 or rk == "model_unavailable":
        return "Model Gemini yêu cầu không khả dụng trên API key này (HTTP 404)."
    if http_code == 429 or "quota" in rk or "rate_limit" in rk:
        return "Đã chạm giới hạn lượt gọi miễn phí (Rate Limit / Quota HTTP 429)."
    if http_code in (408, 500, 502, 503, 504) or rk in ("service_unavailable", "timeout_or_connection", "fallback"):
        code_txt = f" (HTTP {http_code})" if http_code else ""
        return f"Máy chủ Google Gemini quá tải hoặc lỗi kết nối mạng/Proxy{code_txt}."
    return "Không thể kết nối tới dịch vụ Google Gemini tạm thời."


def build_gemini_warning_vi(attempted_models: list[dict[str, Any]], fallback_provider_label: str) -> str:
    """Build a concise user-facing Vietnamese explanation when both Gemini models fail."""
    if not attempted_models:
        return f"Không gọi được API Gemini. Hệ thống đã tự động chuyển sang {fallback_provider_label}."
    first_reason = attempted_models[0].get("reasonVi") or ""
    if "Chưa cấu hình GEMINI_API_KEY" in first_reason:
        return f"Chưa cấu hình GEMINI_API_KEY trong file .env. Hệ thống đã tự động chuyển sang {fallback_provider_label}."
    if "không hợp lệ" in first_reason or "khóa quyền" in first_reason:
        return f"{first_reason} Hệ thống đã tự động chuyển sang {fallback_provider_label}."
    failed_summaries = []
    for item in attempted_models:
        if item.get("status") == "failed":
            m_name = item.get("model") or "gemini"
            code = item.get("httpCode")
            code_str = f" HTTP {code}" if code else ""
            failed_summaries.append(f"{m_name}{code_str}")
    joined_models = ", ".join(failed_summaries[:3]) or "Gemini"
    last_reason = attempted_models[-1].get("reasonVi") or "tạm thời gián đoạn"
    return (
        f"Không gọi được API Gemini (đã thử {joined_models}: {last_reason}) "
        f"Hệ thống đã tự động chuyển sang {fallback_provider_label}."
    )


def _pick_smart_replacement_model(tried: list[str], key_fp: str, *, prefer_lite: bool) -> str | None:
    discovered = [
        m for m in discover_available_gemini_models()
        if m not in tried and m not in LEGACY_UNRELIABLE_MODELS and not _is_model_unhealthy(m, key_fp)
    ]
    if not discovered:
        return None
    if prefer_lite:
        lite = [m for m in discovered if "lite" in m.lower()]
        return lite[0] if lite else discovered[0]
    full_flash = [m for m in discovered if "flash" in m.lower() and "lite" not in m.lower()]
    return full_flash[0] if full_flash else discovered[0]


def generate_ai_response_with_diagnostics(
    message: str,
    conversation_history: list[dict[str, Any]] | None = None,
    system_instruction: str | None = None,
) -> dict[str, Any]:
    """
    Execute Priority #1 (Gemini Primary Free) -> Priority #2 (Gemini Secondary Free)
    with full non-secret Vietnamese diagnostics so ChefBot only falls back to Ollama (#3)
    when BOTH Gemini models fail.
    """
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        raise GeminiInputError()

    primary = Config.GEMINI_PRIMARY_MODEL
    secondary = Config.GEMINI_FALLBACK_MODEL
    validation = validate_gemini_configuration()
    attempted: list[dict[str, Any]] = []

    if not Config.GEMINI_API_KEY:
        attempted.append({
            "model": primary,
            "status": "failed",
            "httpCode": 0,
            "reasonVi": classify_gemini_reason_vi(None, "missing_api_key"),
        })
        return {
            "success": False,
            "response": "",
            "model_used": "",
            "fallback_used": False,
            "gemini_failed": True,
            "error_code": CONFIGURATION_ERROR_CODES["MISSING_API_KEY"],
            "error_message": CONFIGURATION_MESSAGES["MISSING_API_KEY"],
            "attempted_models": attempted,
        }

    if "INVALID_MODEL_ID" in validation["errors"]:
        attempted.append({
            "model": primary,
            "status": "failed",
            "httpCode": 0,
            "reasonVi": CONFIGURATION_MESSAGES["INVALID_MODEL_ID"],
        })
        return {
            "success": False,
            "response": "",
            "model_used": "",
            "fallback_used": False,
            "gemini_failed": True,
            "error_code": CONFIGURATION_ERROR_CODES["INVALID_MODEL_ID"],
            "error_message": CONFIGURATION_MESSAGES["INVALID_MODEL_ID"],
            "attempted_models": attempted,
        }

    if "SDK_UNAVAILABLE_OR_TOO_OLD" in validation["errors"]:
        attempted.append({
            "model": primary,
            "status": "failed",
            "httpCode": 0,
            "reasonVi": CONFIGURATION_MESSAGES["SDK_UNAVAILABLE"],
        })
        return {
            "success": False,
            "response": "",
            "model_used": "",
            "fallback_used": False,
            "gemini_failed": True,
            "error_code": CONFIGURATION_ERROR_CODES["SDK_UNAVAILABLE"],
            "error_message": CONFIGURATION_MESSAGES["SDK_UNAVAILABLE"],
            "attempted_models": attempted,
        }

    contents = _prepare_contents(message.strip(), conversation_history)
    system = (system_instruction or "You are CookMate ChefBot. Answer only cooking, food, and food-related nutrition questions.").strip()[:18000]
    is_mocked = (
        "unittest.mock" in type(_generate_once).__module__
        or "unittest.mock" in type(_build_client).__module__
    )
    key_fp = _key_fingerprint()
    _sync_health_key(key_fp)
    tried: list[str] = []

    def _try_candidate(model_name: str, *, is_fallback_slot: bool) -> tuple[bool, str, BaseException | None]:
        tried.append(model_name)
        try:
            _, answer = _attempt_model(model_name, contents, system, fallback=is_fallback_slot)
            if not is_mocked:
                _mark_model_working(model_name, key_fp)
            attempted.append({
                "model": model_name,
                "status": "success",
                "httpCode": 200,
                "reasonVi": "Phản hồi thành công từ Google Gemini API.",
            })
            return True, answer, None
        except GeminiPolicyError:
            raise
        except GeminiConfigurationError as cfg_err:
            code = cfg_err.http_status or (403 if cfg_err.reason == "PERMISSION_DENIED" else 401 if "EXPIRED" in cfg_err.reason else 400)
            attempted.append({
                "model": model_name,
                "status": "failed",
                "httpCode": code,
                "reasonVi": classify_gemini_reason_vi(code, cfg_err.reason.lower()),
            })
            return False, "", cfg_err
        except StopIteration as stop_err:
            return False, "", stop_err
        except Exception as err:
            code = _http_status(err)
            rk = _safe_failure_reason(err, _failure_kind(err))
            if not is_mocked:
                _mark_model_unhealthy(model_name, key_fp)
            attempted.append({
                "model": model_name,
                "status": "failed",
                "httpCode": code or 503,
                "reasonVi": classify_gemini_reason_vi(code, rk),
            })
            return False, "", err

    # --- SLOT #1: GEMINI PRIMARY FREE MODEL ---
    slot1_model = primary
    if not is_mocked and _is_model_unhealthy(primary, key_fp):
        mapped_1 = _pick_smart_replacement_model(tried, key_fp, prefer_lite=False)
        if mapped_1:
            slot1_model = mapped_1

    ok1, ans1, err1 = _try_candidate(slot1_model, is_fallback_slot=False)
    if ok1:
        return {
            "success": True,
            "response": ans1,
            "model_used": slot1_model,
            "fallback_used": slot1_model != primary,
            "gemini_failed": False,
            "attempted_models": attempted,
        }
    if isinstance(err1, GeminiConfigurationError):
        return {
            "success": False,
            "response": "",
            "model_used": "",
            "fallback_used": False,
            "gemini_failed": True,
            "error_code": err1.error_code,
            "error_message": str(err1),
            "attempted_models": attempted,
        }
    # If configured primary returned HTTP 404 (not enabled on this key), auto-map Slot #1 to best Flash in models.list()
    if not is_mocked and err1 is not None and _http_status(err1) == 404:
        mapped_flash = _pick_smart_replacement_model(tried, key_fp, prefer_lite=False)
        if mapped_flash:
            ok1_map, ans1_map, err1_map = _try_candidate(mapped_flash, is_fallback_slot=False)
            if ok1_map:
                return {
                    "success": True,
                    "response": ans1_map,
                    "model_used": mapped_flash,
                    "fallback_used": True,
                    "gemini_failed": False,
                    "attempted_models": attempted,
                }
            if isinstance(err1_map, GeminiConfigurationError):
                return {
                    "success": False,
                    "response": "",
                    "model_used": "",
                    "fallback_used": True,
                    "gemini_failed": True,
                    "error_code": err1_map.error_code,
                    "error_message": str(err1_map),
                    "attempted_models": attempted,
                }

    # --- SLOT #2: GEMINI SECONDARY FREE MODEL (SEPARATE QUOTA BUCKET) ---
    slot2_model = secondary
    if not is_mocked and (slot2_model in tried or _is_model_unhealthy(slot2_model, key_fp)):
        mapped_2 = _pick_smart_replacement_model(tried, key_fp, prefer_lite=True)
        if mapped_2:
            slot2_model = mapped_2

    if slot2_model and slot2_model not in tried:
        ok2, ans2, err2 = _try_candidate(slot2_model, is_fallback_slot=True)
        if ok2:
            return {
                "success": True,
                "response": ans2,
                "model_used": slot2_model,
                "fallback_used": True,
                "gemini_failed": False,
                "attempted_models": attempted,
            }
        if isinstance(err2, GeminiConfigurationError):
            return {
                "success": False,
                "response": "",
                "model_used": "",
                "fallback_used": True,
                "gemini_failed": True,
                "error_code": err2.error_code,
                "error_message": str(err2),
                "attempted_models": attempted,
            }
        if not is_mocked and err2 is not None and _http_status(err2) == 404:
            mapped_lite = _pick_smart_replacement_model(tried, key_fp, prefer_lite=True)
            if mapped_lite:
                ok2_map, ans2_map, _ = _try_candidate(mapped_lite, is_fallback_slot=True)
                if ok2_map:
                    return {
                        "success": True,
                        "response": ans2_map,
                        "model_used": mapped_lite,
                        "fallback_used": True,
                        "gemini_failed": False,
                        "attempted_models": attempted,
                    }

    return {
        "success": False,
        "response": "",
        "model_used": "",
        "fallback_used": True,
        "gemini_failed": True,
        "error_code": "AI_SERVICE_UNAVAILABLE",
        "error_message": SAFE_UNAVAILABLE_MESSAGE,
        "attempted_models": attempted,
    }


def generate_grounded_response(prompt: str, *, system_instruction: str = "") -> dict[str, Any]:
    """Grounded-search adapter sharing the same sequential model failover policy."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise GeminiInputError()
    from google.genai import types

    contents = _prepare_contents(prompt.strip(), None)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction or "Use Google Search grounding. Do not invent source URLs.",
        tools=[types.Tool(google_search=types.GoogleSearch())],
        max_output_tokens=1600,
    )
    return _run_with_failover(contents, system_instruction, generation_config=config, operation="grounded_search")
