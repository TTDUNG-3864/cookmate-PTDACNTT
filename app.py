# -*- coding: utf-8 -*-
"""CookMate Flask application factory and existing static page serving."""

from __future__ import annotations

import logging
import hmac
import os
import threading
from typing import Any

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from backend.config import BASE_DIR, Config, apply_environment_defaults
from backend.database.connection import check_database, fetch_all
from backend.routes.api import api
from backend.security.authentication import current_user
from backend.security.rate_limit import OTPRateLimiter

CSRF_EXPLICIT_PATHS = frozenset({
    "/api/auth/forgot-password",
    "/api/auth/verify-otp",
    "/api/auth/resend-otp",
})

FORCE_PASSWORD_CHANGE_ALLOWED_PATHS = frozenset({
    "/api/auth/csrf",
    "/api/auth/me",
    "/api/auth/logout",
    "/api/auth/login",
    "/api/auth/force-change-password",
    "/api/auth/change-password",
    "/api/health",
})


def create_app(config_overrides: dict | None = None) -> Flask:
    app=Flask(
        __name__,static_folder=str(BASE_DIR / "assets"),static_url_path="/assets",
        template_folder=str(BASE_DIR / "templates"),
    )
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    apply_environment_defaults(app.config, config_overrides)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("COOKMATE_SECRET_KEY is required. Set it in the root .env file.")
    if bool(app.config.get("TRUST_PROXY_HEADERS", False)):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)
    app.extensions["otp_rate_limiter"] = OTPRateLimiter(
        secret_key=str(app.config["SECRET_KEY"]),
        use_db=True,
    )

    ai_logger=logging.getLogger("backend.gemini_manager")
    if not app.config.get("TESTING"):
        ai_logger.setLevel(logging.INFO)
        if not ai_logger.handlers:
            ai_handler=logging.StreamHandler()
            ai_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            ai_logger.addHandler(ai_handler)
        ai_logger.propagate=False

    app.register_blueprint(api)
    app.logger.setLevel(logging.INFO)

    @app.before_request
    def enforce_origin_and_csrf():
        origin=request.headers.get("Origin")
        if origin:
            normalized=origin.rstrip("/")
            allowed=set(app.config.get("CORS_ALLOWED_ORIGINS") or ())
            own_origin=f"{request.scheme}://{request.host}".rstrip("/")
            if normalized not in allowed and normalized != own_origin:
                return jsonify({"success":False,"error":"Origin is not allowed."}),403
        if request.method in {"POST","PUT","PATCH","DELETE"} and request.path.startswith("/api/"):
            if session.get("user_id") or request.path.rstrip("/") in CSRF_EXPLICIT_PATHS:
                supplied=request.headers.get("X-CSRF-Token","")
                expected=session.get("csrf_token","")
                if (
                    not isinstance(supplied,str)
                    or not isinstance(expected,str)
                    or not supplied
                    or not expected
                    or not hmac.compare_digest(supplied,expected)
                ):
                    return jsonify({"success":False,"error":"CSRF validation failed."}),403
        if request.path.startswith("/api/") and session.get("user_id"):
            normalized_path = request.path.rstrip("/")
            if normalized_path not in FORCE_PASSWORD_CHANGE_ALLOWED_PATHS:
                user = current_user()
                if user and user.get("must_change_password"):
                    return jsonify({
                        "success": False,
                        "must_change_password": True,
                        "error": "Bạn cần đổi mật khẩu tạm thời trước khi tiếp tục sử dụng hệ thống.",
                    }), 403

    @app.after_request
    def apply_cors(response):
        origin=request.headers.get("Origin")
        if origin:
            normalized=origin.rstrip("/")
            allowed=set(app.config.get("CORS_ALLOWED_ORIGINS") or ())
            own_origin=f"{request.scheme}://{request.host}".rstrip("/")
            if normalized in allowed or normalized == own_origin:
                response.headers["Access-Control-Allow-Origin"]=origin
                response.headers["Access-Control-Allow-Credentials"]="true"
                response.headers["Access-Control-Allow-Headers"]="Content-Type, X-CSRF-Token"
                response.headers["Access-Control-Allow-Methods"]="GET, POST, PUT, PATCH, DELETE, OPTIONS"
                response.headers["Vary"]="Origin"
        response.headers.setdefault("X-Content-Type-Options","nosniff")
        response.headers.setdefault("X-Frame-Options","SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy","strict-origin-when-cross-origin")
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        if isinstance(error,HTTPException):
            return error
        errno=getattr(error,"errno",None)
        app.logger.error("Request failed (%s%s)",type(error).__name__,f", errno={errno}" if errno else "")
        if request.path.startswith("/api/"):
            return jsonify({"success":False,"error":"Dịch vụ tạm thời không khả dụng. Vui lòng thử lại."}),503
        return "CookMate is temporarily unavailable.",503

    @app.get("/favicon.ico")
    def serve_favicon():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<rect width="64" height="64" rx="16" fill="#E85D2A"/>'
            '<text x="32" y="43" text-anchor="middle" font-family="sans-serif" font-weight="800" font-size="32" fill="#FFF9F2">C</text>'
            '</svg>'
        )
        return app.response_class(svg, mimetype="image/svg+xml")

    @app.get("/")
    @app.get("/index.html")
    def serve_index():
        return send_from_directory(BASE_DIR,"index.html")

    @app.get("/static/uploads/recipes/<path:filename>")
    def serve_recipe_uploads(filename: str):
        upload_dir = app.config.get("RECIPE_UPLOAD_DIR") or str(BASE_DIR / "static" / "uploads" / "recipes")
        return send_from_directory(upload_dir, filename)

    @app.get("/pages/<path:_prefix>/static/uploads/recipes/<path:filename>")
    def serve_nested_recipe_uploads(_prefix: str, filename: str):
        upload_dir = app.config.get("RECIPE_UPLOAD_DIR") or str(BASE_DIR / "static" / "uploads" / "recipes")
        return send_from_directory(upload_dir, filename)

    @app.get("/pages/<path:filename>")
    def serve_pages(filename: str):
        return send_from_directory(BASE_DIR / "pages",filename)

    @app.get("/static/<path:filename>")
    def static_alias(filename: str):
        static_candidate = (BASE_DIR / "static" / filename).resolve()
        if str(static_candidate).startswith(str((BASE_DIR / "static").resolve())) and static_candidate.is_file():
            return send_from_directory(BASE_DIR / "static", filename)
        return send_from_directory(BASE_DIR / "assets",filename)

    os.makedirs(str(app.config.get("RECIPE_UPLOAD_DIR") or (BASE_DIR / "static" / "uploads" / "recipes")), exist_ok=True)
    return app


