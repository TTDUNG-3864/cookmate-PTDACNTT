"""Shared pytest fixtures for the CookMate opaque-box E2E test suite."""

from __future__ import annotations

from collections.abc import Callable, Generator

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from helpers.browser_helper import launch_browser
from helpers.db_helper import DbHelper
from helpers.http_client import ApiClient
from helpers.server_harness import CookMateServerHarness


@pytest.fixture(scope="module")
def live_server() -> Generator[CookMateServerHarness, None, None]:
    """Module-scoped Flask server running in APP_ENV=testing with DEMO_MODE=true and raised IP cap."""
    DbHelper().clear_rate_limits()
    harness = CookMateServerHarness(
        env_overrides={
            "APP_ENV": "testing",
            "DEMO_MODE": "true",
            "OTP_IP_RATE_LIMIT_MAX": "500",
            "GEMINI_TIMEOUT": "2",
            "GEMINI_MAX_RETRIES": "0",
            "OLLAMA_TIMEOUT": "2",
        }
    ).start()
    try:
        yield harness
    finally:
        harness.stop()


@pytest.fixture
def server_factory() -> Generator[Callable[[dict[str, str] | None], CookMateServerHarness], None, None]:
    """Creates isolated subprocess Flask servers (e.g., APP_ENV=testing or production) and cleans them up."""
    started: list[CookMateServerHarness] = []

    def _start(env_overrides: dict[str, str] | None = None) -> CookMateServerHarness:
        harness = CookMateServerHarness(env_overrides=env_overrides).start()
        started.append(harness)
        return harness

    try:
        yield _start
    finally:
        for harness in reversed(started):
            harness.stop()


@pytest.fixture
def db() -> Generator[DbHelper, None, None]:
    """Function-scoped direct MySQL helper that resets rate limits and deletes created e2e_* users."""
    helper = DbHelper()
    helper.clear_rate_limits()
    try:
        yield helper
    finally:
        helper.cleanup()


@pytest.fixture
def api_client(live_server: CookMateServerHarness) -> ApiClient:
    """Fresh HTTP client pinned to live_server with isolated cookie jar."""
    return ApiClient(live_server.base_url)


@pytest.fixture(scope="session")
def browser() -> Generator[Browser, None, None]:
    """Session-scoped headless Chrome/Edge browser via Playwright."""
    pw = sync_playwright().start()
    br = launch_browser(pw)
    try:
        yield br
    finally:
        try:
            br.close()
        finally:
            pw.stop()


@pytest.fixture
def context(browser: Browser) -> Generator[BrowserContext, None, None]:
    """Fresh isolated Playwright BrowserContext per test."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        yield ctx
    finally:
        ctx.close()


@pytest.fixture
def page(context: BrowserContext) -> Generator[Page, None, None]:
    """Fresh Playwright Page per test."""
    pg = context.new_page()
    try:
        yield pg
    finally:
        pg.close()
