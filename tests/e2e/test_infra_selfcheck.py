"""Pre-M1/M2 self-check suite verifying E2E dependencies, isolation, opaque-box AST, MySQL, Playwright, Flask, and tier counts."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from helpers.db_helper import DbHelper
from helpers.http_client import ApiClient
from helpers.server_harness import CookMateServerHarness

E2E_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = E2E_DIR.parents[1]
FORBIDDEN_ROOT_MODULES = {"app", "main", "backend"}


@pytest.mark.selfcheck
def test_selfcheck_python_dependencies() -> None:
    """Verify all required E2E packages are importable in the active pytest Python runtime."""
    required = ("pytest", "playwright.sync_api", "requests", "mysql.connector", "dotenv", "werkzeug.security")
    for mod_name in required:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import required module: {mod_name}"


@pytest.mark.selfcheck
def test_selfcheck_unittest_discovery_isolation() -> None:
    """Ensure tests/__init__.py and tests/e2e/__init__.py are absent and unittest discover ignores tests/e2e."""
    assert not (PROJECT_ROOT / "tests" / "__init__.py").exists(), "tests/__init__.py must NOT exist"
    assert not (E2E_DIR / "__init__.py").exists(), "tests/e2e/__init__.py must NOT exist"

    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0

    # Verify via Python unittest loader directly that tests/e2e is skipped during discovery.
    import unittest

    suite = unittest.defaultTestLoader.discover(start_dir=str(PROJECT_ROOT / "tests"), pattern="test_*.py")
    discovered_ids: list[str] = []

    def _walk(node) -> None:
        if isinstance(node, unittest.TestSuite):
            for child in node:
                _walk(child)
        else:
            discovered_ids.append(node.id())

    _walk(suite)
    assert len(discovered_ids) >= 80, f"Expected existing unittest suite (~91 tests), found {len(discovered_ids)}"
    leaked = [tid for tid in discovered_ids if "e2e" in tid.lower()]
    assert not leaked, f"unittest discover leaked E2E tests: {leaked}"


@pytest.mark.selfcheck
def test_selfcheck_opaque_box_no_internal_imports() -> None:
    """AST-verify that zero files under tests/e2e/ import app, main, or backend.*."""
    py_files = sorted(E2E_DIR.rglob("*.py"))
    assert len(py_files) >= 10

    violations: list[str] = []
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    if root_pkg in FORBIDDEN_ROOT_MODULES:
                        violations.append(f"{path.relative_to(E2E_DIR)}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_pkg = node.module.split(".")[0]
                    if root_pkg in FORBIDDEN_ROOT_MODULES:
                        violations.append(f"{path.relative_to(E2E_DIR)}:{node.lineno} from {node.module} import ...")

    assert not violations, "Opaque-box violation(s) found:\n" + "\n".join(violations)


@pytest.mark.selfcheck
def test_selfcheck_mysql_connection_and_user_seed_cleanup(db: DbHelper) -> None:
    """Verify direct MySQL connectivity, UTC clock check, and isolated test user seed + cleanup."""
    utc_now = db.get_utc_now()
    assert utc_now is not None

    created = db.create_test_user(prefix="e2e_selfcheck", password="SelfCheckPass123!")
    assert created["user_id"] > 0
    fetched = db.get_user_by_email(created["email"])
    assert fetched is not None
    assert fetched["email"] == created["email"]
    assert fetched["password_hash"] != "SelfCheckPass123!"

    db.cleanup()
    after_cleanup = db.get_user_by_email(created["email"])
    assert after_cleanup is None


@pytest.mark.selfcheck
@pytest.mark.browser
def test_selfcheck_playwright_chromium_launches(page) -> None:
    """Verify headless Chrome/Edge launches via Playwright and computes DOM geometry/styles."""
    page.set_content(
        "<html><body style='margin:0'><div id='box' style='width:120px;height:40px;z-index:10050;position:fixed'>OK</div></body></html>"
    )
    box = page.locator("#box").bounding_box()
    assert box is not None
    assert box["width"] == 120 and box["height"] == 40
    z_idx = page.locator("#box").evaluate("el => Number(getComputedStyle(el).zIndex)")
    assert z_idx == 10050


@pytest.mark.selfcheck
def test_selfcheck_flask_server_boots_and_captures_stdout(live_server: CookMateServerHarness) -> None:
    """Verify isolated Flask subprocess boots on ephemeral port, serves /api/health & /api/auth/csrf, and captures output."""
    client = ApiClient(live_server.base_url)
    health = client.get("/api/health")
    assert health.status_code == 200
    health_data = health.json()
    assert health_data.get("status") == "ok"
    assert health_data.get("database") == "mysql"

    token = client.ensure_csrf()
    assert len(token) >= 16

    captured = live_server.text_since(0)
    assert "CookMate" in captured or "127.0.0.1" in captured or len(captured) > 0


@pytest.mark.selfcheck
def test_selfcheck_tier_matrix_thresholds() -> None:
    """Verify Tier 1-4 and per-feature test counts meet SCOPE.md/PROJECT.md thresholds without empty stubs."""
    test_files = sorted(E2E_DIR.glob("test_*.py"))
    counts = {"selfcheck": 0, "tier1": 0, "tier2": 0, "tier3": 0, "tier4": 0}
    tier1_features = {f"f{i}": 0 for i in range(1, 11)}
    tier2_features = {f"f{i}": 0 for i in range(1, 11)}
    stub_tests: list[str] = []

    for path in test_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue

            # Reject empty/pass-only facade tests
            meaningful_stmts = [
                stmt
                for stmt in node.body
                if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str))
            ]
            if not meaningful_stmts or all(isinstance(stmt, ast.Pass) for stmt in meaningful_stmts):
                stub_tests.append(f"{path.name}::{node.name}")

            markers: set[str] = set()
            for dec in node.decorator_list:
                if isinstance(dec, ast.Attribute) and isinstance(dec.value, ast.Attribute):
                    markers.add(dec.attr)
                elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    markers.add(dec.func.attr)

            for tier_key in counts:
                if tier_key in markers:
                    counts[tier_key] += 1

            for f_key in tier1_features:
                if node.name.startswith(f"test_t1_{f_key}_"):
                    tier1_features[f_key] += 1
                if node.name.startswith(f"test_t2_{f_key}_"):
                    tier2_features[f_key] += 1

    assert not stub_tests, f"Facade/empty stub tests detected: {stub_tests}"
    assert counts["selfcheck"] >= 7, f"Expected >=7 selfcheck tests, got {counts['selfcheck']}"
    assert counts["tier1"] >= 50, f"Expected >=50 tier1 tests, got {counts['tier1']}"
    assert counts["tier2"] >= 50, f"Expected >=50 tier2 tests, got {counts['tier2']}"
    assert counts["tier3"] >= 10, f"Expected >=10 tier3 tests, got {counts['tier3']}"
    assert counts["tier4"] >= 5, f"Expected >=5 tier4 tests, got {counts['tier4']}"
    total_feature_tests = counts["tier1"] + counts["tier2"] + counts["tier3"] + counts["tier4"]
    assert total_feature_tests >= 115, f"Expected >=115 feature tests, got {total_feature_tests}"

    for f_key, cnt in tier1_features.items():
        assert cnt >= 5, f"Tier 1 coverage for {f_key} has {cnt} < 5 tests"
    for f_key, cnt in tier2_features.items():
        assert cnt >= 5, f"Tier 2 coverage for {f_key} has {cnt} < 5 tests"
