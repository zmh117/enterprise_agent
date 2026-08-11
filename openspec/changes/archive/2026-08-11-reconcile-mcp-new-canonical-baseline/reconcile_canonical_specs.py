#!/usr/bin/env python3
"""Reconcile the domain canonical baseline with mcp_new accepted spec changes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any


CHANGE_ROOT = Path(__file__).resolve().parent


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "openspec" / "config.yaml").is_file() and (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"cannot locate repository root from {start}")


REPO_ROOT = find_repo_root(CHANGE_ROOT)
OPEN_SPEC_ROOT = REPO_ROOT / "openspec"
CANONICAL_ROOT = OPEN_SPEC_ROOT / "specs"
ORIGINAL_ARCHIVE = (
    OPEN_SPEC_ROOT / "changes" / "archive" / "2026-08-11-rebuild-canonical-spec-baseline"
)
ORIGINAL_SNAPSHOT = ORIGINAL_ARCHIVE / "source-specs-snapshot"
TARGET_SNAPSHOT = CHANGE_ROOT / "target-source-specs-snapshot"
STAGING_ROOT = CHANGE_ROOT / "_canonical_staging"
SOURCE_MANIFEST = CHANGE_ROOT / "target-source-manifest.json"
FINAL_MANIFEST = CHANGE_ROOT / "reconciliation-manifest.json"
SOURCE_COMMIT = "fd00d3946de17b8dd97eae3dc8f7fa57fc5aa3f5"

DOMAIN_ORDER = (
    "identity-access",
    "agent-model",
    "business-application",
    "channel-conversation",
    "execution-delivery",
    "builtin-tool-resource",
    "governed-api-capability",
    "platform-operations",
)

COMPLETED_CHANGES = (
    "migrate-claude-agent-sdk-to-typescript",
    "retire-legacy-api-platform-for-mcp",
)

GOVERNANCE_TITLES = (
    "Canonical 主规格是唯一当前规范基线",
    "Codex 默认按领域读取 Canonical 主规格",
    "Archive 保持完整且不参与默认规范解析",
)

RESTORE_PATHS = (
    "business-application-publication/spec.md",
    "claude-agent-runtime-integration/spec.md",
    "multi-agent-configuration/spec.md",
    "rabbitmq-agent-job-execution/spec.md",
)

MODIFIED_TITLE_ALIASES = {
    (
        "migrate-claude-agent-sdk-to-typescript",
        "claude-agent-runtime-integration",
        "Read-only tools are exposed only through governed MCP servers",
    ): "Read-only tools are exposed only through an in-process SDK MCP server",
    (
        "retire-legacy-api-platform-for-mcp",
        "claude-agent-runtime-integration",
        "Read-only tools are exposed only through the deployment-fixed standard MCP server",
    ): "Read-only tools are exposed only through governed MCP servers",
}

REQUIREMENT_RE = re.compile(r"(?m)^### Requirement: (?P<title>.+)$")
SCENARIO_RE = re.compile(r"(?m)^#### Scenario: ")
SECTION_RE = re.compile(r"(?m)^## (?P<operation>ADDED|MODIFIED|REMOVED|RENAMED) Requirements\s*$")
SOURCE_COMMENT_RE = re.compile(r"(?m)^<!-- (?:Migrated|Reconciled) from [^\n]+ -->\n?")


def normalized_block(raw: str) -> str:
    return SOURCE_COMMENT_RE.sub("", raw).rstrip() + "\n"


def requirement_blocks(text: str, *, require_scenario: bool = True) -> list[dict[str, Any]]:
    matches = list(REQUIREMENT_RE.finditer(text))
    blocks: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block_text = normalized_block(text[match.start() : end])
        scenario_count = len(SCENARIO_RE.findall(block_text))
        if require_scenario and scenario_count == 0:
            raise ValueError(f"Requirement has no Scenario: {match.group('title').strip()}")
        blocks.append(
            {
                "title": match.group("title").strip(),
                "text": block_text,
                "sha256": hashlib.sha256(block_text.encode("utf-8")).hexdigest(),
                "scenario_count": scenario_count,
            }
        )
    return blocks


def purpose_from_spec(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^## Purpose\s*\n(?P<purpose>.+?)\n## Requirements\s*\n", text)
    if not match:
        raise ValueError(f"cannot parse Purpose: {path}")
    return match.group("purpose").strip()


def load_original_mapping() -> list[tuple[str, str]]:
    path = ORIGINAL_ARCHIVE / "migration-map.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    mapping = [(row["source_capability"], row["canonical_domain"]) for row in rows]
    if len(mapping) != 83 or len({source for source, _ in mapping}) != 83:
        raise ValueError("original 83 capability mapping is incomplete or duplicated")
    return mapping


def load_mapping_additions() -> list[tuple[str, str]]:
    path = CHANGE_ROOT / "mapping-additions.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return [(row["capability"], row["canonical_domain"]) for row in rows]


def all_mapping() -> list[tuple[str, str]]:
    mapping = load_original_mapping() + load_mapping_additions()
    if len(mapping) != len({source for source, _ in mapping}):
        raise ValueError("capability mapping contains duplicates")
    unknown_domains = sorted({domain for _, domain in mapping} - set(DOMAIN_ORDER))
    if unknown_domains:
        raise ValueError(f"unknown canonical domains: {unknown_domains}")
    return mapping


def block_entry(block: dict[str, Any], *, capability: str, domain: str) -> dict[str, Any]:
    return {
        "capability": capability,
        "canonical_domain": domain,
        "title": block["title"],
        "sha256": block["sha256"],
        "scenario_count": block["scenario_count"],
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def freeze_source() -> None:
    if TARGET_SNAPSHOT.exists():
        raise FileExistsError(f"refusing to overwrite target snapshot: {TARGET_SNAPSHOT}")
    shutil.copytree(ORIGINAL_SNAPSHOT, TARGET_SNAPSHOT)
    runtime_source = CANONICAL_ROOT / "agent-runtime-service-contract" / "spec.md"
    runtime_target = TARGET_SNAPSHOT / "agent-runtime-service-contract" / "spec.md"
    runtime_target.parent.mkdir(parents=True, exist_ok=False)
    shutil.copy2(runtime_source, runtime_target)

    source_mapping = load_original_mapping() + [
        ("agent-runtime-service-contract", "execution-delivery")
    ]
    actual_capabilities = sorted(path.name for path in TARGET_SNAPSHOT.iterdir() if path.is_dir())
    expected_capabilities = sorted(source for source, _ in source_mapping)
    if actual_capabilities != expected_capabilities:
        raise ValueError("target source snapshot does not contain exactly 84 mapped capabilities")

    entries: list[dict[str, Any]] = []
    for capability, domain in source_mapping:
        for block in requirement_blocks(
            (TARGET_SNAPSHOT / capability / "spec.md").read_text(encoding="utf-8")
        ):
            entries.append(block_entry(block, capability=capability, domain=domain))
    titles = [entry["title"] for entry in entries]
    if len(titles) != len(set(titles)):
        duplicates = sorted(title for title, count in Counter(titles).items() if count > 1)
        raise ValueError(f"duplicate source Requirement titles: {duplicates}")
    manifest = {
        "source_commit_parent": "851dbee7b6a814d59cc7ff3d7c71b7929164406f",
        "source_capability_count": len(source_mapping),
        "source_requirement_count": len(entries),
        "source_scenario_count": sum(int(entry["scenario_count"]) for entry in entries),
        "entries": entries,
    }
    write_json(SOURCE_MANIFEST, manifest)
    print(
        json.dumps(
            {key: value for key, value in manifest.items() if key != "entries"},
            ensure_ascii=False,
            indent=2,
        )
    )


def verify_source_snapshot() -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    domain_by_capability = dict(
        load_original_mapping() + [("agent-runtime-service-contract", "execution-delivery")]
    )
    expected = Counter(
        (
            entry["capability"],
            entry["canonical_domain"],
            entry["title"],
            entry["sha256"],
            entry["scenario_count"],
        )
        for entry in manifest["entries"]
    )
    actual: Counter[tuple[Any, ...]] = Counter()
    for capability, domain in domain_by_capability.items():
        for block in requirement_blocks(
            (TARGET_SNAPSHOT / capability / "spec.md").read_text(encoding="utf-8")
        ):
            actual[
                (capability, domain, block["title"], block["sha256"], block["scenario_count"])
            ] += 1
    if actual != expected:
        raise ValueError("target source snapshot differs from its frozen manifest")
    print(
        json.dumps(
            {"target_source_snapshot_verification": "passed", "requirements": sum(actual.values())},
            ensure_ascii=False,
        )
    )


def restore_original_archive() -> None:
    for relative in RESTORE_PATHS:
        repo_relative = f"openspec/changes/archive/2026-08-11-rebuild-canonical-spec-baseline/source-specs-snapshot/{relative}"
        content = (
            subprocess.run(
                ["git", "show", f"{SOURCE_COMMIT}:{repo_relative}"],
                cwd=REPO_ROOT,
                check=True,
                stdout=subprocess.PIPE,
            )
            .stdout.decode("utf-8")
            .rstrip()
            + "\n"
        )
        (REPO_ROOT / repo_relative).write_text(content, encoding="utf-8")
    verify_original_archive()


def verify_original_archive() -> None:
    manifest = json.loads((ORIGINAL_ARCHIVE / "source-manifest.json").read_text(encoding="utf-8"))
    expected = Counter(
        (
            entry["source_capability"],
            entry["canonical_domain"],
            entry["title"],
            entry["sha256"],
            entry["scenario_count"],
        )
        for entry in manifest["entries"]
    )
    actual: Counter[tuple[Any, ...]] = Counter()
    for capability, domain in load_original_mapping():
        path = ORIGINAL_SNAPSHOT / capability / "spec.md"
        for block in requirement_blocks(path.read_text(encoding="utf-8")):
            actual[
                (capability, domain, block["title"], block["sha256"], block["scenario_count"])
            ] += 1
    if actual != expected:
        raise ValueError(
            "original canonical archive snapshot still differs from its frozen manifest"
        )
    print(
        json.dumps(
            {
                "original_archive_snapshot_verification": "passed",
                "requirements": sum(actual.values()),
            },
            ensure_ascii=False,
        )
    )


def parse_delta(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    sections = list(SECTION_RE.finditer(text))
    operations: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        operation = section.group("operation")
        body = text[section.end() : end]
        if operation == "RENAMED":
            pairs = re.findall(
                r"(?ms)^- FROM: `### Requirement: (?P<from>[^`]+)`\s*\n- TO: `### Requirement: (?P<to>[^`]+)`",
                body,
            )
            if not pairs:
                raise ValueError(f"cannot parse RENAMED section: {path}")
            for old_title, new_title in pairs:
                operations.append(
                    {"operation": operation, "from": old_title.strip(), "to": new_title.strip()}
                )
            continue
        blocks = requirement_blocks(body, require_scenario=operation != "REMOVED")
        if not blocks:
            raise ValueError(f"empty {operation} section: {path}")
        for block in blocks:
            operations.append({"operation": operation, "block": block})
    if not operations:
        raise ValueError(f"delta has no operations: {path}")
    return operations


def load_source_groups() -> tuple[dict[str, OrderedDict[str, dict[str, Any]]], dict[str, str]]:
    mapping = all_mapping()
    domain_by_capability = dict(mapping)
    groups: dict[str, OrderedDict[str, dict[str, Any]]] = {}
    source_capabilities = [source for source, _ in load_original_mapping()] + [
        "agent-runtime-service-contract"
    ]
    for capability in source_capabilities:
        blocks = requirement_blocks(
            (TARGET_SNAPSHOT / capability / "spec.md").read_text(encoding="utf-8")
        )
        groups[capability] = OrderedDict((block["title"], block) for block in blocks)

    platform_blocks = requirement_blocks(
        (CANONICAL_ROOT / "platform-operations" / "spec.md").read_text(encoding="utf-8")
    )
    governance = [block for block in platform_blocks if block["title"] in GOVERNANCE_TITLES]
    if [block["title"] for block in governance] != list(GOVERNANCE_TITLES):
        raise ValueError("cannot resolve all canonical governance Requirements")
    groups["canonical-baseline-governance"] = OrderedDict(
        (block["title"], block) for block in governance
    )
    domain_by_capability["canonical-baseline-governance"] = "platform-operations"
    return groups, domain_by_capability


def apply_change(
    change_name: str,
    groups: dict[str, OrderedDict[str, dict[str, Any]]],
    domain_by_capability: dict[str, str],
    operation_log: list[dict[str, Any]],
) -> None:
    delta_root = OPEN_SPEC_ROOT / "changes" / change_name / "specs"
    for path in sorted(delta_root.glob("*/spec.md")):
        capability = path.parent.name
        if capability not in domain_by_capability:
            raise ValueError(f"unmapped delta capability: {capability}")
        group = groups.setdefault(capability, OrderedDict())
        for operation_item in parse_delta(path):
            operation = operation_item["operation"]
            if operation == "RENAMED":
                old_title = operation_item["from"]
                new_title = operation_item["to"]
                if old_title not in group or new_title in group:
                    raise ValueError(
                        f"invalid rename in {change_name}/{capability}: {old_title} -> {new_title}"
                    )
                block = group.pop(old_title)
                block_text = block["text"].replace(
                    f"### Requirement: {old_title}", f"### Requirement: {new_title}", 1
                )
                renamed = requirement_blocks(block_text)[0]
                group[new_title] = renamed
                operation_log.append(
                    {
                        "change": change_name,
                        "capability": capability,
                        "operation": operation,
                        "title": old_title,
                        "action": f"renamed:{new_title}",
                    }
                )
                continue

            block = operation_item["block"]
            title = block["title"]
            before = group.get(title)
            if operation == "ADDED":
                group[title] = block
                action = "replaced-existing" if before else "added"
            elif operation == "MODIFIED":
                if before is None:
                    alias_key = (change_name, capability, title)
                    previous_title = MODIFIED_TITLE_ALIASES.get(alias_key)
                    if previous_title is None or previous_title not in group:
                        raise ValueError(
                            f"MODIFIED Requirement not found: {change_name}/{capability}/{title}"
                        )
                    before = group[previous_title]
                    replaced: OrderedDict[str, dict[str, Any]] = OrderedDict()
                    for existing_title, existing_block in group.items():
                        if existing_title == previous_title:
                            replaced[title] = block
                        else:
                            replaced[existing_title] = existing_block
                    groups[capability] = replaced
                    group = replaced
                    action = f"modified-and-renamed:{previous_title}"
                else:
                    group[title] = block
                    action = "modified"
            elif operation == "REMOVED":
                if before is None:
                    action = "already-absent"
                else:
                    del group[title]
                    action = "removed"
            else:
                raise ValueError(f"unsupported operation: {operation}")
            operation_log.append(
                {
                    "change": change_name,
                    "capability": capability,
                    "operation": operation,
                    "title": title,
                    "action": action,
                    "before_sha256": before["sha256"] if before else None,
                    "after_sha256": block["sha256"] if operation != "REMOVED" else None,
                }
            )


def apply_reconciliation_governance(
    groups: dict[str, OrderedDict[str, dict[str, Any]]], operation_log: list[dict[str, Any]]
) -> None:
    delta = CHANGE_ROOT / "specs" / "platform-operations" / "spec.md"
    operations = parse_delta(delta)
    if len(operations) != 1 or operations[0]["operation"] != "MODIFIED":
        raise ValueError("reconciliation governance delta must contain one MODIFIED Requirement")
    block = operations[0]["block"]
    group = groups["canonical-baseline-governance"]
    title = block["title"]
    if title not in group:
        raise ValueError(f"governance Requirement not found: {title}")
    before = group[title]
    group[title] = block
    operation_log.append(
        {
            "change": "reconcile-mcp-new-canonical-baseline",
            "capability": "platform-operations",
            "operation": "MODIFIED",
            "title": title,
            "action": "modified",
            "before_sha256": before["sha256"],
            "after_sha256": block["sha256"],
        }
    )


def render_domain(
    domain: str,
    purpose: str,
    groups: dict[str, OrderedDict[str, dict[str, Any]]],
    domain_by_capability: dict[str, str],
) -> str:
    parts = [f"# {domain} Specification\n\n## Purpose\n{purpose}\n\n## Requirements\n"]
    capability_order = [source for source, _ in all_mapping()] + ["canonical-baseline-governance"]
    for capability in capability_order:
        if domain_by_capability.get(capability) != domain or not groups.get(capability):
            continue
        parts.append(f"\n<!-- Reconciled from mcp_new capability: `{capability}` -->\n\n")
        for block in groups[capability].values():
            parts.append(block["text"].rstrip() + "\n\n")
    return "".join(parts).rstrip() + "\n"


def build_staging() -> None:
    if STAGING_ROOT.exists():
        raise FileExistsError(f"refusing to overwrite staging root: {STAGING_ROOT}")
    verify_source_snapshot()
    groups, domain_by_capability = load_source_groups()
    operation_log: list[dict[str, Any]] = []
    for change_name in COMPLETED_CHANGES:
        apply_change(change_name, groups, domain_by_capability, operation_log)
    apply_reconciliation_governance(groups, operation_log)

    titles: list[str] = []
    final_entries: list[dict[str, Any]] = []
    for capability, group in groups.items():
        domain = domain_by_capability[capability]
        for block in group.values():
            titles.append(block["title"])
            final_entries.append(block_entry(block, capability=capability, domain=domain))
    duplicates = sorted(title for title, count in Counter(titles).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate final Requirement titles: {duplicates}")

    purposes = {
        domain: purpose_from_spec(CANONICAL_ROOT / domain / "spec.md") for domain in DOMAIN_ORDER
    }
    STAGING_ROOT.mkdir(parents=True, exist_ok=False)
    for domain in DOMAIN_ORDER:
        output_dir = STAGING_ROOT / domain
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "spec.md").write_text(
            render_domain(domain, purposes[domain], groups, domain_by_capability), encoding="utf-8"
        )

    manifest = {
        "source_manifest": SOURCE_MANIFEST.name,
        "delta_order": list(COMPLETED_CHANGES),
        "operation_count": len(operation_log),
        "operations": operation_log,
        "final_domain_count": len(DOMAIN_ORDER),
        "final_requirement_count": len(final_entries),
        "final_scenario_count": sum(int(entry["scenario_count"]) for entry in final_entries),
        "final_entries": final_entries,
    }
    write_json(FINAL_MANIFEST, manifest)
    verify_target(STAGING_ROOT)
    print(
        json.dumps(
            {
                "delta_order": manifest["delta_order"],
                "operations": manifest["operation_count"],
                "domains": manifest["final_domain_count"],
                "requirements": manifest["final_requirement_count"],
                "scenarios": manifest["final_scenario_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def verify_target(target_root: Path) -> None:
    manifest = json.loads(FINAL_MANIFEST.read_text(encoding="utf-8"))
    actual_domains = sorted(path.name for path in target_root.iterdir() if path.is_dir())
    if actual_domains != sorted(DOMAIN_ORDER):
        raise ValueError(f"target domains differ: {actual_domains}")
    expected = Counter(
        (entry["canonical_domain"], entry["title"], entry["sha256"], entry["scenario_count"])
        for entry in manifest["final_entries"]
    )
    actual: Counter[tuple[Any, ...]] = Counter()
    for domain in DOMAIN_ORDER:
        for block in requirement_blocks(
            (target_root / domain / "spec.md").read_text(encoding="utf-8")
        ):
            actual[(domain, block["title"], block["sha256"], block["scenario_count"])] += 1
    if actual != expected:
        raise ValueError("canonical target differs from reconciliation manifest")
    if sum(actual.values()) != int(manifest["final_requirement_count"]):
        raise ValueError("final Requirement count mismatch")
    print(
        json.dumps(
            {
                "target": str(target_root.relative_to(REPO_ROOT)),
                "domains": len(actual_domains),
                "requirements": sum(actual.values()),
                "scenarios": sum(int(item[3]) * count for item, count in actual.items()),
                "verification": "passed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "freeze-source",
            "verify-source",
            "restore-original-archive",
            "verify-original-archive",
            "build-staging",
            "verify-staging",
            "verify-live",
        ),
    )
    args = parser.parse_args()
    if args.command == "freeze-source":
        freeze_source()
    elif args.command == "verify-source":
        verify_source_snapshot()
    elif args.command == "restore-original-archive":
        restore_original_archive()
    elif args.command == "verify-original-archive":
        verify_original_archive()
    elif args.command == "build-staging":
        build_staging()
    elif args.command == "verify-staging":
        verify_target(STAGING_ROOT)
    else:
        verify_target(CANONICAL_ROOT)


if __name__ == "__main__":
    main()
