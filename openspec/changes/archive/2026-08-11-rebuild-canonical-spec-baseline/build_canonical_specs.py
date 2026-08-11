#!/usr/bin/env python3
"""Build and verify the lossless domain-oriented canonical OpenSpec baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


CHANGE_ROOT = Path(__file__).resolve().parent


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "openspec" / "config.yaml").is_file() and (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"cannot locate repository root from {start}")


REPO_ROOT = find_repo_root(CHANGE_ROOT)
SOURCE_SPECS = REPO_ROOT / "openspec" / "specs"
SOURCE_SNAPSHOT = CHANGE_ROOT / "source-specs-snapshot"
DELTA_SPECS = CHANGE_ROOT / "specs"
STAGING_SPECS = CHANGE_ROOT / "_canonical_staging"
MAPPING_PATH = CHANGE_ROOT / "migration-map.tsv"
MANIFEST_PATH = CHANGE_ROOT / "source-manifest.json"

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

PURPOSES = {
    "identity-access": "定义内部用户、外部身份、认证、角色、授权及其管理入口的统一领域契约，确保身份、个人凭据、管理权限、应用访问和数据范围彼此独立。",
    "agent-model": "定义 Agent、模型连接、工作流模板及 Agent 管理面的版本化配置、验证、发布与运行引用契约，确保草稿变化不会改写已冻结的执行配置。",
    "business-application": "定义业务应用对 Agent、Capability、内置工具、入口、权限和运行策略的装配、发布与路由契约。",
    "channel-conversation": "定义 Channel、钉钉、Webhook、会话、消息和附件的受治理入口、持久化、幂等处理与投递契约，确保外部事件只能通过已发布路由进入系统。",
    "execution-delivery": "定义 Agent Job、Runtime、队列、Outbox、重试、审计和结果投递的可靠执行契约，确保状态事实、幂等恢复与执行和投递分离保持一致。",
    "builtin-tool-resource": "定义内置只读工具、资源版本、业务拓扑、数据库、Redis 和 Loki 的治理、发布、绑定与执行边界，确保模型不能绕过受管资源和只读策略。",
    "governed-api-capability": "定义外部 API Connection、认证配置、个人凭据、Capability、Handler、Release 及 ONES 能力的治理契约。",
    "platform-operations": "定义平台配置、Secret、Migration、Compose、测试环境、运行验收及 canonical 规格读取治理。",
}

GOVERNANCE_REQUIREMENTS = """### Requirement: Canonical 主规格是唯一当前规范基线
仓库 SHALL 仅将 `openspec/specs/<canonical-domain>/spec.md` 视为当前已接受规范的 canonical baseline。Active change、archive、proposal、design、tasks、evidence、ADR 和运行手册 MUST NOT 覆盖 canonical Requirement；需要改变当前规范时 MUST 通过明确的 OpenSpec change 更新 canonical specs。

#### Scenario: 判断当前已接受规范
- **WHEN** Codex 或维护者需要确定项目当前的规范要求
- **THEN** 其以相关领域的 canonical spec 为规范事实源，不从历史 change 或辅助文档推断替代要求

#### Scenario: 辅助文档与主规格冲突
- **WHEN** ADR、运行手册或历史 evidence 与 canonical Requirement 表述冲突
- **THEN** 系统维护流程将冲突记录为待处理 change，而不静默改写或绕过 canonical spec

### Requirement: Codex 默认按领域读取 Canonical 主规格
仓库级 Codex 指令 SHALL 要求 Codex 在一般规格、设计和实现任务中只默认读取与请求相关的 canonical domain specs。只有在用户指定 active change、执行 OpenSpec change 工作流或明确要求历史审计时，Codex 才可读取对应 change 或 archive，并 MUST 明确区分其非当前规范身份。

#### Scenario: 处理普通领域需求
- **WHEN** 用户提出身份、Agent、业务应用、Channel、执行、内置工具、API Capability 或平台运维需求且未指定 change
- **THEN** Codex 只加载相关 canonical domain spec 作为默认规格上下文

#### Scenario: 处理指定 Active Change
- **WHEN** 用户指定某个 active change 或要求执行 propose、apply、sync、archive 工作流
- **THEN** Codex 可读取该 change 的 artifacts，并以 delta 相对 canonical baseline 的语义处理，而不加载无关 change 或 archive

#### Scenario: 明确追溯历史
- **WHEN** 用户明确要求审计历史决策或归档证据
- **THEN** Codex 可读取相关 archive，但将其标记为历史证据且不把它当作当前规范

