"""Opaque-box HTTP client wrapping requests.Session with Origin & CSRF token management."""

from __future__ import annotations

from typing import Any

import requests


class ApiClient:
    """Stateful HTTP client that maintains session cookies, Origin, and X-CSRF-Token."""

    def __init__(self, base_url: str, *, allow_insecure_cookies: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.csrf_token: str = ""
        self.allow_insecure_cookies = allow_insecure_cookies

    def _sync_cookie_security(self) -> None:
        if self.allow_insecure_cookies:
            for cookie in self.session.cookies:
                cookie.secure = False

    def ensure_csrf(self) -> str:
        resp = self.session.get(f"{self.base_url}/api/auth/csrf", timeout=10.0)
        self._sync_cookie_security()
        resp.raise_for_status()
        data = resp.json()
        self.csrf_token = str(data.get("csrfToken") or "")
        return self.csrf_token

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        include_csrf: bool = True,
        csrf_override: str | None = None,
        origin_override: str | None = None,
        omit_origin: bool = False,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> requests.Response:
        if include_csrf and csrf_override is None and not self.csrf_token:
            self.ensure_csrf()

        headers: dict[str, str] = {}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if not omit_origin:
            headers["Origin"] = origin_override if origin_override is not None else self.base_url
        if csrf_override is not None:
            headers["X-CSRF-Token"] = csrf_override
        elif include_csrf and self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token

        if extra_headers:
            headers.update(extra_headers)

        self._sync_cookie_security()
        resp = self.session.request(
            method=method.upper(),
            url=f"{self.base_url}{path}",
            json=json_body,
            headers=headers,
            timeout=timeout,
        )
        self._sync_cookie_security()

        if method.upper() == "POST" and path.rstrip("/") == "/api/auth/logout" and resp.status_code < 400:
            self.csrf_token = ""
        else:
            try:
                payload = resp.json()
                if isinstance(payload, dict) and payload.get("csrfToken"):
                    self.csrf_token = str(payload["csrfToken"])
            except Exception:
                pass

        return resp

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, include_csrf=False, **kwargs)

    def post(self, path: str, json_body: Any = None, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, json_body=json_body, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", path, **kwargs)

    def login(self, email: str, password: str, **kwargs: Any) -> requests.Response:
        return self.post("/api/auth/login", {"email": email, "password": password}, **kwargs)

    def register(self, name: str, email: str, password: str, **kwargs: Any) -> requests.Response:
        return self.post("/api/auth/register", {"name": name, "email": email, "password": password}, **kwargs)

    def logout(self, **kwargs: Any) -> requests.Response:
        resp = self.post("/api/auth/logout", {}, **kwargs)
        if resp.status_code < 400:
            self.csrf_token = ""
        return resp

    def me(self) -> requests.Response:
        return self.get("/api/auth/me")

    def forgot_password(self, email: str, **kwargs: Any) -> requests.Response:
        return self.post("/api/auth/forgot-password", {"email": email}, **kwargs)

    def resend_otp(self, email: str, **kwargs: Any) -> requests.Response:
        return self.post("/api/auth/resend-otp", {"email": email}, **kwargs)

    def verify_otp(self, email: str, otp: str, **kwargs: Any) -> requests.Response:
        return self.post("/api/auth/verify-otp", {"email": email, "otp": otp}, **kwargs)

    def change_password(
        self,
        current_password: str,
        new_password: str,
        confirm_password: str,
        *,
        extra_payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        payload: dict[str, Any] = {
            "current_password": current_password,
            "new_password": new_password,
            "confirm_password": confirm_password,
        }
        if extra_payload:
            payload.update(extra_payload)
        return self.post("/api/auth/change-password", payload, **kwargs)
