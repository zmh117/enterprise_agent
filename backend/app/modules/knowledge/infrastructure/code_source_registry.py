"""Deployment-owned SVN targets and opaque authentication-directory references."""

from pathlib import Path
from typing import Any
from collections.abc import Callable

from app.modules.knowledge.infrastructure.code_svn_admission import SvnSourceAdmission
from app.modules.knowledge.domain.code_contracts import COMPONENTS, CodeKnowledgeError
from app.modules.knowledge.domain.code_package import parse_json
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_snapshot_directory import directory_id
from app.modules.knowledge.infrastructure.code_source import _read_beneath, relative_path
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource

CONNECTION_FIELDS = {"branch_url", "repository_uuid", "branch_path", "auth_ref"}


class CodeSourceRegistry:
    def __init__(
        self, path: Path, auth_root: Path, *, cancelled: Callable[[], bool] | None = None
    ) -> None:
        if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
            raise CodeKnowledgeError("code_registry_path_invalid")
        if (
            not auth_root.is_absolute()
            or auth_root.is_symlink()
            or auth_root.resolve() != auth_root
        ):
            raise CodeKnowledgeError("code_svn_auth_reference_invalid")
        self.path, self.auth_root = path, auth_root
        self.cancelled = cancelled

    def get(self, key: str) -> tuple[dict[str, Any], SvnSourceAdmission]:
        directory_id(key)
        raw = _read_beneath(self.path.parent, self.path.name, 64 * 1024)
        registry = parse_json(raw.decode("utf-8"))
        if not isinstance(registry, dict) or len(registry) > 20 or key not in registry:
            raise CodeKnowledgeError("code_registration_unavailable")
        entry = registry[key]
        if not isinstance(entry, dict) or set(entry) != CONNECTION_FIELDS | {
            "components",
            "externals",
        }:
            raise CodeKnowledgeError("code_registration_invalid")
        components = entry["components"]
        if not isinstance(components, dict) or set(components) != set(COMPONENTS):
            raise CodeKnowledgeError("code_svn_components_invalid")
        for path in components.values():
            relative_path(path)
        if any(
            a == b or a.startswith(b + "/")
            for i, a in enumerate(components.values())
            for j, b in enumerate(components.values())
            if i != j
        ):
            raise CodeKnowledgeError("code_svn_components_invalid")
        main = self._connection({name: entry[name] for name in CONNECTION_FIELDS})
        external_config = entry["externals"]
        if not isinstance(external_config, dict) or len(external_config) > 20:
            raise CodeKnowledgeError("code_svn_externals_limit")
        externals = {}
        for path, config in external_config.items():
            relative_path(path)
            if not any(path.startswith(prefix + "/") for prefix in components.values()):
                raise CodeKnowledgeError("code_svn_path_outside_components")
            externals[path] = self._connection(config)
        return {"key": key, "digest": digest(entry), "connection": entry}, SvnSourceAdmission(
            main, components, externals=externals
        )

    def _connection(self, config: Any) -> SvnCodeSource:
        if (
            not isinstance(config, dict)
            or set(config) != CONNECTION_FIELDS
            or not all(isinstance(v, str) for v in config.values())
        ):
            raise CodeKnowledgeError("code_registration_invalid")
        reference = directory_id(config["auth_ref"])
        directory = self.auth_root / reference
        if directory.is_symlink() or not directory.is_dir() or directory.resolve() != directory:
            raise CodeKnowledgeError("code_svn_auth_reference_invalid")
        return SvnCodeSource(
            branch_url=config["branch_url"],
            expected_uuid=config["repository_uuid"],
            branch_path=config["branch_path"],
            config_directory=directory,
            cancelled=self.cancelled,
        )