### Requirement: Archive 保持完整且不参与默认规范解析
基线重建 SHALL 保留 `openspec/changes/archive/` 下的历史内容，不得为了减少默认上下文而删除或改写既有 archive。默认规范解析 MUST 排除 archive；历史内容只有在显式追溯时才参与证据分析。

#### Scenario: 重建 Canonical Baseline
- **WHEN** 维护者替换或重组主规格文件
- **THEN** 既有 archive 的目录、proposal、design、tasks、delta specs 和 evidence 保持不变

#### Scenario: 默认规格检索
- **WHEN** Codex 搜索当前领域要求且用户没有请求历史
- **THEN** 搜索范围排除 `openspec/changes/archive/`
"""

REQUIREMENT_RE = re.compile(r"(?m)^### Requirement: (?P<title>.+)$")
SCENARIO_RE = re.compile(r"(?m)^#### Scenario: ")
SOURCE_COMMENT_RE = re.compile(
    r"(?m)^<!-- Migrated from (?:canonical source capability|baseline governance): `[^`]+` -->\n?"
)


def load_mapping() -> list[tuple[str, str]]:
    with MAPPING_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    mapping = [(row["source_capability"], row["canonical_domain"]) for row in rows]
    sources = [source for source, _ in mapping]
    if len(sources) != len(set(sources)):
        raise ValueError("migration-map.tsv contains duplicate source capabilities")
    unknown_domains = sorted({domain for _, domain in mapping} - set(DOMAIN_ORDER))
    if unknown_domains:
        raise ValueError(f"unknown canonical domains: {unknown_domains}")
    source_root = SOURCE_SNAPSHOT if SOURCE_SNAPSHOT.is_dir() else SOURCE_SPECS
    actual_sources = sorted(path.name for path in source_root.iterdir() if path.is_dir())
    if sorted(sources) != actual_sources:
        missing = sorted(set(actual_sources) - set(sources))
        unknown = sorted(set(sources) - set(actual_sources))
        raise ValueError(f"mapping/source mismatch: missing={missing}, unknown={unknown}")
    return mapping


def requirement_blocks(text: str) -> list[dict[str, object]]:
    matches = list(REQUIREMENT_RE.finditer(text))
    blocks: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = text[match.start() : end]
        normalized = SOURCE_COMMENT_RE.sub("", raw).rstrip() + "\n"
        blocks.append(
            {
                "title": match.group("title").strip(),
                "text": normalized,
                "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                "scenario_count": len(SCENARIO_RE.findall(normalized)),
            }
        )
    return blocks


def read_source_blocks(mapping: list[tuple[str, str]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_titles: set[str] = set()
    manifest_entries: list[dict[str, object]] = []
    source_root = SOURCE_SNAPSHOT if SOURCE_SNAPSHOT.is_dir() else SOURCE_SPECS
    for source, domain in mapping:
        path = source_root / source / "spec.md"
        text = path.read_text(encoding="utf-8")
        if "## Requirements" not in text:
            raise ValueError(f"missing Requirements section: {path}")
        blocks = requirement_blocks(text)
        if not blocks:
            raise ValueError(f"no Requirement blocks: {path}")
        for block in blocks:
            title = str(block["title"])
            if title in seen_titles:
                raise ValueError(f"duplicate Requirement title: {title}")
            seen_titles.add(title)
            enriched = {**block, "source_capability": source, "canonical_domain": domain}
            grouped[domain].append(enriched)
            manifest_entries.append(
                {key: value for key, value in enriched.items() if key != "text"}
            )
    manifest = {
        "source_capability_count": len(mapping),
        "source_requirement_count": len(manifest_entries),
        "source_scenario_count": sum(int(entry["scenario_count"]) for entry in manifest_entries),
        "entries": manifest_entries,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return grouped


def grouped_sources(mapping: list[tuple[str, str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for source, domain in mapping:
        result[domain].append(source)
    return result


def render_domain(
    domain: str,
    sources: list[str],
    grouped: dict[str, list[dict[str, object]]],
    *,
    delta: bool,
) -> str:
    parts = [
        "## ADDED Requirements\n"
        if delta
        else f"# {domain} Specification\n\n## Purpose\n{PURPOSES[domain]}\n\n## Requirements\n"
    ]
    by_source: dict[str, list[dict[str, object]]] = defaultdict(list)
    for block in grouped[domain]:
        by_source[str(block["source_capability"])].append(block)
    for source in sources:
        parts.append(f"\n<!-- Migrated from canonical source capability: `{source}` -->\n\n")
        for block in by_source[source]:
            parts.append(str(block["text"]).rstrip() + "\n\n")
    if domain == "platform-operations":
        parts.append(
            "<!-- Migrated from baseline governance: `rebuild-canonical-spec-baseline` -->\n\n"
        )
        parts.append(GOVERNANCE_REQUIREMENTS.rstrip() + "\n")
    return "".join(parts).rstrip() + "\n"


def build(target_root: Path, *, delta: bool) -> None:
    if target_root.exists() and any(target_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty target: {target_root}")
    target_root.mkdir(parents=True, exist_ok=True)
    mapping = load_mapping()
    grouped = read_source_blocks(mapping)
    source_groups = grouped_sources(mapping)
    for domain in DOMAIN_ORDER:
        output_dir = target_root / domain
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "spec.md").write_text(
            render_domain(domain, source_groups[domain], grouped, delta=delta),
            encoding="utf-8",
        )


def verify(target_root: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected = Counter(entry["sha256"] for entry in manifest["entries"])
    governance_hashes = Counter(
        block["sha256"] for block in requirement_blocks(GOVERNANCE_REQUIREMENTS)
    )
    actual_entries: list[dict[str, object]] = []
    for domain in DOMAIN_ORDER:
        path = target_root / domain / "spec.md"
        if not path.is_file():
            raise ValueError(f"missing canonical spec: {path}")
        actual_entries.extend(requirement_blocks(path.read_text(encoding="utf-8")))
    actual = Counter(entry["sha256"] for entry in actual_entries)
    migrated_actual = actual - governance_hashes
    if migrated_actual != expected:
        missing = list((expected - migrated_actual).elements())
        extra = list((migrated_actual - expected).elements())
        raise ValueError(f"Requirement block hash mismatch: missing={missing}, extra={extra}")
    if actual - expected != governance_hashes:
        raise ValueError("unexpected non-source Requirement blocks in canonical target")
    expected_scenarios = int(manifest["source_scenario_count"])
    actual_migrated_scenarios = sum(int(entry["scenario_count"]) for entry in actual_entries) - sum(
        int(block["scenario_count"]) for block in requirement_blocks(GOVERNANCE_REQUIREMENTS)
    )
    if actual_migrated_scenarios != expected_scenarios:
        raise ValueError(
            f"Scenario count mismatch: expected={expected_scenarios}, actual={actual_migrated_scenarios}"
        )
    print(
        json.dumps(
            {
                "canonical_domains": len(DOMAIN_ORDER),
                "migrated_requirements": len(manifest["entries"]),
                "new_governance_requirements": sum(governance_hashes.values()),
                "total_requirements": len(actual_entries),
                "migrated_scenarios": actual_migrated_scenarios,
                "verification": "passed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def verify_source_snapshot() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
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
    source_root = SOURCE_SNAPSHOT if SOURCE_SNAPSHOT.is_dir() else SOURCE_SPECS
    actual: Counter[tuple[object, ...]] = Counter()
    for source, domain in load_mapping():
        path = source_root / source / "spec.md"
        for block in requirement_blocks(path.read_text(encoding="utf-8")):
            actual[
                (
                    source,
                    domain,
                    block["title"],
                    block["sha256"],
                    block["scenario_count"],
                )
            ] += 1
    if actual != expected:
        raise ValueError("source snapshot differs from the frozen source manifest")
    print(
        json.dumps(
            {
                "source_capabilities": len({entry[0] for entry in actual}),
                "source_requirements": sum(actual.values()),
                "source_scenarios": sum(int(entry[4]) * count for entry, count in actual.items()),
                "source_snapshot_verification": "passed",
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
            "build-delta",
            "build-staging",
            "verify-delta",
            "verify-staging",
            "verify-live",
            "verify-source-snapshot",
        ),
    )
    args = parser.parse_args()
    if args.command == "build-delta":
        build(DELTA_SPECS, delta=True)
    elif args.command == "build-staging":
        build(STAGING_SPECS, delta=False)
    elif args.command == "verify-delta":
        verify(DELTA_SPECS)
    elif args.command == "verify-staging":
        verify(STAGING_SPECS)
    elif args.command == "verify-live":
        verify(SOURCE_SPECS)
    else:
        verify_source_snapshot()


if __name__ == "__main__":
    main()
