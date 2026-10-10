"""Executable dependency and documentation boundaries for Mabrid backend packages."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = {
    "bridge": BACKEND_ROOT / "packages" / "bridge" / "src" / "mabrid" / "bridge",
    "application": (BACKEND_ROOT / "packages" / "application" / "src" / "mabrid" / "application"),
    "server": BACKEND_ROOT / "apps" / "server" / "src" / "mabrid" / "server",
}
FORBIDDEN_IMPORTS = {
    "bridge": {
        "mabrid.application",
        "mabrid.server",
        "alembic",
        "fastapi",
        "sqlalchemy",
        "uvicorn",
        "yaml",
    },
    "application": {
        "mabrid.server",
        "alembic",
        "fastapi",
        "sqlalchemy",
        "uvicorn",
        "yaml",
    },
}


def test_product_identity_does_not_depend_on_checkout_directory_name() -> None:
    projects = {
        BACKEND_ROOT: "mabrid-workspace",
        BACKEND_ROOT / "packages" / "bridge": "mabrid-bridge",
        BACKEND_ROOT / "packages" / "application": "mabrid-application",
        BACKEND_ROOT / "apps" / "server": "mabrid-server",
    }
    for root, name in projects.items():
        metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        assert metadata["project"]["name"] == name
        assert "Mabrid" in metadata["project"]["description"]
        if name == "mabrid-server":
            assert metadata["project"]["scripts"] == {"mabrid": "mabrid.server.main:main"}
    for source_root in SOURCE_ROOTS.values():
        assert source_root.is_dir()
        for path in source_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for legacy_identity in (
                "mcpapps-bridge",
                "mcp_gateway_core",
                "mcp_gateway_service",
                "mcp_gateway_server",
                "cembrid",
            ):
                assert legacy_identity not in source, str(path.relative_to(BACKEND_ROOT))


def test_lower_packages_do_not_import_outer_layers() -> None:
    violations: list[str] = []
    for owner, forbidden in FORBIDDEN_IMPORTS.items():
        for path in SOURCE_ROOTS[owner].rglob("*.py"):
            for imported in _absolute_imports(path):
                if any(
                    imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden
                ):
                    relative_path = path.relative_to(BACKEND_ROOT)
                    violations.append(f"{relative_path}: {imported}")

    assert violations == []


def test_every_production_module_records_its_boundary() -> None:
    missing: list[str] = []
    for source_root in SOURCE_ROOTS.values():
        for path in source_root.rglob("*.py"):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if ast.get_docstring(module, clean=False) is None:
                missing.append(str(path.relative_to(BACKEND_ROOT)))

    assert missing == []


def _absolute_imports(path: Path) -> list[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            imports.append(node.module)
    return imports
