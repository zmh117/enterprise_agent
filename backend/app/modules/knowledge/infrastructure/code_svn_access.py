"""Resource-owned SVN connections; only the trusted executor resolves credentials."""

from contextlib import contextmanager
from collections.abc import Callable, Iterator
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlsplit, unquote
from uuid import uuid4

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.infrastructure.code_checkout_client import registry, WorkingCopyClient
from app.modules.knowledge.infrastructure.storage import insert, table
from app.shared.database import Database


def connection_fingerprint(entry: dict[str, str]) -> str:
    return (
        digest({k: v for k, v in entry.items() if k not in {"repository_uuid", "branch_path"}})
        if entry.get("secret_ref")
        else digest(entry)
    )


def connection_url(value: Any) -> str:
    try:
        if not isinstance(value, str) or len(value) > 2048 or value != value.strip():
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or "@" in unquote(parsed.path)
            or any(ord(c) < 33 for c in value)
            or "\\" in value
        ):
            raise ValueError
        parsed.port
        return value.rstrip("/")
    except (ValueError, TypeError):
        raise CodeKnowledgeError("CODE_SVN_URL_INVALID") from None


def account(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"username", "password"}:
        raise CodeKnowledgeError("CODE_SVN_CREDENTIAL_INVALID")
    username, password = value["username"], value["password"]
    if any(
        not isinstance(v, str) or not v or any(c in v for c in "\r\n\0")
        for v in (username, password)
    ):
        raise CodeKnowledgeError("CODE_SVN_CREDENTIAL_INVALID")
    if not username.strip() or len(username.encode()) > 256 or len(password.encode()) > 4096:
        raise CodeKnowledgeError("CODE_SVN_CREDENTIAL_INVALID")
    return username, password


class CodeSvnAccess:
    def __init__(self, db: Database, registry_file: Path) -> None:
        self.db, self.registry_file = db, registry_file

    def entries(self, resource_id: str) -> dict[str, dict[str, str]]:
        result = registry(self.registry_file) if self.registry_file.is_file() else {}
        rows = self.db.execute(
            f"SELECT * FROM {table(self.db, 'code_svn_connection')} WHERE resource_id=? ORDER BY created_at,id",
            (resource_id,),
        )
        for row in rows:
            result[row["id"]] = dict(
                public_url=row["public_url"],
                branch_url=row["public_url"],
                repository_uuid=row["repository_uuid"] or "",
                branch_path=row["branch_path"] or "/",
                secret_ref=row["secret_ref"],
                resource_id=resource_id,
            )
        return result

    def entry(self, identifier: str, resource_id: str) -> dict[str, str]:
        entry = self.entries(resource_id).get(identifier)
        if entry is None:
            raise CodeKnowledgeError("CODE_REGISTRATION_CHANGED")
        return entry

    def create(
        self,
        *,
        resource_id: str,
        url: str,
        username: str,
        password: str,
        actor_id: str,
        platform_config: Any,
    ) -> dict[str, Any]:
        url = connection_url(url)
        username, password = account(dict(username=username, password=password))
        identifier = "svn-" + uuid4().hex
        with self.db.unit_of_work():
            secret = platform_config.create_platform_secret(
                dict(
                    code=identifier,
                    value=json.dumps(dict(username=username, password=password)),
                    purpose="SVN 代码仓库访问",
                    metadata={"kind": "svn_account"},
                ),
                actor_id=actor_id,
            )
            insert(
                self.db,
                "code_svn_connection",
                dict(
                    id=identifier,
                    resource_id=resource_id,
                    public_url=url,
                    secret_ref=secret["secret_ref"],
                    created_by=actor_id,
                    created_at=now(),
                ),
            )
        return {"id": identifier, "url": url, "authentication": "account", "configured": True}

    def pin(
        self, identifier: str, resource_id: str, *, repository_uuid: str, branch_path: str
    ) -> None:
        if not self.entry(identifier, resource_id).get("secret_ref"):
            return
        with self.db.unit_of_work():
            suffix = " FOR UPDATE" if self.db.engine == "postgres" else ""
            row = self.db.execute_one(
                f"SELECT * FROM {table(self.db, 'code_svn_connection')} WHERE id=? AND resource_id=?"
                + suffix,
                (identifier, resource_id),
            )
            if not row or (
                row["repository_uuid"] is not None
                and (row["repository_uuid"], row["branch_path"]) != (repository_uuid, branch_path)
            ):
                raise CodeKnowledgeError("CODE_REPOSITORY_CHANGED")
            self.db.execute(
                f"UPDATE {table(self.db, 'code_svn_connection')} SET repository_uuid=?,branch_path=? WHERE id=?",
                (repository_uuid, branch_path, identifier),
            )

    @contextmanager
    def client(
        self,
        entry: dict[str, str],
        auth_root: Path,
        cancelled: Callable[[], bool],
        *,
        factory: Any = WorkingCopyClient,
    ) -> Iterator[WorkingCopyClient]:
        if not entry.get("secret_ref"):
            yield factory(entry, auth_root, cancelled)
            return
        from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
        from app.modules.platform_config.infrastructure.repository import PlatformConfigRepository
        from app.shared.config import load_settings
        from app.shared.master_key import load_master_key_settings

        try:
            settings = load_master_key_settings(load_settings())
            provider = EncryptedDbSecretProvider(
                PlatformConfigRepository(self.db),
                master_key=settings.app_config_master_key,
            )
            credentials = account(json.loads(provider.resolve(entry["secret_ref"])))
        except Exception:
            raise CodeKnowledgeError("CODE_SVN_CREDENTIAL_UNAVAILABLE") from None
        with TemporaryDirectory(prefix="code-svn-config-") as directory:
            yield factory(
                entry,
                auth_root,
                cancelled,
                credentials=credentials,
                config_directory=Path(directory).resolve(),
            )
