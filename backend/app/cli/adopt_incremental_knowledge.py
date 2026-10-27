"""显式验证/转换当前知识索引；不创建向量、不开启采集。"""

import argparse
import json

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository, ConfigurationRepository
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, checked_identifier
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.incremental_adoption import IncrementalAdoption
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="一次性将当前受管知识索引转换为固定集合增量模式")
    parser.add_argument("--binding-code", required=True)
    parser.add_argument("--index-code", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    database = qdrant = None
    try:
        for value in (args.binding_code, args.index_code, args.actor_id):
            checked_identifier(value)
        database = Database(load_settings().database_dsn)
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        administration = KnowledgeAdministration(
            GovernanceStore(database),
            PermissionService(
                ConfigurationRepository(database),
                authorization_evaluator=AuthorizationEvaluator(IdentityRepository(database)),
            ),
            AuditService(AuditRepository(database)),
        )
        qdrant = QdrantClient()
        result = IncrementalAdoption(database, administration, qdrant).run(
            stable_id("sync-binding", args.binding_code),
            args.index_code,
            actor_id=args.actor_id,
            commit=args.commit,
        )
        print(json.dumps({"event": "knowledge_incremental_adoption", **result}))
        return 0
    except SchemaHeadError:
        code = "knowledge_schema_head_mismatch"
    except (VectorError, ExportValidationError) as exc:
        code = exc.code
    except KnowledgeGovernanceError as exc:
        code = exc.error_code
    except AppError as exc:
        code = exc.error_code or "knowledge_access_denied"
    except Exception:
        code = "knowledge_incremental_adoption_failed"
    finally:
        if qdrant is not None:
            qdrant.http.close()
        if database is not None:
            database.close()
    print(json.dumps({"event": "knowledge_incremental_adoption_failed", "error_code": code}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
