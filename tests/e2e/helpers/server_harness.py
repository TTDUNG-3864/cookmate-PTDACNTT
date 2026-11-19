"""Subprocess Flask server harness with live stdout/stderr capture and OTP banner parsing."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[3]

OTP_BANNER_RE = re.compile(
    r"^={10,}[ \t]*\r?\n"
    r"^\[COOKMATE DEMO MODE\] Password Reset OTP[ \t]*\r?\n"
    r"^Email:[ \t]*(?P<email>[^\r\n\t ]+(?:[ \t]+[^\r\n\t ]+)*)[ \t]*\r?\n"
    r"^OTP:[ \t]*(?P<otp>\d{6})[ \t]*\r?\n"
    r"^Expires in:[ \t]*(?P<expires>[^\r\n\t ]+(?:[ \t]+[^\r\n\t ]+)*)[ \t]*\r?\n"
    r"^={10,}[ \t]*$",
    re.MULTILINE,
)


def allocate_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


class CookMateServerHarness:
    """Manages an isolated Flask subprocess launched via main.py."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        env_overrides: dict[str, str] | None = None,
        startup_timeout: float = 20.0,
    ) -> None:
        self.host = host
        self.port = port or allocate_free_port(host)
        self.base_url = f"http://{self.host}:{self.port}"
        self.env_overrides = dict(env_overrides or {})
        self.startup_timeout = startup_timeout
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._lines: list[tuple[str, str]] = []
        self._threads: list[threading.Thread] = []

    def _drain_stream(self, stream, stream_name: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                with self._lock:
                    self._lines.append((stream_name, line))
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def start(self) -> "CookMateServerHarness":
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["OLLAMA_AUTO_START"] = "false"
        env.update(self.env_overrides)

        cmd = [
            sys.executable,
            "-u",
            str(PROJECT_ROOT / "main.py"),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--no-ollama-warm",
        ]

        self.process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert self.process.stdout is not None
        assert self.process.stderr is not None

        for stream, name in ((self.process.stdout, "stdout"), (self.process.stderr, "stderr")):
            t = threading.Thread(target=self._drain_stream, args=(stream, name), daemon=True)
            t.start()
            self._threads.append(t)

        self.wait_for_ready(timeout=self.startup_timeout)
        return self

    def wait_for_ready(self, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: str | None = None
        health_url = f"{self.base_url}/api/health"

        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"CookMate server exited early with code {self.process.returncode}.\n"
                    f"Captured output:\n{self.text_since(0)}"
                )
            try:
                resp = requests.get(health_url, timeout=1.5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok":
                        return
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.2)

        raise TimeoutError(
            f"CookMate server at {self.base_url} did not become healthy within {timeout}s. "
            f"Last error: {last_error}\nCaptured output:\n{self.text_since(0)}"
        )

    def output_mark(self) -> int:
        with self._lock:
            return len(self._lines)

    def lines_since(self, mark: int = 0, stream: str | None = None) -> list[str]:
        with self._lock:
            sliced = self._lines[mark:]
        if stream is None:
            return [line for _, line in sliced]
        return [line for s, line in sliced if s == stream]

    def text_since(self, mark: int = 0, stream: str | None = None) -> str:
        return "".join(self.lines_since(mark=mark, stream=stream))

    def find_otp_banners(
        self, email: str | None = None, since_mark: int = 0, stream: str | None = "stdout"
    ) -> list[dict[str, str]]:
        text = self.text_since(mark=since_mark, stream=stream)
        matches: list[dict[str, str]] = []
        target = email.strip().lower() if email else None
        for m in OTP_BANNER_RE.finditer(text):
            found_email = m.group("email").strip()
            if target is None or found_email.lower() == target:
                matches.append(
                    {
                        "email": found_email,
                        "otp": m.group("otp"),
                        "expires": m.group("expires").strip(),
                        "raw": m.group(0),
                    }
                )
        return matches

    def wait_for_otp_banner(
        self,
        email: str,
        *,
        since_mark: int = 0,
        timeout: float = 5.0,
        stream: str | None = "stdout",
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            banners = self.find_otp_banners(email=email, since_mark=since_mark, stream=stream)
            if banners:
                return banners[-1]
            time.sleep(0.1)
        raise TimeoutError(
            f"Timed out waiting {timeout}s for terminal OTP banner for '{email}'.\n"
            f"Captured output since mark {since_mark}:\n{self.text_since(since_mark)}"
        )

    def wait_for_otp(
        self, email: str, *, since_mark: int = 0, timeout: float = 5.0, stream: str | None = "stdout"
    ) -> str:
        return self.wait_for_otp_banner(email=email, since_mark=since_mark, timeout=timeout, stream=stream)["otp"]

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)
        for t in self._threads:
            t.join(timeout=1.0)
        self._threads.clear()
