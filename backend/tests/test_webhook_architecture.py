from __future__ import annotations

from pathlib import Path


def test_webhook_module_does_not_bypass_agent_tool_or_delivery_boundaries() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "modules" / "webhook"
    source = "\n".join(path.read_text() for path in root.rglob("*.py"))

    forbidden = (
        "app.modules.agent.application.agent_executor",
        "app.modules.internal_tools",
        "app.modules.delivery.infrastructure",
    )
    assert all(name not in source for name in forbidden)
