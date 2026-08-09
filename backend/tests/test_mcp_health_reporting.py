from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

from app.modules.mcp_resources import api as mcp_api
from services.mcp_common.observability import generation_health_status_code


def test_exact_lkg_degraded_health_remains_serviceable() -> None:
    degraded_with_lkg = {
        "generation_status": "degraded",
        "active_deployment_count": 2,
        "active_generation_count": 2,
        "last_known_good_generation_count": 2,
    }
    degraded_without_lkg = {
        **degraded_with_lkg,
        "last_known_good_generation_count": 1,
    }

    assert generation_health_status_code(degraded_with_lkg) == 200
    assert generation_health_status_code(degraded_without_lkg) == 503


class _DegradedOpener:
    def open(self, request, timeout):
        del timeout
        payload = json.dumps(
            {
                "status": "degraded",
                "server_code": "data-mcp",
                "server_version": "0.1.0",
                "generation_status": "degraded",
                "active_generation_count": 1,
                "building_generation_count": 0,
                "failed_generation_count": 1,
                "unsafe_detail": "must-not-pass-through",
            }
        ).encode()
        raise HTTPError(request.full_url, 503, "degraded", {}, BytesIO(payload))


def test_control_plane_preserves_safe_degraded_health_payload(monkeypatch) -> None:
    monkeypatch.setattr(mcp_api, "build_opener", lambda *handlers: _DegradedOpener())

    assert mcp_api._health("http://data-mcp-server:9102/mcp") == {
        "status": "degraded",
        "server_code": "data-mcp",
        "server_version": "0.1.0",
        "generation_status": "degraded",
        "active_generation_count": 1,
        "building_generation_count": 0,
        "failed_generation_count": 1,
    }
