from __future__ import annotations

import argparse
import getpass

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application import AuthService
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the first local platform administrator"
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        database.run_migrations(default_migrations_dir())
        repository = IdentityRepository(database)
        service = AuthService(
            repository,
            AuditService(
                AuditRepository(database),
                max_chars=settings.execution.max_tool_response_chars,
            ),
            settings.identity,
        )
        user = service.bootstrap_admin(
            username=args.username,
            display_name=args.display_name,
            password=password,
        )
        print(f"Created administrator {user['username']} ({user['id']})")
    finally:
        database.close()


if __name__ == "__main__":
    main()
