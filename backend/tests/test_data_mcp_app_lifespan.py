from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from services.mcp_common.lifespan import install_sync_lifespan_hooks


class _RecordingReconciler:
    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self) -> None:
        self.events.append("start")

    def close(self) -> None:
        self.events.append("close")


def test_generation_reconciler_uses_starlette_lifespan() -> None:
    app = Starlette()
    reconciler = _RecordingReconciler()
    install_sync_lifespan_hooks(
        app,
        start=reconciler.start,
        close=reconciler.close,
    )

    with TestClient(app):
        assert reconciler.events == ["start"]

    assert reconciler.events == ["start", "close"]
