from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath


TEST_TIERS = ("unit", "contract", "integration", "acceptance", "migration")
FAST_TEST_TIERS = frozenset({"unit", "contract"})


class SuiteManifestError(ValueError):
    """Raised when the versioned test tier manifest is incomplete or ambiguous."""


def discover_test_files(test_root: Path) -> set[str]:
    return {
        path.relative_to(test_root).as_posix()
        for path in test_root.rglob("test_*.py")
        if path.is_file()
    }


def load_test_tier_assignments(manifest_path: Path) -> dict[str, tuple[str, ...]]:
    payload = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    tiers = payload.get("tiers")
    if not isinstance(tiers, dict):
        raise SuiteManifestError("test tier manifest must contain a [tiers] table")
    assignments: dict[str, tuple[str, ...]] = {}
    for tier, paths in tiers.items():
        if not isinstance(tier, str) or not isinstance(paths, list):
            raise SuiteManifestError("test tier entries must be string arrays")
        if not all(isinstance(path, str) for path in paths):
            raise SuiteManifestError(f"test tier {tier!r} contains a non-string path")
        assignments[tier] = tuple(paths)
    return assignments


def validate_test_tier_assignments(
    assignments: Mapping[str, Sequence[str]],
    discovered: set[str],
) -> dict[str, str]:
    errors: list[str] = []
    unknown_tiers = sorted(set(assignments) - set(TEST_TIERS))
    missing_tiers = sorted(set(TEST_TIERS) - set(assignments))
    if unknown_tiers:
        errors.append("unknown tiers: " + ", ".join(unknown_tiers))
    if missing_tiers:
        errors.append("missing tiers: " + ", ".join(missing_tiers))

    path_tiers: dict[str, list[str]] = {}
    for tier in TEST_TIERS:
        for raw_path in assignments.get(tier, ()):
            normalized = PurePosixPath(raw_path)
            if normalized.is_absolute() or ".." in normalized.parts:
                errors.append(f"unsafe test path in {tier}: {raw_path}")
                continue
            path = normalized.as_posix()
            if not normalized.name.startswith("test_") or normalized.suffix != ".py":
                errors.append(f"invalid test path in {tier}: {raw_path}")
                continue
            path_tiers.setdefault(path, []).append(tier)

    duplicates = {path: tiers for path, tiers in path_tiers.items() if len(tiers) != 1}
    for path, tiers in sorted(duplicates.items()):
        errors.append(f"test assigned to multiple tiers: {path} -> {', '.join(tiers)}")

    assigned = set(path_tiers)
    missing = sorted(discovered - assigned)
    stale = sorted(assigned - discovered)
    if missing:
        errors.append("unclassified tests: " + ", ".join(missing))
    if stale:
        errors.append("manifest references missing tests: " + ", ".join(stale))

    if errors:
        raise SuiteManifestError("; ".join(errors))
    return {path: tiers[0] for path, tiers in path_tiers.items()}


def load_validated_test_tiers(test_root: Path, manifest_path: Path) -> dict[str, str]:
    return validate_test_tier_assignments(
        load_test_tier_assignments(manifest_path),
        discover_test_files(test_root),
    )


def is_fast_test_tier(tier: str) -> bool:
    return tier in FAST_TEST_TIERS
