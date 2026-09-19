"""导入后的来源确认；显式确认与提交才写入，不调用 ONES 或自动发布。"""

import argparse
import json

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository, ConfigurationRepository
from app.modules.knowledge.application.source_service import SourceBindingService
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, checked_identifier
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.ones_verifier import OnesSourceVerifier
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import AppError
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="确认已导入批次的 ONES 实例和 Team；不需要证明摘要或 Job"
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--actor-id", required=True, help="承担此次导入来源确认的有效平台管理员 ID")
    parser.add_argument("--instance-code", required=True)
    parser.add_argument("--team-id", required=True, help="原生 Team ID，不是项目名")
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument(
        "--confirm-source", action="store_true", help="明确确认整个批次来源属于此实例与 Team"
    )
    parser.add_argument(
        "--commit", action="store_true", help="提交来源确认；替换会撤销旧绑定，不修改文本或向量"
    )
    args = parser.parse_args(argv)
    database = None
    try:
        for value in (args.source_id, args.actor_id, args.instance_code, args.team_id):
            checked_identifier(value)
        if args.expected_revision < 0 or (args.commit and not args.confirm_source):
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        settings = load_settings()
        database = Database(settings.database_dsn)
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        audit = AuditService(AuditRepository(database))
        permissions = PermissionService(
            ConfigurationRepository(database),
            authorization_evaluator=AuthorizationEvaluator(IdentityRepository(database)),
        )
        # 固定目标只取部署配置；此 CLI 不创建 Principal、不读取 ONES 凭据。
        target = OnesSourceVerifier(
            database,
            None,
            instance_code=settings.ones_identity.instance_code,
            provider_origin=settings.ones_mcp.provider_base_url,
        )
        service = SourceBindingService(GovernanceStore(database), permissions, audit, target)
        service.require_admin(args.actor_id)
        if args.instance_code != target.instance_code:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        if service.store.latest_source_revision(args.source_id) != args.expected_revision:
            raise KnowledgeGovernanceError("knowledge_revision_conflict")
        items = service.store.source_items(args.source_id)
        result = {"event": "source_preflight_passed", "document_count": len(items)}
        if args.commit:
            binding = service.confirm_import(
                actor_id=args.actor_id,
                source_id=args.source_id,
                instance_code=args.instance_code,
                team_id=args.team_id,
                expected_revision=args.expected_revision,
                confirmed=args.confirm_source,
            )
            result = {
                "event": "source_confirmed",
                "binding_id": binding["id"],
                "revision": binding["revision"],
                "state": binding["state"],
            }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except SchemaHeadError:
        code = "knowledge_schema_head_mismatch"
    except AppError as exc:
        code = exc.error_code or "knowledge_access_denied"
    except Exception:
        code = "knowledge_source_unavailable"
    finally:
        if database is not None:
            database.close()
    print(json.dumps({"event": "source_confirmation_failed", "error_code": code}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