app = create_app()

CORE_TABLES = (
    "users",
    "categories",
    "ingredients",
    "dishes",
    "dish_ingredients",
    "recipes",
    "recipe_ingredients",
    "recipe_steps",
    "favorites",
    "comments",
    "chat_sessions",
    "chat_messages",
)


def bootstrap_runtime(*, warm_ollama: bool = True, run_schema_upgrade: bool = True) -> dict[str, Any]:
    """Verify MySQL connectivity/core tables, upgrade schema if needed, and start Ollama."""
    from backend.database.schema_upgrade import ensure_runtime_schema
    from backend.gemini_manager import discover_available_gemini_models, get_gemini_runtime_status
    from backend.ollama_manager import OllamaServiceManager

    Config.validate()
    check_database()
    existing_rows = fetch_all(
        "SELECT TABLE_NAME AS name FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()"
    )
    existing_tables = {str(row.get("name") or "").lower() for row in existing_rows}
    missing_tables = [table for table in CORE_TABLES if table not in existing_tables]
    if missing_tables:
        app.logger.warning("Missing MySQL core tables: %s", ",".join(missing_tables))

    schema_result: dict[str, Any] = {"ok": True, "added_columns": []}
    if run_schema_upgrade:
        try:
            schema_result = ensure_runtime_schema()
        except Exception as exc:
            app.logger.warning("Runtime schema upgrade check skipped/failed (%s)", type(exc).__name__)
            schema_result = {"ok": False, "error": type(exc).__name__}

    ollama_status = OllamaServiceManager.ensure_started(background_warm=warm_ollama)

    if Config.GEMINI_API_KEY:
        def _prewarm_gemini_discovery() -> None:
            try:
                discover_available_gemini_models()
            except Exception:
                pass

        threading.Thread(
            target=_prewarm_gemini_discovery,
            name="cookmate-gemini-discovery",
            daemon=True,
        ).start()

    return {
        "mysql": {"ok": True, "missing_tables": missing_tables},
        "schema": schema_result,
        "ollama": ollama_status,
        "gemini": get_gemini_runtime_status(),
    }


def run_server(*, host: str = "0.0.0.0", port: int | None = None, debug: bool = False, warm_ollama: bool = True) -> None:
    """Start CookMate server with reloader-safe bootstrap."""
    target_port = int(port or Config.PORT)
    should_bootstrap = (not debug) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true")
    if should_bootstrap:
        try:
            status = bootstrap_runtime(warm_ollama=warm_ollama, run_schema_upgrade=True)
            app.logger.info(
                "CookMate runtime ready (mysql=ok, ollama_running=%s, model=%s, gemini_configured=%s)",
                status["ollama"].get("running"),
                status["ollama"].get("model"),
                status["gemini"].get("configured"),
            )
        except Exception as exc:
            errno = getattr(exc, "errno", None)
            app.logger.error("MySQL startup check failed (%s%s)", type(exc).__name__, f", errno={errno}" if errno else "")
            raise SystemExit(1) from None
    app.run(host=host, port=target_port, debug=debug)


if __name__ == "__main__":
    run_server(host="0.0.0.0", port=Config.PORT, debug=False)
