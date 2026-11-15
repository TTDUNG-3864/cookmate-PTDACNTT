"""
CookMate Flask Compatibility Layer
==================================
Sử dụng thư viện Flask và Werkzeug chính thức nếu môi trường đã cài đặt.
Trong trường hợp chạy ở môi trường offline / chưa cài pip package bên ngoài,
module này cung cấp bộ tương thích chuẩn WSGI/HTTP với đầy đủ API của Flask:
- Flask, request, jsonify, session, send_from_directory, redirect, Response, abort
- generate_password_hash, check_password_hash (PBKDF2-HMAC-SHA256)
"""

import hashlib
import hmac
import http.cookies
import json
import mimetypes
import os
import re
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from flask import (
        Flask,
        Response,
        abort,
        jsonify,
        redirect,
        render_template,
        request,
        send_from_directory,
        session,
    )
    from werkzeug.security import check_password_hash, generate_password_hash

    USING_NATIVE_FLASK = True
except ImportError:
    USING_NATIVE_FLASK = False

    def generate_password_hash(password: str, method: str = "pbkdf2:sha256", salt_length: int = 16) -> str:
        salt = secrets.token_hex(salt_length // 2)
        iterations = 260000
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return f"pbkdf2:sha256:{iterations}${salt}${dk.hex()}"

    def check_password_hash(pwhash: str, password: str) -> bool:
        if not pwhash or not password:
            return False
        try:
            header, salt, stored_hex = pwhash.split("$", 2)
            parts = header.split(":")
            iterations = int(parts[2]) if len(parts) > 2 else 260000
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
            return hmac.compare_digest(dk.hex(), stored_hex)
        except Exception:
            return False

    class HTTPException(Exception):
        def __init__(self, code: int, description: str = ""):
            super().__init__(description)
            self.code = code
            self.description = description

    def abort(code: int, description: str = ""):
        raise HTTPException(code, description)

    class Response:
        def __init__(self, response=b"", status: int = 200, headers=None, mimetype: str = "text/html; charset=utf-8"):
            if isinstance(response, str):
                self.data = response.encode("utf-8")
            elif isinstance(response, (bytes, bytearray)):
                self.data = bytes(response)
            else:
                self.data = str(response).encode("utf-8")
            self.status_code = int(status)
            self.headers = dict(headers or {})
            if mimetype and "Content-Type" not in self.headers:
                self.headers["Content-Type"] = mimetype

    class _RequestContext(threading.local):
        def __init__(self):
            self.method = "GET"
            self.path = "/"
            self.args = {}
            self.headers = {}
            self.cookies = {}
            self.data = b""
            self._json = None
            self.form = {}

        def get_json(self, silent: bool = True, force: bool = False):
            if self._json is not None:
                return self._json
            if not self.data:
                return None
            try:
                self._json = json.loads(self.data.decode("utf-8"))
                return self._json
            except Exception:
                if silent:
                    return None
                raise

        @property
        def json(self):
            return self.get_json(silent=True)

    request = _RequestContext()

    class _SessionStore(threading.local):
        def __init__(self):
            self.data = {}
            self.modified = False

        def get(self, key, default=None):
            return self.data.get(key, default)

        def __getitem__(self, key):
            return self.data[key]

        def __setitem__(self, key, value):
            self.data[key] = value
            self.modified = True

        def __delitem__(self, key):
            if key in self.data:
                del self.data[key]
                self.modified = True

        def __contains__(self, key):
            return key in self.data

        def pop(self, key, default=None):
            self.modified = True
            return self.data.pop(key, default)

        def clear(self):
            self.data.clear()
            self.modified = True

    session = _SessionStore()

    def jsonify(*args, **kwargs) -> Response:
        if args and kwargs:
            raise TypeError("jsonify() behavior undefined when passed both args and kwargs")
        if len(args) == 1:
            payload = args[0]
        elif args:
            payload = list(args)
        else:
            payload = kwargs
        body = json.dumps(payload, ensure_ascii=False)
        return Response(body, status=200, mimetype="application/json; charset=utf-8")

    def redirect(location: str, code: int = 302) -> Response:
        return Response("", status=code, headers={"Location": location}, mimetype="text/plain")

    def send_from_directory(directory: str, path: str, **kwargs) -> Response:
        base_dir = os.path.abspath(directory)
        safe_rel = os.path.normpath(path).lstrip("\\/")
        full_path = os.path.abspath(os.path.join(base_dir, safe_rel))
        if not full_path.startswith(base_dir) or not os.path.isfile(full_path):
            abort(404, "File not found")
        mime_type, _ = mimetypes.guess_type(full_path)
        if not mime_type:
            if full_path.endswith(".svg"):
                mime_type = "image/svg+xml"
            elif full_path.endswith(".js"):
                mime_type = "application/javascript; charset=utf-8"
            elif full_path.endswith(".css"):
                mime_type = "text/css; charset=utf-8"
            elif full_path.endswith(".html"):
                mime_type = "text/html; charset=utf-8"
            else:
                mime_type = "application/octet-stream"
        elif mime_type.startswith("text/") or mime_type in ("application/javascript", "application/json"):
            mime_type = f"{mime_type}; charset=utf-8"
        with open(full_path, "rb") as f:
            content = f.read()
        return Response(content, status=200, mimetype=mime_type)

    def render_template(template_name: str, **context) -> Response:
        tpl_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
        if os.path.isfile(os.path.join(tpl_dir, template_name)):
            return send_from_directory(tpl_dir, template_name)
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return send_from_directory(root_dir, template_name)

    class _TestClientResponse:
        def __init__(self, resp: Response, cookies: dict):
            self.status_code = resp.status_code
            self.headers = resp.headers
            self.data = resp.data
            self.cookies = cookies

        @property
        def text(self) -> str:
            return self.data.decode("utf-8", errors="replace")

        def get_data(self, as_text: bool = False):
            if as_text:
                return self.text
            return self.data

        def get_json(self):
            try:
                return json.loads(self.text)
            except Exception:
                return None

    class _TestClient:
        def __init__(self, app: "Flask"):
            self.app = app
            self.cookies = {}

        def open(self, path: str, method: str = "GET", json_data=None, data=None, headers=None):
            req_headers = dict(headers or {})
            body_bytes = b""
            if json_data is not None:
                body_bytes = json.dumps(json_data, ensure_ascii=False).encode("utf-8")
                req_headers["Content-Type"] = "application/json"
            elif isinstance(data, str):
                body_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                body_bytes = data

            resp, updated_cookies = self.app._dispatch_internal(
                method=method.upper(),
                full_path=path,
                headers=req_headers,
                body=body_bytes,
                cookies=dict(self.cookies),
            )
            self.cookies.update(updated_cookies)
            return _TestClientResponse(resp, self.cookies)

        def get(self, path: str, **kwargs):
            return self.open(path, method="GET", **kwargs)

        def post(self, path: str, json=None, **kwargs):
            return self.open(path, method="POST", json_data=json, **kwargs)

        def put(self, path: str, json=None, **kwargs):
            return self.open(path, method="PUT", json_data=json, **kwargs)

        def delete(self, path: str, json=None, **kwargs):
            return self.open(path, method="DELETE", json_data=json, **kwargs)

    class Flask:
        def __init__(
            self,
            import_name: str,
            static_folder: str = "assets",
            static_url_path: str = "/assets",
            template_folder: str = "templates",
            **kwargs,
        ):
            self.import_name = import_name
            self.static_folder = static_folder
            self.static_url_path = static_url_path
            self.template_folder = template_folder
            self.config = {"SECRET_KEY": "cookmate-secret-key-2026"}
            self.secret_key = "cookmate-secret-key-2026"
            self._routes = []
            self._sessions = {}

        def route(self, rule: str, methods=None):
            if methods is None:
                methods = ["GET"]
            methods = [m.upper() for m in methods]
            regex, converters = self._compile_rule(rule)

            def decorator(func):
                self._routes.append((regex, converters, methods, func))
                return func

            return decorator

        @staticmethod
        def _compile_rule(rule: str):
            converters = {}
            pattern = "^"
            pos = 0
            for m in re.finditer(r"<(?:(int|path|string):)?([a-zA-Z_][a-zA-Z0-9_]*)>", rule):
                pattern += re.escape(rule[pos : m.start()])
                conv_type = m.group(1) or "string"
                var_name = m.group(2)
                converters[var_name] = conv_type
                if conv_type == "int":
                    pattern += f"(?P<{var_name}>\\d+)"
                elif conv_type == "path":
                    pattern += f"(?P<{var_name}>.+)"
                else:
                    pattern += f"(?P<{var_name}>[^/]+)"
                pos = m.end()
            pattern += re.escape(rule[pos:]) + "$"
            return re.compile(pattern), converters

        def test_client(self):
            return _TestClient(self)

        def _dispatch_internal(self, method: str, full_path: str, headers: dict, body: bytes, cookies: dict):
            parsed = urllib.parse.urlsplit(full_path)
            path = urllib.parse.unquote(parsed.path) or "/"
            raw_qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            args = {k: v[0] if len(v) == 1 else v for k, v in raw_qs.items()}

            request.method = method
            request.path = path
            request.args = args
            request.headers = headers
            request.cookies = cookies
            request.data = body
            request._json = None

            sid = cookies.get("cookmate_sid")
            if sid and sid in self._sessions:
                session.data = dict(self._sessions[sid])
            else:
                session.data = {}
            session.modified = False

            updated_cookies = {}
            try:
                resp = self._match_and_call(method, path)
            except HTTPException as exc:
                resp = jsonify({"error": exc.description or f"HTTP {exc.code}"}), exc.code
            except Exception as exc:
                resp = jsonify({"error": str(exc)}), 500

            if isinstance(resp, tuple):
                if len(resp) == 2:
                    raw_body, status_code = resp
                    extra_headers = {}
                else:
                    raw_body, status_code, extra_headers = resp
                if isinstance(raw_body, Response):
                    raw_body.status_code = status_code
                    raw_body.headers.update(extra_headers)
                    final_resp = raw_body
                elif isinstance(raw_body, (dict, list)):
                    final_resp = jsonify(raw_body)
                    final_resp.status_code = status_code
                    final_resp.headers.update(extra_headers)
                else:
                    final_resp = Response(raw_body, status=status_code, headers=extra_headers)
            elif isinstance(resp, Response):
                final_resp = resp
            elif isinstance(resp, (dict, list)):
                final_resp = jsonify(resp)
            else:
                final_resp = Response(resp)

            if session.modified:
                if not sid:
                    sid = secrets.token_hex(16)
                self._sessions[sid] = dict(session.data)
                updated_cookies["cookmate_sid"] = sid
                final_resp.headers["Set-Cookie"] = f"cookmate_sid={sid}; Path=/; HttpOnly; SameSite=Lax"

            return final_resp, updated_cookies

        def _match_and_call(self, method: str, path: str):
            allowed_methods = set()
            for regex, converters, methods, func in self._routes:
                m = regex.match(path)
                if m:
                    if method not in methods and not (method == "HEAD" and "GET" in methods):
                        allowed_methods.update(methods)
                        continue
                    kwargs = {}
                    for k, val in m.groupdict().items():
                        if converters.get(k) == "int":
                            kwargs[k] = int(val)
                        else:
                            kwargs[k] = val
                    return func(**kwargs)
            if allowed_methods:
                abort(405, "Method Not Allowed")
            abort(404, "Not Found")

        def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False, **kwargs):
            app_ref = self

            class _Handler(BaseHTTPRequestHandler):
                def _handle(self):
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    body = self.rfile.read(length) if length > 0 else b""
                    cookie_dict = {}
                    raw_cookie = self.headers.get("Cookie")
                    if raw_cookie:
                        c = http.cookies.SimpleCookie()
                        try:
                            c.load(raw_cookie)
                            for k, morsel in c.items():
                                cookie_dict[k] = morsel.value
                        except Exception:
                            pass

                    resp, _ = app_ref._dispatch_internal(
                        method=self.command,
                        full_path=self.path,
                        headers=dict(self.headers),
                        body=body,
                        cookies=cookie_dict,
                    )
                    self.send_response(resp.status_code)
                    for hk, hv in resp.headers.items():
                        self.send_header(hk, hv)
                    self.send_header("Content-Length", str(len(resp.data)))
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(resp.data)

                def do_GET(self):
                    self._handle()

                def do_POST(self):
                    self._handle()

                def do_PUT(self):
                    self._handle()

                def do_DELETE(self):
                    self._handle()

                def do_HEAD(self):
                    self._handle()

                def log_message(self, fmt, *args):
                    if debug:
                        super().log_message(fmt, *args)

            server = ThreadingHTTPServer((host, port), _Handler)
            print(f" * Running CookMate Flask Server on http://{host}:{port} (Press CTRL+C to quit)")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
