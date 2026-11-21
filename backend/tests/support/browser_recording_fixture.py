"""File Service and controlled recording queries for the extension's Chrome regression."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import threading
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from uuid import uuid4

import boto3
import uvicorn
from starlette.applications import Starlette

from app.modules.channel.browser.tools import RecordingTools
from app.modules.file_workspace.storage import FileObjectStorageSettings, MinioFileObjectStorage
from app.modules.identity.api.service_principal_controller import build_service_principal_router
from app.modules.identity.application.principal_jwt import PrincipalJwks
from app.modules.identity.application.service_principal import (
    RECORDING_TOOL_PARTY,
    REQUIRED_SERVICE_PRINCIPAL_ROLES,
    ServicePrincipalTokenIssuer,
)
from backend.tests.test_service_principal_identity import _signing_key
from services.file_service.auth import FileWorkerPrincipalVerifier
from services.file_service.recordings import RecordingFiles


def isolated_storage(stack: ExitStack):
    name = "ea-extension-test-" + uuid4().hex
    # Synthetic credentials passed to Docker by name. The data volume lives in memory.
    env = {
        **os.environ,
        "MINIO_ROOT_USER": "synthetic-browser",
        "MINIO_ROOT_PASSWORD": secrets.token_urlsafe(40),
    }

    def docker(*args):
        return subprocess.check_output(["docker", *args], env=env, text=True).strip()

    docker(
        "run",
        "--pull=never",
        "--rm",
        "-d",
        "--name",
        name,
        "-p",
        "127.0.0.1::9000",
        "--tmpfs",
        "/data",
        "-e",
        "MINIO_ROOT_USER",
        "-e",
        "MINIO_ROOT_PASSWORD",
        "minio/minio:RELEASE.2025-04-22T22-12-26Z",
        "server",
        "/data",
    )
    stack.callback(docker, "stop", "--time", "1", name)
    port = int(docker("port", name, "9000/tcp").split(":")[-1])
    endpoint = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            with urlopen(endpoint + "/minio/health/ready", timeout=1) as reply:
                if reply.status == 200:
                    break
        except OSError:
            time.sleep(0.1)
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id=env["MINIO_ROOT_USER"],
        aws_secret_access_key=env["MINIO_ROOT_PASSWORD"],
    )
    client.create_bucket(Bucket="recording-test")
    cfg = FileObjectStorageSettings(
        endpoint_url=endpoint,
        bucket="recording-test",
        region="us-east-1",
        secure=False,
        access_key_ref="secret://platform/synthetic-access",
        secret_key_ref="secret://platform/synthetic-secret",
    )
    return MinioFileObjectStorage(
        cfg,
        lambda ref: env[
            "MINIO_ROOT_USER"
            if ref == "secret://platform/synthetic-access"
            else "MINIO_ROOT_PASSWORD"
        ],
        client=client,
    )


def enable_recordings(stack: ExitStack, api, api_port: int):
    c = api.state.container
    storage = isolated_storage(stack)
    roles = {
        role: secrets.token_urlsafe(40)
        for role in (*REQUIRED_SERVICE_PRINCIPAL_ROLES, RECORDING_TOOL_PARTY)
    }
    issuer = ServicePrincipalTokenIssuer(
        signing_key=_signing_key(), bootstrap_credentials=roles, audit_service=c.audit_service
    )
    c.service_principal_token_issuer = issuer
    verifier = FileWorkerPrincipalVerifier(
        PrincipalJwks.from_dict(issuer.signing_key.public_jwks())
    )
    files = RecordingFiles(c, storage, verifier)
    sock = stack.enter_context(socket.socket())
    sock.bind(("127.0.0.1", 0))
    fs = uvicorn.Server(
        uvicorn.Config(Starlette(routes=files.routes()), log_level="error", access_log=False)
    )
    thread = threading.Thread(target=fs.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()

    def close():
        fs.should_exit = True
        thread.join(timeout=5)

    stack.callback(close)
    while not fs.started and thread.is_alive():
        time.sleep(0.02)
    if not fs.started:
        raise RuntimeError("Synthetic File Service failed to start")
    secret = Path(stack.enter_context(TemporaryDirectory())) / "synthetic-service-identity"
    secret.touch(mode=0o600, exist_ok=False)
    secret.write_text(roles[RECORDING_TOOL_PARTY])
    c.settings = replace(
        c.settings,
        file_service=replace(
            c.settings.file_service,
            internal_base_url=f"http://127.0.0.1:{sock.getsockname()[1]}",
            internal_allowed_hosts=("127.0.0.1",),
        ),
        service_principal=replace(
            c.settings.service_principal,
            identity_base_url=f"http://127.0.0.1:{api_port}",
            identity_allowed_hosts=("127.0.0.1",),
            recording_tool_bootstrap_token_file=str(secret),
        ),
    )
    api.include_router(build_service_principal_router())
    c.tool_service.recording_tools = RecordingTools(c)
    return files


def controlled_followup(c, number: int, evidence):
    jobs = c.database.execute("""select j.id,j.session_id from agent_job j join browser_message_receipt b on j.id=b.job_id
            join agent_message m on m.id=j.input_message_id order by m.sequence_no""")
    assert len(jobs) == number and len({j["session_id"] for j in jobs}) == 1
    job = c.agent_repository.get_job(jobs[-1]["id"])
    context = c.agent_executor.context_builder.build(job)
    assert not context.retrieved_context.get("file_manifest")
    c.database.execute("update agent_job set status='RUNNING' where id=?", (job.id,))
    if number == 2:
        result = c.tool_service.call_tool(
            job_id=job.id,
            user_id=job.internal_user_id,
            project_code=job.project_code,
            tool_name="get_recording_evidence",
            arguments={"evidence_id": evidence},
        )
        row = result.summary["row"]
        assert row["request_capture"] == "unavailable"
        assert {"path": "/body", "reason": "not_captured"} in row["request_details"]["omissions"]
        code = row["response_code"]
        assert code == "DEMO_REJECTED"
        answer = "保存请求的业务码是 **" + code + "**。"
    else:
        assert "DEMO_REJECTED" in context.conversation_summary
        answer = "上一轮确认保存请求返回业务失败。"
    with c.database.unit_of_work():
        c.session_repository.add_message(
            session_id=job.session_id, job_id=job.id, role="assistant", content=answer
        )
        c.database.execute(
            "update agent_job set status='SUCCEEDED',result=? where id=?", (answer, job.id)
        )
    return {
        "jobs": number,
        "indexed": c.database.execute_one("select count(*) as n from browser_recording_evidence")[
            "n"
        ],
        "published": c.database.execute_one(
            "select count(*) as n from browser_recording where state='ready'"
        )["n"],
    }


def controlled_capture(c):
    jobs = c.database.execute("""select j.id from agent_job j join browser_message_receipt b on b.job_id=j.id
        join agent_message m on m.id=j.input_message_id order by m.sequence_no""")
    assert len(jobs) == 4
    job = c.agent_repository.get_job(jobs[-1]["id"])
    c.database.execute("update agent_job set status='RUNNING' where id=?", (job.id,))

    def call(name, args):
        return c.tool_service.call_tool(
            job_id=job.id,
            user_id=job.internal_user_id,
            project_code=job.project_code,
            tool_name=name,
            arguments=args,
        ).summary

    hits = call(
        "search_recording", {"business_outcome": "failure", "path_template": "/synthetic-mes/save"}
    )["hits"]
    assert len(hits) == 1
    ref = hits[0]["evidence_id"]
    nearby = call("search_recording", {"related_to": ref})["hits"]
    if not nearby:
        when = hits[0]["offset_ms"]
        nearby = call(
            "search_recording",
            {
                "kind": "action",
                "action": "click",
                "from_ms": max(0, when - 1500),
                "to_ms": when + 1500,
            },
        )["hits"]
    assert any(
        row["evidence_id"]["kind"] == "action" and row.get("action") == "click" for row in nearby
    )
    row = call("get_recording_evidence", {"evidence_id": ref})["row"]
    assert row["response_code"] == "SYNTHETIC_LOT_MISSING"
    answer = "保存请求的业务码是 **" + row["response_code"] + "**。"
    with c.database.unit_of_work():
        c.session_repository.add_message(
            session_id=job.session_id, job_id=job.id, role="assistant", content=answer
        )
        c.database.execute(
            "update agent_job set status='SUCCEEDED',result=? where id=?", (answer, job.id)
        )
    return {"jobs": len(jobs), "saved": True}
