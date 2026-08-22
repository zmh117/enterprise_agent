from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIG = ROOT / "frontend" / "nginx.conf"


def test_admin_web_dynamically_resolves_replaced_api_server_container() -> None:
    config = NGINX_CONFIG.read_text(encoding="utf-8")

    assert "resolver 127.0.0.11 valid=10s ipv6=off;" in config
    assert "zone api_backend 64k;" in config
    assert "server api-server:8000 resolve;" in config
    assert "proxy_pass http://api_backend/api/;" in config
    assert "proxy_pass http://api-server:8000/api/;" not in config
