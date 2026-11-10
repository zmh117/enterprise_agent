"""Resource-owned SVN connections; only the trusted executor resolves credentials."""

from contextlib import contextmanager
from collections.abc import Callable, Iterator
import json
import ssl
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlsplit, unquote
from uuid import uuid4

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.infrastructure.code_checkout_client import registry, WorkingCopyClient
from app.modules.knowledge.infrastructure.code_source import _read_beneath
from app.modules.knowledge.infrastructure.storage import insert, table
from app.shared.database import Database


def configure_certificate_trust(auth_root: Path, config: Path) -> None:
    """Only deployment-owned public CA certificates enter the temporary SVN config."""
    trusted = auth_root / "trusted-ca"
    try:
        if trusted.is_symlink():
            raise ValueError
        if not trusted.exists():
            return
        if not trusted.is_dir():
            raise ValueError
        certificates = sorted(trusted.glob("*.crt"))
        if not certificates:
            return
        if len(certificates) > 64:
            raise ValueError
        bundle = b""
        for certificate in certificates:
            data = _read_beneath(auth_root, "trusted-ca/" + certificate.name, 1024 * 1024)
            if b"PRIVATE KEY" in data or not data.strip():
                raise ValueError
            ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(
                cadata=data.decode("ascii")
            )
            bundle += data + b"\n"
            if len(bundle) > 1024 * 1024:
                raise ValueError
        target = config / "trusted-ca.pem"
        target.write_bytes(bundle)
        (config / "servers").write_text(f"[global]\nssl-authority-files = {target}\n")
    except (OSError, ValueError, CodeKnowledgeError):
        raise CodeKnowledgeError("CODE_SVN_CERTIFICATE_INVALID") from None


def connection_fingerprint(entry: dict[str, str]) -> str:
    return (
        digest({k: v for k, v in entry.items() if k not in {"repository_uuid", "branch_path"}})
        if entry.get("resource_id")
        else digest(entry)
    )


def connection_url(value: Any) -> str:
    try:
        if not isinstance(value, str) or len(value) > 2048 or value != value.strip():
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https", "svn"}
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

    def checkout_connection(self, checkout_id: str, resource_id: str) -> dict[str, str]:
        """Resolve only the successful checkout's original connection, never a URL match."""
        rows = self.db.execute(
            f"SELECT o.request_json,v.resource_id,r.repository_uuid,r.branch_path "
            f"FROM {table(self.db, 'code_svn_operation')} o "
            f"JOIN {table(self.db, 'retrieval_revision')} v ON v.id=o.config_revision_id "
            f"JOIN {table(self.db, 'code_checkout')} c ON c.id=o.checkout_id AND c.source_id=o.source_id "
            f"JOIN {table(self.db, 'code_repository')} r ON r.source_id=c.source_id "
            "WHERE o.checkout_id=? AND o.operation_kind='checkout' AND o.state='succeeded' "
            "ORDER BY o.created_at,o.id LIMIT 2",
            (checkout_id,),
        )
        if len(rows) != 1:
            raise CodeKnowledgeError("CODE_CHECKOUT_CONNECTION_UNAVAILABLE")
        row = rows[0]
        request = row["request_json"]
        if isinstance(request, str):
            request = json.loads(request)
        if not isinstance(request, dict):
            raise CodeKnowledgeError("CODE_CHECKOUT_CONNECTION_UNAVAILABLE")
        reference = request.get("registration")
        if not isinstance(reference, str) or not reference:
            raise CodeKnowledgeError("CODE_CHECKOUT_CONNECTION_UNAVAILABLE")
        entry = self.entry(reference, resource_id)
        if (
            request.get("registration_hash") != connection_fingerprint(entry)
            or str(row["repository_uuid"]) != entry["repository_uuid"]
            or row["branch_path"] != entry["branch_path"].strip("/")
            or (entry.get("resource_id") and entry["resource_id"] != row["resource_id"])
        ):
            raise CodeKnowledgeError("CODE_REGISTRATION_CHANGED")
        return {
            "id": reference,
            "url": entry["branch_url"],
            "kind": "account"
            if entry.get("secret_ref")
            else "anonymous"
            if entry.get("resource_id")
            else "deployment",
        }

    def create(
        self,
        *,
        resource_id: str,
        url: str,
        username: str | None = None,
        password: str | None = None,
        authentication: str = "account",
        actor_id: str,
        platform_config: Any,
    ) -> dict[str, Any]:
        url = connection_url(url)
        if authentication not in {"account", "anonymous"}:
            raise CodeKnowledgeError("CODE_SVN_CREDENTIAL_INVALID")
        if authentication == "anonymous":
            if username is not None or password is not None:
                raise CodeKnowledgeError("CODE_SVN_CREDENTIAL_INVALID")
            # An anonymous request never borrows deployment routing or a saved account.
            existing = self.db.execute_one(
                f"SELECT id FROM {table(self.db, 'code_svn_connection')} "
                "WHERE resource_id=? AND public_url=? AND secret_ref='' ORDER BY created_at,id LIMIT 1",
                (resource_id, url),
            )
            if existing:
                return {
                    "id": existing["id"],
                    "url": url,
                    "authentication": authentication,
                    "configured": True,
                }
        else:
            username, password = account(dict(username=username, password=password))
        identifier = "svn-" + uuid4().hex
        with self.db.unit_of_work():
            secret = (
                platform_config.create_platform_secret(
                    dict(
                        code=identifier,
                        value=json.dumps(dict(username=username, password=password)),
                        purpose="SVN 代码仓库访问",
                        metadata={"kind": "svn_account"},
                    ),
                    actor_id=actor_id,
                )
                if authentication == "account"
                else None
            )
            insert(
                self.db,
                "code_svn_connection",
                dict(
                    id=identifier,
                    resource_id=resource_id,
                    public_url=url,
                    secret_ref=secret["secret_ref"] if secret else "",
                    created_by=actor_id,
                    created_at=now(),
                ),
            )
        return {"id": identifier, "url": url, "authentication": authentication, "configured": True}

    def pin(
        self, identifier: str, resource_id: str, *, repository_uuid: str, branch_path: str
    ) -> None:
        if not self.entry(identifier, resource_id).get("resource_id"):
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
        if not entry.get("resource_id"):
            yield factory(entry, auth_root, cancelled)
            return
        credentials = self._credentials(entry["secret_ref"]) if entry["secret_ref"] else None
        with TemporaryDirectory(prefix="code-svn-config-") as directory:
            config = Path(directory).resolve()
            configure_certificate_trust(auth_root, config)
            yield factory(
                entry,
                auth_root,
                cancelled,
                credentials=credentials,
                config_directory=config,
            )

    def _credentials(self, secret_ref: str) -> tuple[str, str]:
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
            return account(json.loads(provider.resolve(secret_ref)))
        except Exception:
            raise CodeKnowledgeError("CODE_SVN_CREDENTIAL_UNAVAILABLE") from None
