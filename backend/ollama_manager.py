"""Local Ollama chat client with explicit, verifiable thinking suppression."""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.config import BASE_DIR, Config

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Safe failure category used to decide whether to invoke Gemini."""

    def __init__(self, reason: str, *, http_status: int | None = None):
        self.reason = reason
        self.http_status = http_status
        super().__init__(reason)


def _request_json(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        f"{Config.OLLAMA_BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    with urlopen(request, timeout=Config.OLLAMA_TIMEOUT) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise OllamaError("INVALID_RESPONSE")
    return decoded


@lru_cache(maxsize=8)
def _server_profile(base_url: str, model: str) -> tuple[str, frozenset[str]]:
    try:
        version_payload = _request_json_from(base_url, "/api/version")
    except HTTPError as error:
        reason = "OLLAMA_VERSION_ENDPOINT_UNAVAILABLE" if error.code == 404 else "OLLAMA_PROFILE_CHECK_FAILED"
        raise OllamaError(reason, http_status=error.code) from None
    try:
        model_payload = _request_json_from(base_url, "/api/show", {"model": model})
    except HTTPError as error:
        reason = "MODEL_UNAVAILABLE" if error.code == 404 else "OLLAMA_PROFILE_CHECK_FAILED"
        raise OllamaError(reason, http_status=error.code) from None
    version = str(version_payload.get("version") or "UNKNOWN")
    capabilities = frozenset(str(value).lower() for value in (model_payload.get("capabilities") or []))
    return version, capabilities


def _request_json_from(base_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    with urlopen(request, timeout=Config.OLLAMA_TIMEOUT) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise OllamaError("INVALID_RESPONSE")
    return decoded


def _history_messages(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    if not isinstance(history, list):
        return []
    messages: list[dict[str, str]] = []
    for item in history[-(Config.CHATBOT_HISTORY_TURNS * 2):]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("sender") or "").strip().lower()
        role = "assistant" if role in {"assistant", "ai", "model"} else "user" if role in {"user", "human"} else ""
        content = str(item.get("text") or item.get("message") or "").strip()
        if role and content:
            messages.append({"role": role, "content": content[:3000]})
    return messages


def _think_unsupported(error_payload: dict[str, Any]) -> bool:
    message = str(error_payload.get("error") or "").lower()
    return "think" in message and any(word in message for word in ("unsupported", "unknown", "invalid", "not supported", "unrecognized"))


def _raise_http_error(error: HTTPError, *, server_version: str = "UNKNOWN") -> None:
    try:
        payload = json.loads(error.read(8192).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if _think_unsupported(payload):
        logger.error(
            "[OLLAMA CONFIG ERROR] Reason: THINK_PARAMETER_UNSUPPORTED OllamaVersion: %s Model: %s HTTP: %s",
            server_version,
            Config.OLLAMA_MODEL,
            error.code,
        )
        raise OllamaError("THINK_PARAMETER_UNSUPPORTED", http_status=error.code) from None
    if error.code == 404:
        reason = "MODEL_UNAVAILABLE"
    elif error.code in (408, 504):
        reason = "TIMEOUT"
    elif error.code >= 500:
        reason = "OLLAMA_SERVICE_ERROR"
    else:
        reason = "OLLAMA_REQUEST_REJECTED"
    logger.warning("[OLLAMA] event=failed model=%s http_status=%d reason=%s", Config.OLLAMA_MODEL, error.code, reason)
    raise OllamaError(reason, http_status=error.code) from None


def generate_ollama_response(
    message: str,
    *,
    system_instruction: str,
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call /api/chat with think=false at the request top level and use content only."""
    if not isinstance(message, str) or not message.strip():
        raise OllamaError("EMPTY_INPUT")

    messages = [{"role": "system", "content": system_instruction}]
    messages.extend(_history_messages(conversation_history))
    messages.append({"role": "user", "content": message.strip()[:2000]})
    request_body: dict[str, Any] = {
        "model": Config.OLLAMA_MODEL,
        "messages": messages,
        "think": False,
        "stream": False,
        "keep_alive": Config.OLLAMA_KEEP_ALIVE,
        "options": {
            "num_ctx": Config.OLLAMA_NUM_CTX,
            "num_predict": Config.OLLAMA_NUM_PREDICT,
            "temperature": 0.3,
        },
    }

    started = time.perf_counter()
    try:
        try:
            server_version, capabilities = _server_profile(Config.OLLAMA_BASE_URL, Config.OLLAMA_MODEL)
        except OllamaError as error:
            logger.error(
                "[OLLAMA CONFIG ERROR] Reason: %s OllamaVersion: UNKNOWN Model: %s HTTP: %s",
                error.reason,
                Config.OLLAMA_MODEL,
                error.http_status or "-",
            )
            raise
        except HTTPError as error:
            if error.code == 404:
                logger.error(
                    "[OLLAMA CONFIG ERROR] Reason: VERSION_OR_MODEL_METADATA_UNAVAILABLE Model: %s HTTP: %s",
                    Config.OLLAMA_MODEL,
                    error.code,
                )
                raise OllamaError("VERSION_OR_MODEL_METADATA_UNAVAILABLE", http_status=error.code) from None
            _raise_http_error(error)
        except (URLError, TimeoutError, socket.timeout, OSError, json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("[OLLAMA] event=failed model=%s reason=PROFILE_CHECK_FAILED", Config.OLLAMA_MODEL)
            raise OllamaError("PROFILE_CHECK_FAILED") from None
        if "thinking" not in capabilities:
            logger.error(
                "[OLLAMA CONFIG ERROR] Reason: MODEL_THINKING_CAPABILITY_UNAVAILABLE OllamaVersion: %s Model: %s",
                server_version,
                Config.OLLAMA_MODEL,
            )
            raise OllamaError("MODEL_THINKING_CAPABILITY_UNAVAILABLE")
        response = _request_json("/api/chat", request_body)
    except HTTPError as error:
            _raise_http_error(error, server_version=server_version)
    except (TimeoutError, socket.timeout):
        logger.warning("[OLLAMA] event=failed model=%s reason=TIMEOUT timeout_seconds=%d", Config.OLLAMA_MODEL, Config.OLLAMA_TIMEOUT)
        raise OllamaError("TIMEOUT") from None
    except URLError as error:
        reason = "TIMEOUT" if isinstance(error.reason, (TimeoutError, socket.timeout)) else "CONNECTION_FAILED"
        logger.warning("[OLLAMA] event=failed model=%s reason=%s", Config.OLLAMA_MODEL, reason)
        raise OllamaError(reason) from None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("[OLLAMA] event=failed model=%s reason=CONNECTION_OR_RESPONSE_ERROR", Config.OLLAMA_MODEL)
        raise OllamaError("CONNECTION_OR_RESPONSE_ERROR") from None

    response_message = response.get("message")
    if not isinstance(response_message, dict):
        logger.warning("[OLLAMA] event=failed model=%s reason=INVALID_RESPONSE", Config.OLLAMA_MODEL)
        raise OllamaError("INVALID_RESPONSE")

    if str(response.get("done_reason") or "").lower() == "length":
        logger.warning("[OLLAMA] event=failed model=%s reason=TRUNCATED_CONTENT", Config.OLLAMA_MODEL)
        raise OllamaError("TRUNCATED_CONTENT")

    # Never use the thinking field. If the server returns it despite think=false,
    # thinking suppression was not confirmed; discard the response and fail over.
    if response_message.get("thinking"):
        logger.error(
            "[OLLAMA CONFIG ERROR] Reason: THINK_FALSE_NOT_HONORED Model: %s OllamaVersion: %s",
            Config.OLLAMA_MODEL,
            server_version,
        )
        raise OllamaError("THINK_FALSE_NOT_HONORED")

    content = response_message.get("content")
    content = content.strip() if isinstance(content, str) else ""
    if not content:
        logger.warning("[OLLAMA] event=failed model=%s reason=EMPTY_CONTENT", Config.OLLAMA_MODEL)
        raise OllamaError("EMPTY_CONTENT")
    if re.search(r"<think(?:ing)?\b|</think(?:ing)?\s*>", content, re.IGNORECASE):
        logger.error("[OLLAMA CONFIG ERROR] Reason: THINKING_LEAK_IN_CONTENT Model: %s", Config.OLLAMA_MODEL)
        raise OllamaError("THINKING_LEAK_IN_CONTENT")

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    metrics = {
        "duration_ms": elapsed_ms,
        "total_duration_ms": round((response.get("total_duration") or 0) / 1_000_000),
        "load_duration_ms": round((response.get("load_duration") or 0) / 1_000_000),
        "prompt_eval_count": int(response.get("prompt_eval_count") or 0),
        "eval_count": int(response.get("eval_count") or 0),
        "response_chars": len(content),
    }
    logger.info(
        "[OLLAMA] event=success model=%s ollama_version=%s think_requested=false duration_ms=%d load_duration_ms=%d prompt_tokens=%d output_tokens=%d keep_alive=%s num_ctx=%d",
        Config.OLLAMA_MODEL,
        server_version,
        metrics["duration_ms"],
        metrics["load_duration_ms"],
        metrics["prompt_eval_count"],
        metrics["eval_count"],
        Config.OLLAMA_KEEP_ALIVE,
        Config.OLLAMA_NUM_CTX,
    )
    return {"response": content, "model_used": f"ollama/{Config.OLLAMA_MODEL}", "metrics": metrics, "fallback_used": False}


def _normalize_model_tag(name: str) -> str:
    cleaned = str(name or "").strip().lower()
    if ":" not in cleaned and cleaned:
        return f"{cleaned}:latest"
    return cleaned


class OllamaServiceManager:
    """Lifecycle manager to auto-start and warm up local Ollama without failing Flask."""

    _lock = threading.Lock()
    _proc: subprocess.Popen[bytes] | None = None
    _spawned_by_cookmate = False
    _warmed_up = False
    _warmup_started = False
    _last_error = ""
    _cleanup_registered = False

    @classmethod
    def find_ollama_binary(cls) -> str | None:
        which = shutil.which("ollama")
        if which:
            return which
        if sys.platform == "win32":
            candidates = [
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Ollama" / "ollama.exe",
            ]
            for path in candidates:
                if path and path.is_file():
                    return str(path)
        return None

    @classmethod
    def list_local_models(cls, *, timeout: float = 2.5) -> tuple[bool, list[str]]:
        request = Request(f"{Config.OLLAMA_BASE_URL}/api/tags", method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                if getattr(response, "status", 200) != 200:
                    return False, []
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, socket.timeout, OSError, ValueError):
            return False, []
        models = payload.get("models") if isinstance(payload, dict) else []
        names = [str(item.get("name") or "").strip() for item in (models or []) if isinstance(item, dict) and item.get("name")]
        return True, names

    @classmethod
    def is_alive(cls, *, timeout: float = 2.5) -> bool:
        alive, _ = cls.list_local_models(timeout=timeout)
        return alive

    @classmethod
    def has_model(cls, model: str | None = None, *, timeout: float = 2.5) -> tuple[bool, list[str]]:
        target = str(model or Config.OLLAMA_MODEL).strip()
        alive, available = cls.list_local_models(timeout=timeout)
        if not alive or not target:
            return False, available
        target_norm = _normalize_model_tag(target)
        for item in available:
            if item.strip().lower() == target.lower() or _normalize_model_tag(item) == target_norm:
                return True, available
        return False, available

    @classmethod
    def _register_cleanup(cls) -> None:
        if cls._cleanup_registered:
            return
        cls._cleanup_registered = True
        atexit.register(cls.shutdown_if_owned)

        def _handle_signal(_signum: int, _frame: Any) -> None:
            cls.shutdown_if_owned()

        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    existing = signal.getsignal(sig)
                    if existing in (signal.SIG_DFL, None):
                        signal.signal(sig, _handle_signal)
                except (ValueError, RuntimeError):
                    pass

    @classmethod
    def shutdown_if_owned(cls) -> None:
        with cls._lock:
            proc = cls._proc
            owned = cls._spawned_by_cookmate
            cls._proc = None
            cls._spawned_by_cookmate = False
        if owned and proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=4)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            logger.info("[OLLAMA LIFECYCLE] Stopped CookMate-owned ollama serve process.")

    @classmethod
    def _open_runtime_log(cls):
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "ollama_runtime.log"
        if log_file.exists() and log_file.stat().st_size > 5 * 1024 * 1024:
            backup = log_dir / "ollama_runtime.log.1"
            try:
                if backup.exists():
                    backup.unlink()
                log_file.rename(backup)
            except OSError:
                pass
        return open(log_file, "ab")

    @classmethod
    def _spawn_serve(cls, binary: str) -> bool:
        cls._register_cleanup()
        log_handle = cls._open_runtime_log()
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": log_handle,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            )
        else:
            kwargs["start_new_session"] = True
        try:
            cls._proc = subprocess.Popen([binary, "serve"], **kwargs)
            cls._spawned_by_cookmate = True
            logger.info("[OLLAMA LIFECYCLE] Spawned background ollama serve (pid=%s)", cls._proc.pid)
            return True
        except Exception as exc:
            cls._last_error = f"SPAWN_FAILED:{type(exc).__name__}"
            logger.warning("[OLLAMA LIFECYCLE] Failed to spawn ollama serve (%s)", type(exc).__name__)
            return False
        finally:
            try:
                log_handle.close()
            except Exception:
                pass

    @classmethod
    def _start_warmup_thread(cls) -> None:
        if cls._warmed_up or cls._warmup_started:
            return
        cls._warmup_started = True

        def _runner() -> None:
            payload = {
                "model": Config.OLLAMA_MODEL,
                "messages": [{"role": "user", "content": "OK"}],
                "think": False,
                "stream": False,
                "keep_alive": Config.OLLAMA_KEEP_ALIVE,
                "options": {"num_predict": 1, "temperature": 0.0},
            }
            try:
                _request_json("/api/chat", payload)
                cls._warmed_up = True
                logger.info("[OLLAMA WARMUP] Model %s pre-warmed (keep_alive=%s).", Config.OLLAMA_MODEL, Config.OLLAMA_KEEP_ALIVE)
            except Exception as exc:
                cls._last_error = f"WARMUP_SKIPPED:{type(exc).__name__}"
                logger.warning("[OLLAMA WARMUP] Non-fatal warmup skip (%s)", type(exc).__name__)

        thread = threading.Thread(target=_runner, name="cookmate-ollama-warmup", daemon=True)
        thread.start()

    @classmethod
    def _start_pull_thread(cls, binary: str, model: str) -> None:
        def _pull() -> None:
            logger.info("[OLLAMA LIFECYCLE] Pulling missing model %s in background...", model)
            try:
                log_handle = cls._open_runtime_log()
                kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": log_handle, "stderr": log_handle}
                if sys.platform == "win32":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                subprocess.run([binary, "pull", model], timeout=600, check=False, **kwargs)
                _server_profile.cache_clear()
            except Exception as exc:
                logger.warning("[OLLAMA LIFECYCLE] Background model pull failed (%s)", type(exc).__name__)
            finally:
                try:
                    log_handle.close()
                except Exception:
                    pass

        threading.Thread(target=_pull, name="cookmate-ollama-pull", daemon=True).start()

    @classmethod
    def ensure_started(cls, *, background_warm: bool = True, max_wait_seconds: float = 20.0) -> dict[str, Any]:
        """Ensure Ollama server is running, model is verified, and warm-up begins in background."""
        cls._last_error = ""
        binary = cls.find_ollama_binary()
        with cls._lock:
            already_alive, available = cls.list_local_models(timeout=2.5)
            if not already_alive:
                if not Config.OLLAMA_AUTO_START:
                    cls._last_error = "AUTO_START_DISABLED"
                    return cls.get_runtime_status(available=available, binary=binary)
                if not binary:
                    cls._last_error = "OLLAMA_BINARY_NOT_FOUND"
                    logger.warning("[OLLAMA LIFECYCLE] Ollama binary not found; Flask will rely on Gemini fallback when needed.")
                    return cls.get_runtime_status(available=available, binary=binary)
                if not cls._spawn_serve(binary):
                    return cls.get_runtime_status(available=available, binary=binary)
                deadline = time.monotonic() + max_wait_seconds
                while time.monotonic() < deadline:
                    alive, available = cls.list_local_models(timeout=2.0)
                    if alive:
                        _server_profile.cache_clear()
                        break
                    time.sleep(0.5)
                else:
                    cls._last_error = "STARTUP_TIMEOUT"
                    logger.warning("[OLLAMA LIFECYCLE] Timed out waiting %.1fs for %s", max_wait_seconds, Config.OLLAMA_BASE_URL)
                    return cls.get_runtime_status(available=available, binary=binary)

        model_ready, available = cls.has_model(Config.OLLAMA_MODEL, timeout=2.5)
        if not model_ready:
            if Config.OLLAMA_AUTO_PULL and binary:
                cls._start_pull_thread(binary, Config.OLLAMA_MODEL)
            else:
                cls._last_error = "MODEL_NOT_PULLED"
                logger.warning(
                    "[OLLAMA LIFECYCLE] Model %s not found locally (available=%s). Run 'ollama pull %s'.",
                    Config.OLLAMA_MODEL,
                    ",".join(available) or "none",
                    Config.OLLAMA_MODEL,
                )
        elif background_warm:
            cls._start_warmup_thread()

        return cls.get_runtime_status(available=available, binary=binary)

    @classmethod
    def get_runtime_status(cls, *, available: list[str] | None = None, binary: str | None = None) -> dict[str, Any]:
        alive = False
        models = available
        if models is None:
            alive, models = cls.list_local_models(timeout=1.5)
        else:
            alive = cls.is_alive(timeout=1.5)
        target_norm = _normalize_model_tag(Config.OLLAMA_MODEL)
        model_ready = alive and any(
            item.strip().lower() == Config.OLLAMA_MODEL.lower() or _normalize_model_tag(item) == target_norm
            for item in (models or [])
        )
        return {
            "running": alive,
            "base_url": Config.OLLAMA_BASE_URL,
            "model": Config.OLLAMA_MODEL,
            "model_ready": model_ready,
            "auto_start": Config.OLLAMA_AUTO_START,
            "spawned_by_cookmate": cls._spawned_by_cookmate,
            "binary_found": bool(binary if binary is not None else cls.find_ollama_binary()),
            "warmed_up": cls._warmed_up,
            "available_models": list(models or []),
            "error": cls._last_error or None,
        }
