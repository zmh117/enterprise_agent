from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = ROOT / "frontend" / "src"


def _production_frontend_sources() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in FRONTEND_SRC.rglob("*")
        if path.is_file()
        and path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
    }


def test_retired_api_platform_does_not_return_to_production_frontend() -> None:
    forbidden_fragments = (
        "/api/admin/api-capabilities",
        "/api/admin/api-connections",
        "/platform/api-capabilities",
        "resource-mapping",
        "resource_mapping",
        "internal-api-platform",
        "internal_api_platform",
        "mocks/dashboard",
        "bak/frontend",
    )
    violations: list[str] = []
    for path, source in _production_frontend_sources().items():
        for fragment in forbidden_fragments:
            if fragment.lower() in source.lower():
                violations.append(f"{path.relative_to(ROOT)}: {fragment}")
    assert violations == []


def test_router_has_no_retired_governance_route_or_catch_all_platform_route() -> None:
    router = (FRONTEND_SRC / "app/router/app-router.tsx").read_text(encoding="utf-8")
    assert not re.search(r'path:\s*["\']/platform/(api-capabilities|api-connections)', router)
    assert not re.search(r'path:\s*["\']/platform/\*', router)
    assert 'path: "/mcp/' in router


def test_vite_never_uses_backup_frontend_as_source_or_alias() -> None:
    vite = (ROOT / "frontend/vite.config.ts").read_text(encoding="utf-8")
    tsconfig = (ROOT / "frontend/tsconfig.app.json").read_text(encoding="utf-8")
    assert "bak/frontend" not in vite
    assert "bak/frontend" not in tsconfig

