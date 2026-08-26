from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.business_application.domain.policies import (
    canonical_json,
    normalize_routing_key,
    publication_task_file_features,
    required_file_mcp_tools,
    reject_dangerous_content,
    snapshot_hash,
    validate_execution_policy,
    verify_publication_snapshot,
    validate_task_file_attachment_dependency,
    validate_task_file_features,
)
from app.modules.document_processing import DOCLING_LAYOUT_OCR_V2
from app.modules.job.domain.job_status import JobStatus
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError, ToolPolicyError
from app.shared.migrations import Migrator
from backend.tests.support.authorization import grant_test_application_access
from backend.tests.support.channels import ensure_active_dingtalk_test_enterprise
from backend.tests.test_unified_identity_rbac import (
    csrf_headers,
    login,
    unified_settings,
)


def control_plane_settings() -> object:
    settings = unified_settings()
    return replace(
        settings,
        feature_business_application_control_plane=True,
        document_processing_worker=replace(
            settings.document_processing_worker,
            layout_ocr_enabled=True,
        ),
    )


def draft_payload(*, route: str = "", mcp_tools: list[str] | None = None) -> dict[str, object]:
    triggers: list[dict[str, object]] = []
    deliveries: list[dict[str, object]] = []
    if route:
        route = route if ":" in route else f"bot:{route}"
        triggers.append(
            {
                "trigger_type": "dingtalk_private",
                "connector_id": "connector-dingtalk-stream-default",
                "routing_key": route,
                "actor_policy": "CURRENT_SENDER",
                "service_account_user_id": "",
                "enabled": True,
                "config": {
                    "conversation_type": "private",
                    "require_mention": False,
                    "webhook_definition_id": "",
                },
            }
        )
        deliveries.append(
            {
                "delivery_type": "reply_original",
                "connector_id": "connector-dingtalk-stream-default",
                "enabled": True,
                "config": {"target_reference": "", "reply_mode": "original"},
            }
        )
    return {
        "agent_publication_id": "agent_publication_default_v1",
        "workflow_publication_id": "",
        "session_policy": {
            "conversation_mode": "channel",
            "recent_message_limit": 20,
            "retention_days": 30,
            "continuous_conversation_enabled": False,
            "attachments_enabled": False,
        },
        "execution_policy": {
            "max_turns": 12,
            "timeout_seconds": 300,
            "max_tool_calls": 30,
        },
        "triggers": triggers,
        "deliveries": deliveries,
        "mcp_tools": mcp_tools or [],
    }


