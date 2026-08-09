from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
import uuid
from email.message import Message
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import yaml

from app.modules.mcp_resources.service import validate_manifest


DEFAULT_SESSION_PATH = Path.home() / ".config" / "enterprise-agent" / "platformctl-session.json"


class PlatformCtlError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        return None


class PlatformClient:
    def __init__(self, session_path: Path) -> None:
        self.session_path = session_path
        self.session = self._load_session()
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    @property
    def base_url(self) -> str:
        return str(self.session.get("base_url") or "").rstrip("/")

    def login(self, *, base_url: str, username: str, password: str) -> dict[str, Any]:
        _validate_base_url(base_url)
        status, headers, payload = self._raw_request(
            base_url.rstrip("/") + "/api/auth/login",
            method="POST",
            body={"username": username, "password": password},
            headers={"Origin": base_url.rstrip("/")},
        )
        password = ""
        if status != 200:
            raise PlatformCtlError(_safe_error(payload, status))
        cookies: dict[str, str] = {}
        for value in headers.get_all("Set-Cookie") or []:
            parsed = SimpleCookie()
            parsed.load(value)
            for key, morsel in parsed.items():
                cookies[key] = morsel.value
        csrf = next((value for key, value in cookies.items() if "csrf" in key.lower()), "")
        if len(cookies) < 2 or not csrf:
            raise PlatformCtlError("登录响应缺少安全 Session Cookie")
        self.session = {
            "base_url": base_url.rstrip("/"),
            "cookies": cookies,
            "csrf": csrf,
            "username": username,
        }
        self._save_session()
        return {"status": "logged_in", "user": payload.get("user", {})}

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        if not self.base_url:
            raise PlatformCtlError("请先执行 platformctl login")
        headers = {
            "Cookie": "; ".join(f"{key}={value}" for key, value in self.session["cookies"].items()),
            "Origin": self.base_url,
            "X-Correlation-Id": f"platformctl-{uuid.uuid4().hex}",
        }
        if method != "GET":
            headers["X-CSRF-Token"] = str(self.session["csrf"])
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        status, _, payload = self._raw_request(
            self.base_url + path,
            method=method,
            body=body,
            headers=headers,
        )
        if not 200 <= status < 300:
            raise PlatformCtlError(_safe_error(payload, status))
        return payload

    def _raw_request(
        self,
        url: str,
        *,
        method: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> tuple[int, Message[str, str], dict[str, Any]]:
        encoded = (
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            if body is not None
            else None
        )
        request = Request(
            url,
            data=encoded,
            method=method,
            headers={
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if encoded is not None else {}),
                **headers,
            },
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read(1024 * 1024 + 1)
                return int(response.status), response.headers, _json(raw)
        except HTTPError as exc:
            return int(exc.code), exc.headers, _json(exc.read(1024 * 1024 + 1))
        except (URLError, TimeoutError, OSError) as exc:
            raise PlatformCtlError("无法连接平台 API") from exc

    def _load_session(self) -> dict[str, Any]:
        if not self.session_path.exists():
            return {}
        mode = stat.S_IMODE(self.session_path.stat().st_mode)
        if mode != 0o600:
            raise PlatformCtlError("Session 文件权限必须为 0600")
        try:
            value = json.loads(self.session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlatformCtlError("Session 文件不可读") from exc
        return value if isinstance(value, dict) else {}

    def _save_session(self) -> None:
        self.session_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.session_path.is_symlink():
            raise PlatformCtlError("Session 文件不能是符号链接")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(
            self.session_path,
            flags,
            0o600,
        )
        try:
            os.write(
                descriptor,
                json.dumps(self.session, ensure_ascii=True, separators=(",", ":")).encode(),
            )
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platformctl")
    parser.add_argument(
        "--session-file",
        type=Path,
        default=Path(os.environ.get("PLATFORMCTL_SESSION_FILE", DEFAULT_SESSION_PATH)),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser("login")
    login.add_argument("--base-url", required=True)
    login.add_argument("--username", required=True)

    resource = commands.add_parser("resource")
    resource_commands = resource.add_subparsers(dest="resource_command", required=True)
    for name in ("plan", "apply"):
        item = resource_commands.add_parser(name)
        item.add_argument("--file", type=Path, required=True)
        if name == "apply":
            item.add_argument("--expected-revision", type=int, required=True)
            item.add_argument("--idempotency-key", required=True)
    for name in ("verify", "publish", "unpublish"):
        item = resource_commands.add_parser(name)
        item.add_argument("code")
        item.add_argument("--expected-revision", type=int, required=True)
        if name == "publish":
            item.add_argument("--idempotency-key", required=True)
    status = resource_commands.add_parser("status")
    status.add_argument("code", nargs="?")
    draft = resource_commands.add_parser("draft-from-revision")
    draft.add_argument("code")
    draft.add_argument("resource_revision_id")
    draft.add_argument("--expected-revision", type=int, required=True)
    draft.add_argument("--idempotency-key", required=True)

    secret = commands.add_parser("secret")
    secret_commands = secret.add_subparsers(dest="secret_command", required=True)
    create = secret_commands.add_parser("create")
    create.add_argument("code")
    create.add_argument("--purpose", default="")
    rotate = secret_commands.add_parser("rotate")
    rotate.add_argument("code")
    rotate.add_argument("--expected-revision", type=int, required=True)
    disable = secret_commands.add_parser("disable")
    disable.add_argument("code")
    disable.add_argument("--expected-revision", type=int, required=True)
    usages = secret_commands.add_parser("usages")
    usages.add_argument("code")

    mcp = commands.add_parser("mcp")
    mcp_commands = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_commands.add_parser("tools")
    mcp_commands.add_parser("status")
    publication = mcp_commands.add_parser("publication")
    publication_commands = publication.add_subparsers(dest="publication_command", required=True)
    publication_commands.add_parser("list")
    publication_commands.add_parser("catalog")
    show_publication = publication_commands.add_parser("show")
    show_publication.add_argument("code")
    create_publication = publication_commands.add_parser("create")
    create_publication.add_argument("code")
    create_publication.add_argument("--name", required=True)
    create_publication.add_argument("--catalog-key", required=True)
    create_publication.add_argument("--resource-deployment-id", default="")
    create_publication.add_argument("--idempotency-key", required=True)
    update_publication = publication_commands.add_parser("update")
    update_publication.add_argument("code")
    update_publication.add_argument("--catalog-key", required=True)
    update_publication.add_argument("--resource-deployment-id", default="")
    update_publication.add_argument("--expected-revision", type=int, required=True)
    update_publication.add_argument("--idempotency-key", required=True)
    for name in ("verify", "publish", "disable", "archive"):
        item = publication_commands.add_parser(name)
        item.add_argument("code")
        item.add_argument("--expected-revision", type=int, required=True)
        item.add_argument("--idempotency-key", required=True)
    rollback_publication = publication_commands.add_parser("rollback")
    rollback_publication.add_argument("code")
    rollback_publication.add_argument("--publication-id", required=True)
    rollback_publication.add_argument("--expected-revision", type=int, required=True)
    rollback_publication.add_argument("--idempotency-key", required=True)

    cutover = commands.add_parser("cutover")
    cutover_commands = cutover.add_subparsers(dest="cutover_command", required=True)
    cutover_commands.add_parser("check")
    clean = cutover_commands.add_parser("clean")
    clean.add_argument("--manifest-hash", required=True)
    clean.add_argument("--confirm", required=True)
    clean.add_argument("--entrances-stopped", action="store_true")
    clean.add_argument("--workers-stopped", action="store_true")
    clean.add_argument("--legacy-services-stopped", action="store_true")
    cutover_commands.add_parser("verify")
    return parser


def execute(args: argparse.Namespace, client: PlatformClient) -> dict[str, Any]:
    if args.command == "login":
        password = getpass.getpass("Password: ")
        try:
            return client.login(
                base_url=args.base_url,
                username=args.username,
                password=password,
            )
        finally:
            password = ""
    if args.command == "resource":
        operation = args.resource_command
        if operation in {"plan", "apply"}:
            manifest = _manifest(args.file)
            if operation == "plan":
                return client.request(
                    "/api/admin/mcp/resources/plan",
                    method="POST",
                    body={"manifest": manifest},
                )
            return client.request(
                "/api/admin/mcp/resources/apply",
                method="POST",
                body={
                    "manifest": manifest,
                    "expected_revision": args.expected_revision,
                    "idempotency_key": args.idempotency_key,
                },
            )
        if operation == "status":
            suffix = f"/{args.code}" if args.code else ""
            return client.request("/api/admin/mcp/resources" + suffix)
        if operation == "draft-from-revision":
            return client.request(
                f"/api/admin/mcp/resources/{args.code}/draft-from-revision",
                method="POST",
                body={
                    "resource_revision_id": args.resource_revision_id,
                    "expected_revision": args.expected_revision,
                    "idempotency_key": args.idempotency_key,
                },
            )
        body = {"expected_revision": args.expected_revision}
        if operation == "publish":
            body["idempotency_key"] = args.idempotency_key
        return client.request(
            f"/api/admin/mcp/resources/{args.code}/{operation}",
            method="POST",
            body=body,
        )
    if args.command == "secret":
        operation = args.secret_command
        if operation in {"create", "rotate"}:
            if sys.stdin.isatty():
                raise PlatformCtlError("Secret 明文必须通过 stdin 或受保护文件描述符提供")
            value = sys.stdin.read(65_537)
            if not value or len(value) > 65_536:
                raise PlatformCtlError("Secret 输入为空或过大")
            value = value.rstrip("\r\n")
            try:
                if operation == "create":
                    return client.request(
                        "/api/platform/secrets",
                        method="POST",
                        body={"code": args.code, "purpose": args.purpose, "value": value},
                    )
                return client.request(
                    f"/api/platform/secrets/{args.code}/rotate",
                    method="POST",
                    body={
                        "value": value,
                        "expected_revision": args.expected_revision,
                    },
                )
            finally:
                value = ""
        if operation == "disable":
            return client.request(
                f"/api/platform/secrets/{args.code}/disable",
                method="POST",
                body={"expected_revision": args.expected_revision},
            )
        return client.request(f"/api/platform/secrets/{args.code}/usage")
    if args.command == "mcp":
        if args.mcp_command == "tools":
            return client.request("/api/admin/mcp/tools")
        if args.mcp_command == "publication":
            operation = args.publication_command
            if operation == "catalog":
                return client.request("/api/admin/mcp/tools")
            if operation == "list":
                return client.request("/api/admin/mcp/tool-publications")
            if operation == "show":
                return client.request(f"/api/admin/mcp/tool-publications/{args.code}")
            if operation == "create":
                return client.request(
                    "/api/admin/mcp/tool-publications",
                    method="POST",
                    body={
                        "expected_revision": 0,
                        "code": args.code,
                        "name": args.name,
                        "catalog_key": args.catalog_key,
                        "resource_deployment_id": args.resource_deployment_id,
                    },
                    idempotency_key=args.idempotency_key,
                )
            if operation == "update":
                return client.request(
                    f"/api/admin/mcp/tool-publications/{args.code}/draft",
                    method="PUT",
                    body={
                        "catalog_key": args.catalog_key,
                        "resource_deployment_id": args.resource_deployment_id,
                        "expected_revision": args.expected_revision,
                    },
                    idempotency_key=args.idempotency_key,
                )
            body = {"expected_revision": args.expected_revision}
            if operation == "rollback":
                body["publication_id"] = args.publication_id
            return client.request(
                f"/api/admin/mcp/tool-publications/{args.code}/{operation}",
                method="POST",
                body=body,
                idempotency_key=args.idempotency_key,
            )
        return client.request("/api/admin/mcp/status")
    if args.command == "cutover":
        if args.cutover_command == "check":
            return client.request("/api/admin/cutover/check")
        if args.cutover_command == "verify":
            return client.request("/api/admin/cutover/verify")
        return client.request(
            "/api/admin/cutover/clean",
            method="POST",
            body={
                "manifest_hash": args.manifest_hash,
                "confirmation": args.confirm,
                "entrances_stopped": args.entrances_stopped,
                "workers_stopped": args.workers_stopped,
                "legacy_services_stopped": args.legacy_services_stopped,
            },
        )
    raise PlatformCtlError("不支持的命令")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = execute(args, PlatformClient(args.session_file))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except PlatformCtlError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PlatformCtlError("资源声明文件不存在")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        canonical, _, _ = validate_manifest(value)
        return canonical
    except Exception as exc:
        raise PlatformCtlError("资源声明文件无效或包含不允许的字段") from exc


def _validate_base_url(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise PlatformCtlError("平台 API 地址无效")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PlatformCtlError("非本机平台 API 必须使用 HTTPS")


def _json(raw: bytes) -> dict[str, Any]:
    if len(raw) > 1024 * 1024:
        raise PlatformCtlError("平台 API 响应过大")
    try:
        value = json.loads(raw.decode()) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_error(payload: dict[str, Any], status: int) -> str:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        message = str(detail.get("message") or "")
        code = str(detail.get("code") or "")
        return f"{message or '平台请求失败'} ({code or status})"
    if isinstance(detail, str) and len(detail) <= 300:
        return detail
    return f"平台请求失败 (HTTP {status})"


if __name__ == "__main__":
    raise SystemExit(main())
