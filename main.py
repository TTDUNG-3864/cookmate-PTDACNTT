# -*- coding: utf-8 -*-
"""Unified production entrypoint for CookMate (MySQL + Ollama lifecycle + Flask)."""

from __future__ import annotations

import argparse
import json
import sys

from app import app, bootstrap_runtime, run_server
from backend.config import Config
from backend.gemini_manager import discover_available_gemini_models, get_gemini_runtime_status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start CookMate web server and AI runtimes.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=Config.PORT, help=f"Port (default: {Config.PORT})")
    parser.add_argument("--debug", action="store_true", help="Run Flask in debug mode")
    parser.add_argument("--no-ollama-warm", action="store_true", help="Skip background Ollama model pre-warming")
    parser.add_argument("--check-only", action="store_true", help="Verify DB, schema, Ollama, and Gemini readiness then exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check_only:
        try:
            status = bootstrap_runtime(warm_ollama=not args.no_ollama_warm, run_schema_upgrade=True)
            if Config.GEMINI_API_KEY:
                discover_available_gemini_models()
                status["gemini"] = get_gemini_runtime_status()
            print(json.dumps({"status": "ok", **status}, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            errno = getattr(exc, "errno", None)
            print(
                json.dumps(
                    {"status": "error", "error": type(exc).__name__, "errno": errno},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1

    run_server(host=args.host, port=args.port, debug=args.debug, warm_ollama=not args.no_ollama_warm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
