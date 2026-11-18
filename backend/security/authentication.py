"""Session-backed identity. Client supplied IDs and roles are ignored."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import g, jsonify, session

from backend.database.repositories import get_user_by_id


def current_user() -> dict[str, Any] | None:
    cached = getattr(g, "cookmate_user_loaded", False)
    if cached:
        return getattr(g, "cookmate_user", None)
    g.cookmate_user_loaded = True
    user_id = session.get("user_id")
    g.cookmate_user = get_user_by_id(int(user_id)) if user_id else None
    return g.cookmate_user


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"success": False, "error": "Vui lòng đăng nhập."}), 401
        if user.get("status") != "active":
            session.clear()
            return jsonify({"success": False, "error": "Tài khoản đã bị vô hiệu hóa."}), 403
        return view(*args, **kwargs)
    return wrapped


def admin_required(view: Callable) -> Callable:
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        user = current_user()
        if user.get("role") != "admin":
            return jsonify({"success": False, "error": "Bạn không có quyền thực hiện thao tác này."}), 403
        return view(*args, **kwargs)
    return wrapped

