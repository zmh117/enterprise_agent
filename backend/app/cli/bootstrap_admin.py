from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import stat
import sys
from typing import Callable

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application import AuthService
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


DEFAULT_USERNAME = "admin"
DEFAULT_DISPLAY_NAME = "Administrator"
LOCAL_DEFAULT_PASSWORD = "111111111111"
DEFAULT_PASSWORD_FILE = Path("/run/secrets/initial_admin_password")
LOCAL_ENVIRONMENTS = frozenset({"local", "test", "testing", "development"})


class InitialAdminBootstrapError(RuntimeError):
    """Safe bootstrap rejection that never contains password material."""


def _password_from_file(path: Path) -> str:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise InitialAdminBootstrapError(
            "initial administrator password file is unavailable"
        ) from exc
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise InitialAdminBootstrapError(
            "initial administrator password path must be a regular non-symlink file"
        )
    if stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise InitialAdminBootstrapError(
            "initial administrator password file permissions must be 0400 or 0600"
        )
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InitialAdminBootstrapError(
            "initial administrator password file is unreadable"
        ) from exc
    password = payload.removesuffix("\n").removesuffix("\r")
    if not password or "\n" in password or "\r" in password or "\x00" in password:
        raise InitialAdminBootstrapError(
            "initial administrator password file must contain one non-empty line"
        )
    if len(password) > 1024:
        raise InitialAdminBootstrapError("initial administrator password is too long")
    return password


def resolve_initial_admin_password(
    *,
    environment: str,
    password_file: Path,
    non_interactive: bool,
    stdin_isatty: bool | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
) -> str:
    if password_file.exists():
        return _password_from_file(password_file)
    if environment.lower() in LOCAL_ENVIRONMENTS:
        return LOCAL_DEFAULT_PASSWORD
    interactive = sys.stdin.isatty() if stdin_isatty is None else stdin_isatty
    if non_interactive or not interactive:
        raise InitialAdminBootstrapError(
            "non-local bootstrap requires a protected password file or interactive input"
        )
    password = prompt("Initial administrator password (minimum 12 characters): ")
    confirmation = prompt("Confirm initial administrator password: ")
    if password != confirmation:
        raise InitialAdminBootstrapError("initial administrator passwords do not match")
    return password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Idempotently create the initial platform administrator"
    )
    parser.add_argument(
        "--password-file",
        type=Path,
        default=Path(os.getenv("INITIAL_ADMIN_PASSWORD_FILE", str(DEFAULT_PASSWORD_FILE))),
        help="Protected password file path; plaintext password arguments are intentionally absent",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting when a non-local password file is absent",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Initial identity bootstrap does not construct or contact object storage.
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        repository = IdentityRepository(database)
        service = AuthService(
            repository,
            AuditService(
                AuditRepository(database),
                max_chars=settings.execution.max_tool_response_chars,
            ),
            settings.identity,
        )
        if repository.admin_count() > 0:
            user = None
        else:
            password = resolve_initial_admin_password(
                environment=settings.environment,
                password_file=args.password_file,
                non_interactive=bool(args.non_interactive),
            )
            user = service.bootstrap_admin(
                username=DEFAULT_USERNAME,
                display_name=DEFAULT_DISPLAY_NAME,
                password=password,
            )
    except InitialAdminBootstrapError as exc:
        print(f"INITIAL_ADMIN_BOOTSTRAP_FAILED: {exc}")
        return 1
    except Exception:
        print("INITIAL_ADMIN_BOOTSTRAP_FAILED: schema, database, or identity bootstrap rejected")
        return 1
    finally:
        database.close()
    if user is None:
        print("INITIAL_ADMIN_BOOTSTRAP_SUCCEEDED: status=existing_admin_preserved")
    else:
        print(f"INITIAL_ADMIN_BOOTSTRAP_SUCCEEDED: status=created username={user['username']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