def enable_file_context_dependencies(container: object, payload: dict[str, object]) -> None:
    agent_row = container.database.execute_one(
        "select snapshot_json from agent_publication where id = ?",
        ("agent_publication_default_v1",),
    )
    assert agent_row is not None
    agent_snapshot = json.loads(str(agent_row["snapshot_json"]))
    agent_snapshot["runtime_kind"] = "python-v1"
    agent_snapshot["supported_runtime_protocol_versions"] = ["1.4"]
    container.database.execute(
        """
        update agent_publication
           set schema_version = 3, snapshot_json = ?, config_hash = ?
         where id = ?
        """,
        (
            json.dumps(agent_snapshot, ensure_ascii=False, sort_keys=True),
            snapshot_hash(agent_snapshot),
            "agent_publication_default_v1",
        ),
    )
    features = {
        "workspace_enabled": True,
        "file_mcp_enabled": True,
        "runtime_file_edit_enabled": True,
        "default_file_delivery_enabled": True,
    }
    payload["task_file_features"] = features
    session_policy = dict(payload["session_policy"])
    session_policy["attachments_enabled"] = True
    session_policy["continuous_conversation_enabled"] = True
    payload["session_policy"] = session_policy
    required_tools = sorted(required_file_mcp_tools(features))
    for selection_order, identifier in enumerate(required_tools, start=30):
        definition = MCP_TOOL_MANIFEST[identifier]
        container.database.execute(
            """
            insert into agent_publication_mcp_tool
              (agent_publication_id, server_code, tool_identifier, schema_hash,
               model_description, selection_order, created_at)
            values ('agent_publication_default_v1', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                definition.server_code,
                definition.identifier,
                definition.schema_hash,
                definition.description,
                selection_order,
            ),
        )
    payload["mcp_tools"] = required_tools


def create_draft_publish(
    container: object, code: str, *, route: str = ""
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code=code,
        name=f"{code} name",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=int(application["revision"]),
        payload=draft_payload(route=route),
    )
    validated = service.validate(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )
    assert validated["validation"] == {"valid": True, "errors": []}
    publication = service.publish(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )
    return application, revision, publication


def test_workspace_retention_is_frozen_in_revision_publication_hash_and_audit() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="workspace-retention-policy",
        name="Workspace Retention Policy",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    assert application["draft"]["task_workspace_retention_period"] == "WEEK"
    payload = draft_payload()
    payload["task_workspace_retention_period"] = "MONTH"
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="workspace-retention-policy",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    assert revision["task_workspace_retention_period"] == "MONTH"
    publication = service.publish(
        actor_id="user_local_admin",
        code="workspace-retention-policy",
        revision_id=str(revision["id"]),
    )
    assert publication["schema_version"] == 6
    assert publication["task_file_features"] == {
        "default_file_delivery_enabled": False,
        "file_mcp_enabled": False,
        "runtime_file_edit_enabled": False,
        "workspace_enabled": False,
    }
    assert publication["snapshot"]["task_workspace_retention_period"] == "MONTH"
    assert publication["task_workspace_retention_source"] == "publication_snapshot"
    assert snapshot_hash(publication["snapshot"]) == publication["config_hash"]

    payload["task_workspace_retention_period"] = "DAY"
    next_revision = service.save_draft(
        actor_id="user_local_admin",
        code="workspace-retention-policy",
        expected_revision=int(revision["revision"]),
        payload=payload,
    )
    assert next_revision["task_workspace_retention_period"] == "DAY"
    frozen = container.business_application_repository.get_publication(str(publication["id"]))
    assert frozen["task_workspace_retention_period"] == "MONTH"

    audit = container.database.execute_one(
        """
        select payload_summary from audit_event
         where event_type = 'business_application.published'
         order by created_at desc limit 1
        """
    )
    assert audit is not None
    audit_envelope = json.loads(str(audit["payload_summary"]))
    assert json.loads(str(audit_envelope["payload"]))["task_workspace_retention_period"] == "MONTH"


def test_task_file_feature_flags_are_strict_and_frozen() -> None:
    disabled, source = publication_task_file_features(
        {"schema_version": 6, "task_file_features": {}}
    )
    assert disabled == {
        "default_file_delivery_enabled": False,
        "file_mcp_enabled": False,
        "runtime_file_edit_enabled": False,
        "workspace_enabled": False,
    }
    assert source == "publication_snapshot"
    with pytest.raises(NonRetryableExecutionError):
        validate_task_file_features({"workspace_enabled": "true"})
    with pytest.raises(NonRetryableExecutionError):
        validate_task_file_features({"unknown_enabled": True})
    with pytest.raises(NonRetryableExecutionError):
        validate_task_file_features({"file_mcp_enabled": True})
    with pytest.raises(NonRetryableExecutionError) as dependency_error:
        validate_task_file_attachment_dependency(
            session_policy={"attachments_enabled": False},
            task_file_features={
                "workspace_enabled": True,
                "file_mcp_enabled": True,
                "runtime_file_edit_enabled": True,
                "default_file_delivery_enabled": True,
            },
        )
    assert dependency_error.value.field_errors == [
        {
            "field": "session_policy.attachments_enabled",
            "message": "启用任务工作区前必须允许消息附件",
        }
    ]
    with pytest.raises(NonRetryableExecutionError) as continuous_error:
        validate_task_file_attachment_dependency(
            session_policy={
                "attachments_enabled": True,
                "continuous_conversation_enabled": False,
            },
            task_file_features={
                "workspace_enabled": True,
                "file_mcp_enabled": True,
                "runtime_file_edit_enabled": True,
                "default_file_delivery_enabled": True,
            },
        )
    assert continuous_error.value.field_errors == [
        {
            "field": "session_policy.continuous_conversation_enabled",
            "message": "启用任务工作区前必须启用连续会话",
        }
    ]

    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="task-file-feature-flags",
        name="Task File Feature Flags",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    enable_file_context_dependencies(container, payload)
    payload["task_file_features"] = {
        "workspace_enabled": True,
        "file_mcp_enabled": True,
        "runtime_file_edit_enabled": True,
        "default_file_delivery_enabled": True,
    }
    payload["mcp_tools"] = []
    with pytest.raises(NonRetryableExecutionError) as missing_file_tools:
        service.save_draft(
            actor_id="user_local_admin",
            code="task-file-feature-flags",
            expected_revision=int(application["revision"]),
            payload=payload,
        )
    assert {error["field"] for error in missing_file_tools.value.field_errors} == {
        "mcp_tools",
    }

    required_tools = sorted(required_file_mcp_tools(payload["task_file_features"]))
    payload["mcp_tools"] = required_tools
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="task-file-feature-flags",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = service.publish(
        actor_id="user_local_admin",
        code="task-file-feature-flags",
        revision_id=str(revision["id"]),
    )
    payload["task_file_features"] = {
        "workspace_enabled": False,
        "file_mcp_enabled": False,
        "runtime_file_edit_enabled": False,
        "default_file_delivery_enabled": False,
    }
    service.save_draft(
        actor_id="user_local_admin",
        code="task-file-feature-flags",
        expected_revision=int(revision["revision"]),
        payload=payload,
    )

    frozen = container.business_application_repository.get_publication(str(publication["id"]))
    assert all(frozen["task_file_features"].values())
    assert frozen["task_file_features_source"] == "publication_snapshot"
    assert frozen["snapshot"]["task_file_features"] == frozen["task_file_features"]
    assert snapshot_hash(frozen["snapshot"]) == frozen["config_hash"]


def test_document_processing_profile_rejects_incomplete_file_context_dependencies() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="document-processing-dependencies",
        name="Document Processing Dependencies",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["document_processing_profile_code"] = "docling-layout-ocr-v2"

    with pytest.raises(NonRetryableExecutionError) as incomplete:
        service.save_draft(
            actor_id="user_local_admin",
            code="document-processing-dependencies",
            expected_revision=int(application["revision"]),
            payload=payload,
        )
    assert {item["field"] for item in incomplete.value.field_errors} == {
        "task_file_features.workspace_enabled",
        "task_file_features.file_mcp_enabled",
        "session_policy.attachments_enabled",
        "session_policy.continuous_conversation_enabled",
    }

    enable_file_context_dependencies(container, payload)
    payload["mcp_tools"] = []
    with pytest.raises(NonRetryableExecutionError) as missing_tools:
        service.save_draft(
            actor_id="user_local_admin",
            code="document-processing-dependencies",
            expected_revision=int(application["revision"]),
            payload=payload,
        )
    assert "mcp_tools" in {item["field"] for item in missing_tools.value.field_errors}


def test_document_processing_profile_is_strict_and_frozen() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="document-processing-profile",
        name="Document Processing Profile",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    assert application["draft"]["document_processing_profile_code"] == "NONE"
    assert application["draft"]["document_processing_status"] == "DISABLED"

    payload = draft_payload()
    payload["document_processing_profile_code"] = "docling-layout-ocr-v2"
    enable_file_context_dependencies(container, payload)
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="document-processing-profile",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    assert revision["document_processing_profile_code"] == "docling-layout-ocr-v2"

    publication = service.publish(
        actor_id="user_local_admin",
        code="document-processing-profile",
        revision_id=str(revision["id"]),
    )
    expected_profile = {
        "code": "docling-layout-ocr-v2",
        "version": "2",
        "hash": DOCLING_LAYOUT_OCR_V2.profile_hash,
    }
    assert publication["schema_version"] == 6
    assert publication["snapshot"]["document_processing_profile"] == expected_profile
    assert publication["document_processing_profile_code"] == "docling-layout-ocr-v2"
    assert publication["document_processing_profile_version"] == "2"
    assert publication["document_processing_profile_hash"] == DOCLING_LAYOUT_OCR_V2.profile_hash
    assert publication["document_processing_profile_source"] == "publication_snapshot"
    assert snapshot_hash(publication["snapshot"]) == publication["config_hash"]
    assert verify_publication_snapshot(
        publication["snapshot"],
        schema_version=6,
        expected_hash=publication["config_hash"],
    )

    payload["document_processing_profile_code"] = "NONE"
    next_revision = service.save_draft(
        actor_id="user_local_admin",
        code="document-processing-profile",
        expected_revision=int(revision["revision"]),
        payload=payload,
    )
    assert next_revision["document_processing_status"] == "DISABLED"
    frozen = container.business_application_repository.get_publication(str(publication["id"]))
    assert frozen["document_processing_profile_code"] == "docling-layout-ocr-v2"
    assert frozen["document_processing_profile_hash"] == DOCLING_LAYOUT_OCR_V2.profile_hash

    tampered = dict(publication["snapshot"])
    tampered["document_processing_profile"] = {
        **expected_profile,
        "hash": "0" * 64,
    }
    assert not verify_publication_snapshot(
        tampered,
        schema_version=6,
        expected_hash=snapshot_hash(tampered),
    )

    catalog = service.catalog(
        actor_id="user_local_admin",
        code="document-processing-profile",
    )
    assert [item["code"] for item in catalog["document_processing_profiles"]] == [
        "NONE",
        "docling-layout-ocr-v2",
    ]
    assert "request_options" not in catalog["document_processing_profiles"][1]
    layout_catalog = catalog["document_processing_profiles"][1]
    assert layout_catalog["hash"] == DOCLING_LAYOUT_OCR_V2.profile_hash
    assert layout_catalog["selectable"] is True
    assert layout_catalog["output_kinds"] == [
        "MARKDOWN",
        "DOCLING_JSON",
        "OCR_LAYOUT_JSON",
    ]
    assert layout_catalog["capabilities"] == {
        "office_embedded_image_ocr": True,
        "coordinates": "TOPLEFT_0_10000",
        "reading_order": True,
        "confidence_when_upstream_provided": True,
        "missing_confidence": "EXPLICIT_NULL",
        "bounded_geometric_relations": True,
        "picture_pixel_basis": "RAW_EMBEDDED_MEDIA_AFTER_EXIF",
        "office_display_transform_applied": False,
        "vlm": False,
        "visual_semantics": False,
    }


def test_historical_profile_hash_remains_manageable_but_cannot_be_activated() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="historical-document-profile",
        name="Historical Document Profile",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload["document_processing_profile_code"] = "docling-layout-ocr-v2"
    enable_file_context_dependencies(container, payload)
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="historical-document-profile",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = service.publish(
        actor_id="user_local_admin",
        code="historical-document-profile",
        revision_id=str(revision["id"]),
    )

    frozen = container.business_application_repository.get_publication(str(publication["id"]))
    historical_hash = "7" * 64
    historical_snapshot = dict(frozen["snapshot"])
    historical_snapshot["document_processing_profile"] = {
        **dict(historical_snapshot["document_processing_profile"]),
        "hash": historical_hash,
    }
    container.database.execute(
        """
        update business_application_publication
           set document_processing_profile_hash = ?, snapshot_json = ?, config_hash = ?
         where id = ?
        """,
        (
            historical_hash,
            canonical_json(historical_snapshot),
            snapshot_hash(historical_snapshot),
            str(publication["id"]),
        ),
    )

    app = create_app(control_plane_settings(), container_factory=lambda _: container)
    with TestClient(app) as client:
        login(client)
        response = client.get("/api/admin/business-applications/historical-document-profile")
        assert response.status_code == 200
        historical = response.json()["application"]["publications"][0]
        assert historical["document_processing_profile_hash"] == historical_hash
        assert historical["document_processing_status"] == "CONFIGURED_UNAVAILABLE"
        assert historical["document_processing_reason_code"] == "profile_version_unavailable"
        assert historical["runtime_status"] == "blocked"
        assert historical["reason_code"] == "publication_integrity_error"

        with pytest.raises(NonRetryableExecutionError) as blocked:
            service.activate(
                actor_id="user_local_admin",
                code="historical-document-profile",
                environment="local",
                publication_id=str(publication["id"]),
                expected_revision=0,
            )
        assert blocked.value.error_code == "document_profile_version_unavailable"

        next_revision = service.save_draft(
            actor_id="user_local_admin",
            code="historical-document-profile",
            expected_revision=int(revision["revision"]),
            payload=payload,
        )
        current_publication = service.publish(
            actor_id="user_local_admin",
            code="historical-document-profile",
            revision_id=str(next_revision["id"]),
        )
        assert current_publication["id"] != publication["id"]
        assert (
            current_publication["document_processing_profile_hash"]
            == DOCLING_LAYOUT_OCR_V2.profile_hash
        )


def test_document_processing_profile_http_contract_rejects_arbitrary_options() -> None:
    settings = control_plane_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    application = container.business_application_service.create(
        actor_id="user_local_admin",
        code="document-profile-http",
        name="Document Profile HTTP",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    payload.update(
        {
            "expected_revision": application["revision"],
            "document_processing_profile_code": "docling-layout-ocr-v2",
            "document_processing_options": {"url": "https://example.invalid"},
        }
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        csrf = login(client)
        response = client.put(
            "/api/admin/business-applications/document-profile-http/draft",
            json=payload,
            headers=csrf_headers(csrf),
        )

    assert response.status_code == 422


def test_layout_profile_publication_fails_closed_until_deployment_contract_is_ready() -> None:
    configured = control_plane_settings()
    settings = replace(
        configured,
        document_processing_worker=replace(
            configured.document_processing_worker,
            layout_ocr_enabled=False,
        ),
    )
    container = build_test_container(settings, migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="layout-profile-not-ready",
        name="Layout Profile Not Ready",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    enable_file_context_dependencies(container, payload)
    payload["document_processing_profile_code"] = "docling-layout-ocr-v2"
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="layout-profile-not-ready",
        expected_revision=int(application["revision"]),
        payload=payload,
    )

    with pytest.raises(NonRetryableExecutionError) as blocked:
        service.publish(
            actor_id="user_local_admin",
            code="layout-profile-not-ready",
            revision_id=str(revision["id"]),
        )

    assert "document_processing_profile_code" in {
        item["field"] for item in blocked.value.field_errors
    }


def test_migration_is_repeatable_and_constraints_are_enforced() -> None:
    db = Database("sqlite:///:memory:")
    migrator = Migrator(
        db,
        default_migrations_dir(),
        migrator_build="business-application-schema-test",
    )
    migrator.run()
    migrator.run()
    tables = {
        str(row["name"])
        for row in db.execute("select name from sqlite_master where type = 'table'")
    }
    assert {
        "business_application",
        "business_application_revision",
        "business_application_publication",
        "business_application_deployment",
        "business_application_active_route",
    } <= tables
    with pytest.raises(Exception):
        db.execute(
            """
            insert into business_application
              (id, code, name, project_code, status, revision,
               created_by, created_at, updated_at)
            values ('bad', 'bad', 'Bad', 'default', 'unknown', 1, 'actor', 'now', 'now')
            """
        )
    with pytest.raises(Exception):
        db.execute(
            """
            insert into business_application_revision
              (id, application_id, revision, created_by, created_at, updated_at)
            values ('orphan', 'missing', 1, 'actor', 'now', 'now')
            """
        )
    migration_names = [path.name for path in sorted(default_migrations_dir().glob("*.sql"))]
    assert migration_names == [
        "100_baseline_v1.sql",
        "101_expand_canonical_job_message.sql",
        "102_schema_consolidation_checkpoint.sql",
        "103_contract_retire_compatibility_shadows.sql",
        "104_add_identity_aware_ones_mcp.sql",
        "105_expand_unified_mcp_operation_audit.sql",
        "106_expand_agent_run_audit.sql",
        "107_expand_task_file_workspaces.sql",
        "108_stage_attachment_only_messages.sql",
        "109_allow_file_service_mcp_publications.sql",
        "110_expand_file_source_received_time.sql",
        "111_expand_text_file_format_policy.sql",
        "112_expand_resource_revision_scope_bindings.sql",
        "113_expand_document_file_processing.sql",
        "114_expand_execution_summary_protocol_v13.sql",
        "115_expand_file_turn_admission.sql",
        "116_expand_office_embedded_image_layout_ocr.sql",
        "117_expand_docling_layout_ocr_v2.sql",
        "118_expand_bounded_workspace_working_sets.sql",
        "119_contract_single_current_file_rule.sql",
        "120_expand_runtime_tool_contract_evidence.sql",
        "121_expand_docling_processing_concurrency.sql",
        "122_document_processing_concurrency_comments.sql",
    ]
    session_columns = {str(row["name"]) for row in db.execute("pragma table_info(agent_session)")}
    assert {
        "application_publication_id",
        "execution_scope_hash",
        "isolation_key_version",
        "history_read_only",
    } <= session_columns


def test_domain_policies_reject_unsafe_or_unknown_configuration() -> None:
    assert normalize_routing_key("  Default   Room ") == "default room"
    assert (
        validate_execution_policy({"max_turns": 2, "timeout_seconds": 30, "max_tool_calls": 4})[
            "max_turns"
        ]
        == 2
    )
    with pytest.raises(NonRetryableExecutionError):
        validate_execution_policy(
            {
                "max_turns": 2,
                "timeout_seconds": 30,
                "max_tool_calls": 4,
                "unknown": True,
            }
        )
    with pytest.raises(NonRetryableExecutionError) as unsafe:
        reject_dangerous_content({"password": "must-not-be-reflected"})
    assert "must-not-be-reflected" not in unsafe.value.safe_message
    left = {"b": 2, "a": {"z": None, "list": [2, 1]}}
    right = {"a": {"list": [2, 1], "z": None}, "b": 2}
    assert canonical_json(left) == canonical_json(right)
    assert snapshot_hash(left) == snapshot_hash(right)


@pytest.mark.parametrize("legacy_mode", ["actor", "application"])
def test_new_drafts_reject_legacy_shared_session_modes(legacy_mode: str) -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    application = container.business_application_service.create(
        actor_id="user_local_admin",
        code=f"reject-{legacy_mode}-session",
        name=f"reject {legacy_mode} session",
        description="legacy mode must stay history-only",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    session_policy = dict(payload["session_policy"])
    session_policy["conversation_mode"] = legacy_mode
    payload["session_policy"] = session_policy

    with pytest.raises(NonRetryableExecutionError) as rejected:
        container.business_application_service.save_draft(
            actor_id="user_local_admin",
            code=str(application["code"]),
            expected_revision=int(application["revision"]),
            payload=payload,
        )
    assert rejected.value.error_code == "validation_failed"
    assert rejected.value.field_errors == [
        {
            "field": "session_policy.conversation_mode",
            "message": "仅支持按渠道会话；旧按主体/按应用模式只可查看历史",
        }
    ]


def test_repository_is_append_only_and_enforces_revision_conflicts() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="revision-test",
        name="Revision Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    first = service.save_draft(
        actor_id="user_local_admin",
        code="revision-test",
        expected_revision=int(application["revision"]),
        payload=draft_payload(),
    )
    with pytest.raises(NonRetryableExecutionError) as conflict:
        service.save_draft(
            actor_id="user_local_admin",
            code="revision-test",
            expected_revision=int(application["revision"]),
            payload=draft_payload(),
        )
    assert conflict.value.error_code == "revision_conflict"
    assert (
        len(container.business_application_repository.list_revisions(str(application["id"]))) == 2
    )
    assert first["revision"] == 2

    ordered_payload = draft_payload(mcp_tools=["query_database", "get_schema_directory"])
    ordered_payload["triggers"] = [
        {
            "trigger_type": "dingtalk_private",
            "connector_id": "connector-dingtalk-stream-default",
            "routing_key": route,
            "actor_policy": "CURRENT_SENDER",
            "service_account_user_id": "",
            "enabled": True,
            "config": {
                "conversation_type": "private",
                "require_mention": False,
                "webhook_definition_id": "",
            },
        }
        for route in ("first-route", "second-route")
    ]
    ordered = service.save_draft(
        actor_id="user_local_admin",
        code="revision-test",
        expected_revision=int(first["revision"]),
        payload=ordered_payload,
    )
    assert [item["binding_order"] for item in ordered["triggers"]] == [0, 1]
    assert [item["routing_key"] for item in ordered["triggers"]] == [
        "first-route",
        "second-route",
    ]
    assert [item["tool_identifier"] for item in ordered["mcp_tools"]] == [
        "query_database",
        "get_schema_directory",
    ]


def test_publish_activate_resolve_rollback_and_deactivate_do_not_touch_data_plane() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    before = {
        "jobs": container.database.execute_one("select count(*) as count from agent_job")["count"],
        "sessions": container.database.execute_one("select count(*) as count from agent_session")[
            "count"
        ],
    }
    application, first_revision, first_publication = create_draft_publish(
        container, "lifecycle-test", route="room-a"
    )
    repeated_publication = container.business_application_service.publish(
        actor_id="user_local_admin",
        code="lifecycle-test",
        revision_id=str(first_revision["id"]),
    )
    assert repeated_publication["id"] == first_publication["id"]
    assert (
        len(container.business_application_repository.list_publications(str(application["id"])))
        == 1
    )
    first = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="local",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )
    resolved = container.business_application_resolver.resolve_trigger(
        "local",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        " BOT:ROOM-A ",
    )
    assert first["runtime_wired"] is True
    assert first["runtime_status"] == "wired"
    assert resolved["publication"]["id"] == first_publication["id"]

    latest = container.business_application_repository.get_by_code("lifecycle-test")
    second_revision = container.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="lifecycle-test",
        expected_revision=int(latest["revision"]),
        payload=draft_payload(route="room-a"),
    )
    second_publication = container.business_application_service.publish(
        actor_id="user_local_admin",
        code="lifecycle-test",
        revision_id=str(second_revision["id"]),
    )
    second = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="local",
        publication_id=str(second_publication["id"]),
        expected_revision=int(first["revision"]),
    )
    rolled_back = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="local",
        publication_id=str(first_publication["id"]),
        expected_revision=int(second["revision"]),
    )
    stopped = container.business_application_service.deactivate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="local",
        expected_revision=int(rolled_back["revision"]),
    )
    assert stopped["active"] is False
    with pytest.raises(NonRetryableExecutionError) as missing:
        container.business_application_resolver.resolve_active("lifecycle-test", "local")
    assert missing.value.error_code == "business_application_configuration_error"
    assert before == {
        "jobs": container.database.execute_one("select count(*) as count from agent_job")["count"],
        "sessions": container.database.execute_one("select count(*) as count from agent_session")[
            "count"
        ],
    }
    assert application["runtime_wired"] is False


def test_baseline_schema_contains_no_business_application_fixture_rows() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="business-application-baseline-test",
    ).run()

    assert database.execute_one("select count(*) as count from business_application") == {
        "count": 0
    }
    assert database.execute_one(
        "select count(*) as count from business_application_deployment"
    ) == {"count": 0}
    assert database.execute_one(
        "select count(*) as count from business_application_active_route"
    ) == {"count": 0}
    database.close()


def test_only_published_session_policy_is_visible_to_runtime_resolver() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="session-policy-test",
        name="Session Policy Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    first_payload = draft_payload(route="session-room")
    first_payload["session_policy"] = {
        "conversation_mode": "channel",
        "recent_message_limit": 20,
        "retention_days": 30,
        "continuous_conversation_enabled": True,
        "attachments_enabled": True,
    }
    first_revision = service.save_draft(
        actor_id="user_local_admin",
        code="session-policy-test",
        expected_revision=int(application["revision"]),
        payload=first_payload,
    )
    first_publication = service.publish(
        actor_id="user_local_admin",
        code="session-policy-test",
        revision_id=str(first_revision["id"]),
    )
    service.activate(
        actor_id="user_local_admin",
        code="session-policy-test",
        environment="local",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )

    current = container.business_application_resolver.resolve_trigger(
        "local",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        "bot:session-room",
    )
    policy = current["publication"]["snapshot"]["session_policy"]
    assert policy["continuous_conversation_enabled"] is True
    assert policy["attachments_enabled"] is True

    latest = container.business_application_repository.get_by_code("session-policy-test")
    service.save_draft(
        actor_id="user_local_admin",
        code="session-policy-test",
        expected_revision=int(latest["revision"]),
        payload=draft_payload(route="session-room"),
    )
    unchanged = container.business_application_resolver.resolve_trigger(
        "local",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        "bot:session-room",
    )
    assert unchanged["publication"]["id"] == first_publication["id"]
    assert (
        unchanged["publication"]["snapshot"]["session_policy"]["continuous_conversation_enabled"]
        is True
    )


def test_active_business_application_policy_controls_live_channel_sessions() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    ensure_active_dingtalk_test_enterprise(container)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="live-session-policy",
        name="Live Session Policy",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload(route="bot:test-robot-code")
    payload["session_policy"] = {
        "conversation_mode": "channel",
        "recent_message_limit": 20,
        "retention_days": 30,
        "continuous_conversation_enabled": True,
        "attachments_enabled": False,
    }
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="live-session-policy",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = service.publish(
        actor_id="user_local_admin",
        code="live-session-policy",
        revision_id=str(revision["id"]),
    )
    service.activate(
        actor_id="user_local_admin",
        code="live-session-policy",
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    grant_test_application_access(
        container,
        application_id=str(application["id"]),
        role_code="live-session-runtime-reader",
    )

    first = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-policy-runtime",
            "senderStaffId": "local-user",
            "senderCorpId": "corp-test-enterprise",
            "chatbotCorpId": "corp-test-enterprise",
            "msgId": "policy-message-1",
            "robotCode": "test-robot-code",
            "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession",
            "text": {"content": "first"},
        },
        correlation_id="policy-correlation-1",
    )
    second = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-policy-runtime",
            "senderStaffId": "local-user",
            "senderCorpId": "corp-test-enterprise",
            "chatbotCorpId": "corp-test-enterprise",
            "msgId": "policy-message-2",
            "robotCode": "test-robot-code",
            "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession",
            "text": {"content": "second"},
        },
        correlation_id="policy-correlation-2",
    )

    assert first.accepted is True
    assert second.accepted is True
    first_job = container.agent_repository.get_job(first.job_id)
    second_job = container.agent_repository.get_job(second.job_id)
    assert first_job.session_id == second_job.session_id
    assert first_job.agent_publication_id == "agent_publication_default_v1"


def test_resolver_fails_closed_for_lifecycle_schema_and_hash_errors() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    application, _revision, publication = create_draft_publish(container, "resolver-integrity-test")
    deployment = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="resolver-integrity-test",
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    assert deployment["active"] is True

    container.database.execute(
        """
        update business_application_publication
           set schema_version = 99
         where id = ?
        """,
        (publication["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as schema_error:
        container.business_application_resolver.resolve_active("resolver-integrity-test", "local")
    assert schema_error.value.error_code == "business_application_configuration_error"

    container.database.execute(
        """
        update business_application_publication
           set schema_version = 1, config_hash = 'tampered'
         where id = ?
        """,
        (publication["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as hash_error:
        container.business_application_resolver.resolve_active("resolver-integrity-test", "local")
    assert hash_error.value.error_code == "business_application_configuration_error"

    container.database.execute(
        "update business_application set status = 'disabled' where id = ?",
        (application["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as lifecycle_error:
        container.business_application_resolver.resolve_active("resolver-integrity-test", "local")
    assert lifecycle_error.value.error_code == "business_application_configuration_error"


def test_activation_route_projection_rejects_conflicting_application() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    _, _, first_publication = create_draft_publish(container, "route-owner-a", route="same-room")
    _, _, second_publication = create_draft_publish(container, "route-owner-b", route="same-room")
    container.business_application_service.activate(
        actor_id="user_local_admin",
        code="route-owner-a",
        environment="local",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )
    with pytest.raises(NonRetryableExecutionError) as conflict:
        container.business_application_service.activate(
            actor_id="user_local_admin",
            code="route-owner-b",
            environment="local",
            publication_id=str(second_publication["id"]),
            expected_revision=0,
        )
    assert conflict.value.error_code == "route_conflict"
    assert (
        container.business_application_repository.get_deployment(
            str(second_publication["application_id"]), "test"
        )
        is None
    )


def test_mcp_tool_catalog_lists_manifest_tools_and_enforces_agent_binding() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="mcp-tool-catalog-test",
        name="MCP Tool Catalog Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    container.database.execute(
        """
        update agent_publication_mcp_tool
           set model_description = 'Legacy English description.'
         where agent_publication_id = 'agent_publication_default_v1'
           and tool_identifier = 'query_database'
        """
    )
    container.database.execute(
        """
        insert into agent_publication_mcp_tool
          (agent_publication_id, server_code, tool_identifier, schema_hash,
           model_description, selection_order, created_at)
        values ('agent_publication_default_v1', 'tool-mcp', 'get_er_context',
                ?, 'Legacy retired tool.', 99, CURRENT_TIMESTAMP)
        """,
        ("1" * 64,),
    )

    catalog = service.catalog(
        actor_id="user_local_admin",
        code="mcp-tool-catalog-test",
    )
    catalog_agents = {(item["code"], item["runtime_kind"]) for item in catalog["agents"]}
    assert ("default-diagnostic-agent", "python-v1") in catalog_agents
    assert all(runtime_kind == "python-v1" for _, runtime_kind in catalog_agents)
    python_tools = {
        item["tool_identifier"]
        for item in catalog["mcp_tools_by_agent_publication"]["agent_publication_default_v1"]
    }
    assert {"get_schema_directory", "query_database"} <= python_tools
    assert "get_er_context" not in python_tools
    descriptions = {
        item["tool_identifier"]: item["description"]
        for item in catalog["mcp_tools_by_agent_publication"]["agent_publication_default_v1"]
    }
    assert descriptions["query_database"] == MCP_TOOL_MANIFEST["query_database"].description

    valid_revision = service.save_draft(
        actor_id="user_local_admin",
        code="mcp-tool-catalog-test",
        expected_revision=int(application["revision"]),
        payload=draft_payload(mcp_tools=["get_schema_directory"]),
    )
    validated = service.validate(
        actor_id="user_local_admin",
        code="mcp-tool-catalog-test",
        revision_id=str(valid_revision["id"]),
    )
    assert validated["validation"] == {"valid": True, "errors": []}

    with pytest.raises(NonRetryableExecutionError) as invalid:
        service.save_draft(
            actor_id="user_local_admin",
            code="mcp-tool-catalog-test",
            expected_revision=int(valid_revision["revision"]),
            payload=draft_payload(mcp_tools=["unbound_readonly"]),
        )
    assert invalid.value.field_errors == [
        {
            "field": "mcp_tools.0",
            "message": "所选 MCP Tool 不在 Agent 发布范围内或 Schema 已变化",
        }
    ]


def test_ones_tool_preserves_server_through_agent_application_and_job_snapshot() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    definition = MCP_TOOL_MANIFEST["ones_work_item_search"]
    container.database.execute(
        """
        insert into agent_publication_mcp_tool
          (agent_publication_id, server_code, tool_identifier, schema_hash,
           model_description, selection_order, created_at)
        values ('agent_publication_default_v1', ?, ?, ?, ?, 10, CURRENT_TIMESTAMP)
        """,
        (
            definition.server_code,
            definition.identifier,
            definition.schema_hash,
            definition.description,
        ),
    )
    existing = container.database.execute_one(
        """
        select server_code from agent_publication_mcp_tool
         where agent_publication_id = 'agent_publication_default_v1'
           and tool_identifier = 'get_schema_directory'
        """
    )
    assert existing == {"server_code": "tool-mcp"}

    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="ones-server-provenance-test",
        name="ONES server provenance",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    catalog = service.catalog(
        actor_id="user_local_admin",
        code="ones-server-provenance-test",
    )
    catalog_entry = next(
        item
        for item in catalog["mcp_tools_by_agent_publication"]["agent_publication_default_v1"]
        if item["tool_identifier"] == definition.identifier
    )
    assert catalog_entry["server_code"] == "ones-mcp"

    wrong_payload = draft_payload()
    wrong_payload["mcp_tools"] = [
        {"server_code": "tool-mcp", "tool_identifier": definition.identifier}
    ]
    with pytest.raises(NonRetryableExecutionError):
        service.save_draft(
            actor_id="user_local_admin",
            code="ones-server-provenance-test",
            expected_revision=int(application["revision"]),
            payload=wrong_payload,
        )

    payload = draft_payload()
    payload["mcp_tools"] = [{"server_code": "ones-mcp", "tool_identifier": definition.identifier}]
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="ones-server-provenance-test",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    revision_fact = container.database.execute_one(
        """
        select server_code, tool_identifier, schema_hash
          from business_application_revision_mcp_tool
         where application_revision_id = ?
        """,
        (revision["id"],),
    )
    assert revision_fact == {
        "server_code": "ones-mcp",
        "tool_identifier": definition.identifier,
        "schema_hash": definition.schema_hash,
    }
    publication = service.publish(
        actor_id="user_local_admin",
        code="ones-server-provenance-test",
        revision_id=str(revision["id"]),
    )
    publication_fact = container.database.execute_one(
        """
        select server_code, tool_identifier, schema_hash
          from business_application_publication_mcp_tool
         where application_publication_id = ?
        """,
        (publication["id"],),
    )
    assert publication_fact == revision_fact

    session = container.agent_repository.create_session(
        project_code="default",
        source_channel="debug_api",
        source_connector_id="connector-debug-api",
        external_conversation_id="ones-server-provenance",
        requester_id="user_local_admin",
        business_application_id=str(application["id"]),
        business_application_code=str(application["code"]),
        application_publication_id=str(publication["id"]),
        execution_scope_hash="ones-server-provenance",
    )
    job = container.agent_repository.create_job(
        session_id=session.id,
        idempotency_key="ones-server-provenance-job",
        project_code="default",
        source_channel="debug_api",
        source_connector_id="connector-debug-api",
        requester_id="user_local_admin",
        input_message="query ONES",
        max_retry_count=0,
        initial_status=JobStatus.RUNNING,
        internal_user_id="user_local_admin",
        agent_publication_id="agent_publication_default_v1",
        business_application_id=str(application["id"]),
        business_application_code=str(application["code"]),
        business_application_publication_id=str(publication["id"]),
        execution_policy={
            "schema_version": 1,
            "requested": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "effective": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "sources": {"source_kind": "runtime_default"},
        },
    )
    frozen = container.mcp_tool_snapshot_service.freeze(
        job_id=job.id,
        requester_id="user_local_admin",
        application_id=str(application["id"]),
        application_publication_id=str(publication["id"]),
        application_config_hash=str(publication["config_hash"]),
        agent_publication_id="agent_publication_default_v1",
        routing_context={},
        business_authorization={},
        runtime_authorization={
            "tool_grants": [
                {
                    "server_code": "ones-mcp",
                    "tool_identifier": definition.identifier,
                    "source_role_codes": ["ones-reader"],
                }
            ]
        },
    )
    assert frozen["snapshot"]["tools"] == [
        {
            "server_code": "ones-mcp",
            "tool_identifier": definition.identifier,
            "schema_hash": definition.schema_hash,
            "resource_kind": "",
        }
    ]

    tampered = dict(frozen["snapshot"])
    tampered["tools"] = [{**frozen["snapshot"]["tools"][0], "server_code": "tool-mcp"}]
    container.database.execute(
        """
        update agent_job_mcp_tool_snapshot
           set snapshot_json = ?, snapshot_hash = ?
         where job_id = ?
        """,
        (
            JobMcpToolSnapshotService._json_text(tampered),
            JobMcpToolSnapshotService._hash(tampered),
            job.id,
        ),
    )
    with pytest.raises(ToolPolicyError) as drift:
        container.mcp_tool_snapshot_service.verify(job.id)
    assert drift.value.error_code == "mcp_tool_schema_drift"


def test_catalog_http_contract_exposes_runtime_compatibility_only_for_agents() -> None:
    settings = control_plane_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.business_application_service.create(
        actor_id="user_local_admin",
        code="catalog-runtime-contract",
        name="Catalog Runtime Contract",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        login(client)
        response = client.get("/api/admin/business-applications/catalog-runtime-contract/catalog")

    assert response.status_code == 200
    catalog = response.json()
    assert {item["runtime_kind"] for item in catalog["agents"]} == {"python-v1"}
    assert all(item["runtime_protocol_versions"] for item in catalog["agents"])
    assert catalog["connectors"]
    assert catalog["mcp_tools_by_agent_publication"]
    assert all("runtime_kind" not in item for item in catalog["connectors"])
    assert all("runtime_protocol_versions" not in item for item in catalog["connectors"])
    assert all(
        "runtime_kind" not in item
        for tools in catalog["mcp_tools_by_agent_publication"].values()
        for item in tools
    )


def test_application_agent_reference_fails_closed_on_runtime_or_hash_tampering() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="agent-runtime-integrity-test",
        name="Agent Runtime Integrity Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    catalog = service.catalog(
        actor_id="user_local_admin",
        code="agent-runtime-integrity-test",
    )
    python = next(item for item in catalog["agents"] if item["runtime_kind"] == "python-v1")
    payload = draft_payload()
    payload["agent_publication_id"] = python["id"]
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="agent-runtime-integrity-test",
        expected_revision=int(application["revision"]),
        payload=payload,
    )

    container.database.execute(
        "update agent_publication set config_hash = 'tampered' where id = ?",
        (python["id"],),
    )
    validated = service.validate(
        actor_id="user_local_admin",
        code="agent-runtime-integrity-test",
        revision_id=str(revision["id"]),
    )

    assert validated["validation"]["valid"] is False
    assert validated["validation"]["errors"] == [
        {"field": "agent_publication_id", "message": "组件不可用"}
    ]


def test_admin_api_enforces_feature_auth_csrf_unknown_fields_and_conflict() -> None:
    enabled = control_plane_settings()
    container = build_test_container(enabled, migrate=True, seed=True)
    app = create_app(enabled, container_factory=lambda _: container)
    with TestClient(app) as client:
        assert client.get("/api/admin/business-applications").status_code == 401
        csrf = login(client)
        no_csrf = client.post(
            "/api/admin/business-applications",
            json={
                "code": "api-test",
                "name": "API Test",
                "project_code": "default",
            },
        )
        unknown = client.post(
            "/api/admin/business-applications",
            headers=csrf_headers(csrf),
            json={
                "code": "api-test",
                "name": "API Test",
                "project_code": "default",
                "database_url": "not-accepted",
            },
        )
        created = client.post(
            "/api/admin/business-applications",
            headers=csrf_headers(csrf),
            json={
                "code": "api-test",
                "name": "API Test",
                "project_code": "default",
            },
        )
        update_payload = {
            "expected_revision": 1,
            "name": "Updated",
            "description": "",
            "project_code": "default",
            "owner_user_id": "",
            "status": "enabled",
        }
        updated = client.put(
            "/api/admin/business-applications/api-test",
            headers=csrf_headers(csrf),
            json=update_payload,
        )
        stale = client.put(
            "/api/admin/business-applications/api-test",
            headers=csrf_headers(csrf),
            json=update_payload,
        )
        listed = client.get("/api/admin/business-applications")
    assert no_csrf.status_code == 403
    assert unknown.status_code == 422
    assert created.status_code == 200, created.text
    assert updated.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_revision"] == 2
    assert listed.status_code == 200
    assert listed.json()["items"][0]["code"] == "api-test"
    assert "password" not in str(listed.json()).lower()

    disabled = replace(enabled, feature_business_application_control_plane=False)
    disabled_container = build_test_container(disabled, migrate=True, seed=True)
    disabled_app = create_app(disabled, container_factory=lambda _: disabled_container)
    with TestClient(disabled_app) as client:
        login(client)
        response = client.get("/api/admin/business-applications")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "business_application_control_plane_disabled"


def test_admin_api_prevents_enumeration_and_denies_unprivileged_writes() -> None:
    settings = control_plane_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.business_application_service.create(
        actor_id="user_local_admin",
        code="private-application",
        name="Private Application",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    container.identity_admin_service.create_user(
        actor_id="user_local_admin",
        username="business-app-restricted",
        display_name="Business App Restricted",
        email="",
        password="restricted-local-test-password",
    )
    app = create_app(settings, container_factory=lambda _: container)
    with TestClient(app) as client:
        csrf = login(
            client,
            username="business-app-restricted",
            password="restricted-local-test-password",
        )
        listed = client.get("/api/admin/business-applications")
        hidden = client.get("/api/admin/business-applications/private-application")
        forbidden = client.post(
            "/api/admin/business-applications",
            headers=csrf_headers(csrf),
            json={
                "code": "forbidden-create",
                "name": "Forbidden Create",
                "project_code": "default",
            },
        )
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert hidden.status_code == 404
    assert forbidden.status_code == 403
    assert "private-application" not in str(hidden.json())


def test_seed_cli_exists_and_production_migration_does_not_activate() -> None:
    assert Path("backend/app/cli/seed_default_business_application.py").exists()
    db = Database("sqlite:///:memory:")
    db.run_migrations(default_migrations_dir())
    assert (
        db.execute_one("select count(*) as count from business_application_deployment")["count"]
        == 0
    )


def test_local_seed_and_default_application_cli_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli.seed_default_business_application import main

    database_path = tmp_path / "control-plane-seed.db"
    master_key_path = tmp_path / "app-config-master-key"
    encoded_key = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
    master_key_path.write_text(
        f"EA_MASTER_KEY_V1:{encoded_key}\n",
        encoding="utf-8",
    )
    master_key_path.chmod(0o400)
    monkeypatch.setenv("DATABASE_DSN", f"sqlite:///{database_path}")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_CONFIG_MASTER_KEY_FILE", str(master_key_path))
    monkeypatch.setenv("FEATURE_UNIFIED_IDENTITY", "true")
    monkeypatch.setenv("FEATURE_WEB_ADMIN", "true")
    monkeypatch.setenv("FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE", "true")
    migration_database = Database(f"sqlite:///{database_path}")
    try:
        Migrator(
            migration_database,
            default_migrations_dir(),
            migrator_build="test-cli",
        ).run()
    finally:
        migration_database.close()
    assert main() == 0
    assert main() == 0
    db = Database(f"sqlite:///{database_path}")
    try:
        assert (
            db.execute_one(
                """
            select count(*) as count from business_application
             where code = 'default-diagnostic-application'
            """
            )["count"]
            == 1
        )
        assert (
            db.execute_one("select count(*) as count from business_application_deployment")["count"]
            == 0
        )
    finally:
        db.close()
