from __future__ import annotations

import json

from app.cli import reconcile_builtin_tools
from app.modules.agent.infrastructure.claude_code_agent_client import (
    TOOL_DEFINITIONS,
)
from backend.tests.helpers import container


def test_reconcile_builtin_tools_cli_is_idempotent_and_does_not_publish(
    monkeypatch,
    capsys,
) -> None:
    runtime = container()
    monkeypatch.setattr(
        reconcile_builtin_tools,
        "load_settings",
        lambda: runtime.settings,
    )
    monkeypatch.setattr(
        reconcile_builtin_tools,
        "build_api_container",
        lambda _settings: runtime,
    )

    assert reconcile_builtin_tools.main(
        ["--actor-id", "local-user", "--correlation-id", "cli-test"]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "drifted": 0,
        "installed": len(TOOL_DEFINITIONS),
        "missing": 0,
        "publication_performed": False,
        "release_count": 0,
        "status": "reconciled",
        "verification_performed": False,
    }
