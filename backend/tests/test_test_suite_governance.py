from __future__ import annotations

from pathlib import Path

import pytest

from backend.tests.suite_governance import (
    FAST_TEST_TIERS,
    TEST_TIERS,
    SuiteManifestError,
    discover_test_files,
    is_fast_test_tier,
    load_validated_test_tiers,
    validate_test_tier_assignments,
)


TEST_ROOT = Path(__file__).parent
MANIFEST_PATH = TEST_ROOT / "test_suite_tiers.toml"


def test_manifest_assigns_every_backend_test_to_exactly_one_tier() -> None:
    discovered = discover_test_files(TEST_ROOT)
    mapping = load_validated_test_tiers(TEST_ROOT, MANIFEST_PATH)

    assert set(mapping) == discovered
    assert set(mapping.values()) == set(TEST_TIERS)


def test_manifest_rejects_unclassified_duplicate_and_stale_paths() -> None:
    assignments = {tier: [] for tier in TEST_TIERS}
    assignments["unit"] = ["test_unit.py", "test_duplicate.py", "test_stale.py"]
    assignments["contract"] = ["test_duplicate.py"]

    with pytest.raises(SuiteManifestError) as exc_info:
        validate_test_tier_assignments(
            assignments,
            {"test_unit.py", "test_duplicate.py", "test_unclassified.py"},
        )

    message = str(exc_info.value)
    assert "test assigned to multiple tiers: test_duplicate.py" in message
    assert "unclassified tests: test_unclassified.py" in message
    assert "manifest references missing tests: test_stale.py" in message


def test_manifest_rejects_unknown_missing_and_unsafe_tiers() -> None:
    assignments = {
        "unit": ["../test_escape.py"],
        "contract": [],
        "integration": [],
        "acceptance": [],
        "unknown": [],
    }

    with pytest.raises(SuiteManifestError) as exc_info:
        validate_test_tier_assignments(assignments, set())

    message = str(exc_info.value)
    assert "unknown tiers: unknown" in message
    assert "missing tiers: migration" in message
    assert "unsafe test path in unit: ../test_escape.py" in message


def test_fast_tiers_are_exactly_unit_and_contract() -> None:
    assert FAST_TEST_TIERS == {"unit", "contract"}
    assert all(is_fast_test_tier(tier) for tier in FAST_TEST_TIERS)
    assert not any(is_fast_test_tier(tier) for tier in {"integration", "acceptance", "migration"})


def test_fast_file_set_is_a_strict_subset_of_complete_manifest() -> None:
    mapping = load_validated_test_tiers(TEST_ROOT, MANIFEST_PATH)
    full_paths = set(mapping)
    fast_paths = {path for path, tier in mapping.items() if is_fast_test_tier(tier)}
    protected_paths = {
        path for path, tier in mapping.items() if tier in {"integration", "acceptance", "migration"}
    }

    assert fast_paths < full_paths
    assert protected_paths
    assert fast_paths.isdisjoint(protected_paths)
    assert fast_paths | protected_paths == full_paths


def test_collection_hook_injects_manifest_tier_marker(
    request: pytest.FixtureRequest,
) -> None:
    marker = request.node.get_closest_marker("unit")
    assert marker is not None


def test_all_tiers_are_registered_with_pytest(pytestconfig: pytest.Config) -> None:
    registered = {value.split(":", 1)[0].strip() for value in pytestconfig.getini("markers")}
    assert set(TEST_TIERS) <= registered
