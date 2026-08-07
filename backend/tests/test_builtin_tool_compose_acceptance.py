from __future__ import annotations

import pytest

from app.acceptance.builtin_tool_composition import SCENARIOS, main


def test_builtin_tool_compose_acceptance_matrix_and_runner(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert {scenario.leaf for scenario in SCENARIOS} == {
        "environment",
        "base",
        "workshop",
    }
    assert {scenario.placements for scenario in SCENARIOS} == {
        (None,),
        ("cloud",),
        ("edge",),
        ("cloud", "edge"),
    }

    assert main() == 0
    output = capsys.readouterr().out
    assert "builtin-tool-composition: passed scenarios=4" in output
