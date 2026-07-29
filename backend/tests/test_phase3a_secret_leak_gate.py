from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.shared.config import IdentitySettings
from backend.tests.helpers import test_settings as make_settings


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def test_phase3a_secret_material_is_confined_to_encrypted_store_and_runtime_memory(
    caplog: Any,
) -> None:
    settings = replace(
        make_settings(),
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )
    runtime = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: runtime)
    plaintext = "phase3a-plain-canary-7vQ9mL2x"

    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        created_response = client.post(
            "/api/platform/secrets",
            json={
                "code": "phase3a_gate_secret",
                "value": plaintext,
                "purpose": "phase3a-gate",
            },
            headers={"x-admin-user-id": "local-user"},
        )
        assert created_response.status_code == 200
        secret = created_response.json()["secret"]
        secret_ref = secret["secret_ref"]
        crypto = runtime.database.execute_one(
            """
            select ciphertext, nonce, key_id
            from platform_secret_version
            where secret_id = ?
            """,
            (secret["id"],),
        )
        assert crypto is not None

        runtime.create_agent_job_service.published_agent_runtime_enabled = False
        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="phase3a-secret-leak-gate",
                dingding_conversation_id="phase3a-gate-conversation",
                dingding_user_id="local-user",
                user_message="执行 Phase 3A 脱敏门禁",
                project_code="default",
                source_channel="debug_api",
                source_connector_id="",
                requester_id="user_local_admin",
            )
        )
        runtime.agent_repository.add_tool_call(
            job_id=job.id,
            tool_name="phase3a_secret_probe",
            request_payload={
                "password": plaintext,
                "secret_ref": secret_ref,
                "payload": json.dumps(
                    {
                        "nested": {
                            "api_key": plaintext,
                            "secret_ref": secret_ref,
                        }
                    }
                ),
            },
            response_summary={
                "token": crypto["ciphertext"],
                "payload": json.dumps(
                    {
                        "nonce": crypto["nonce"],
                        "result": "safe",
                    }
                ),
            },
            status="SUCCEEDED",
            duration_ms=1,
            risk_level="low",
        )
        runtime.audit_repository.record(
            event_type="phase3a_secret_probe",
            status="SUCCEEDED",
            summary=f"password={plaintext} Bearer {crypto['ciphertext']}",
            job_id=job.id,
            actor_id="local-user",
            payload_summary={
                "client_secret": plaintext,
                "ciphertext": crypto["ciphertext"],
                "secret_ref": secret_ref,
            },
        )

        headers = {"x-admin-user-id": "local-user"}
        api_responses = [
            created_response,
            client.get("/api/platform/secrets", headers=headers),
            client.get(
                "/api/platform/secrets/phase3a_gate_secret",
                headers=headers,
            ),
            client.get(
                "/api/platform/secrets/phase3a_gate_secret/usage",
                headers=headers,
            ),
            client.get(
                f"/api/agent/jobs/{job.id}",
                headers=headers,
            ),
            client.get(
                f"/api/agent/jobs/{job.id}/tool-calls",
                headers=headers,
            ),
        ]
        tool_calls = runtime.agent_repository.list_tool_calls(job.id)
        audit_rows = runtime.audit_repository.list_for_job(job.id)
        table_rows = {
            str(table["name"]): runtime.database.execute(
                f'select * from "{table["name"]}"'
            )
            for table in runtime.database.execute(
                """
                select name
                from sqlite_master
                where type = 'table' and name not like 'sqlite_%'
                order by name
                """
            )
        }

    assert all(response.status_code == 200 for response in api_responses)
    assert tool_calls[0]["request_payload"]["password"] == "[REDACTED]"
    assert tool_calls[0]["request_payload"]["secret_ref"] == secret_ref
    assert json.loads(tool_calls[0]["request_payload"]["payload"]) == {
        "nested": {
            "api_key": "[REDACTED]",
            "secret_ref": secret_ref,
        }
    }
    assert tool_calls[0]["response_summary"]["token"] == "[REDACTED]"
    assert json.loads(tool_calls[0]["response_summary"]["payload"]) == {
        "nonce": "[REDACTED]",
        "result": "safe",
    }
    assert audit_rows
    assert secret_ref in _serialized(tool_calls)
    assert secret_ref in _serialized(audit_rows)

    forbidden_values = (
        plaintext,
        str(crypto["ciphertext"]),
        str(crypto["nonce"]),
        str(crypto["key_id"]),
    )
    public_surfaces = "\n".join(
        [
            *(response.text for response in api_responses),
            _serialized(tool_calls),
            _serialized(audit_rows),
            caplog.text,
        ]
    )
    for forbidden in forbidden_values:
        assert forbidden not in public_surfaces

    for table_name, rows in table_rows.items():
        serialized = _serialized(rows)
        assert plaintext not in serialized
        if table_name == "platform_secret_version":
            continue
        for forbidden in forbidden_values[1:]:
            assert forbidden not in serialized

    frontend_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPOSITORY_ROOT / "frontend" / "src").rglob("*"))
        if path.suffix in {".ts", ".tsx"}
    )
    for forbidden_identifier in (
        "APP_CONFIG_MASTER_KEY",
        "ciphertext",
        "secret_value",
    ):
        assert forbidden_identifier not in frontend_sources
