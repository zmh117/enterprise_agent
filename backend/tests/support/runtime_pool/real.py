"""Explicitly authorized, bounded real Provider acceptance using synthetic jobs only.

Only the selected encrypted credential record crosses a private in-memory pipe into
an ephemeral test database. Plaintext credentials are never exported or logged;
the production Runtime decrypts normally using the original read-only master file.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen
import uuid

from backend.tests.support.runtime_pool.run import (
    compose,
    container,
    create_job,
    initialize,
    journal,
    terminal,
    wait_for,
)


def source_query(sql: str) -> Any:
    command = [
        "docker",
        "exec",
        "-e",
        "PGOPTIONS=-c default_transaction_read_only=on",
        "enterprise_agent-postgres-1",
        "psql",
        "-U",
        "enterprise_agent",
        "-d",
        "enterprise_agent",
        "-XAt",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Read-only source metadata query failed")
    return json.loads(result.stdout)


def binding_snapshot() -> dict[str, Any]:
    return source_query("""
    select json_build_object('connection_id',c.id,'revision_id',r.id,'config_hash',r.config_hash,
      'model',r.config_json::jsonb->>'model','credential_id',s.id,'active_version',s.active_version,
      'credential_updated_at',s.updated_at,'encrypted_record_digest',md5(v.ciphertext || v.nonce))
    from model_connection c join model_connection_revision r on r.id=c.current_revision_id
    join platform_secret s on s.id=r.api_key_secret_id
    join platform_secret_version v on v.secret_id=s.id and v.version=s.active_version
    where c.code='default-deepseek-anthropic' and c.status='ready' and r.status='ready'
    """)


def initialize_real(master_file: Path) -> Path:
    assert master_file.is_file()
    before = binding_snapshot()
    root = initialize()
    # Never write this payload to a file, stdout or an exception message.
    bundle = source_query("""
    select json_build_object('connection',row_to_json(c),'revision',row_to_json(r),
      'secret',row_to_json(s),'version',row_to_json(v))
    from model_connection c join model_connection_revision r on r.id=c.current_revision_id
    join platform_secret s on s.id=r.api_key_secret_id
    join platform_secret_version v on v.secret_id=s.id and v.version=s.active_version
    where c.code='default-deepseek-anthropic' and c.status='ready' and r.status='ready'
    """)
    config = json.loads(bundle["revision"]["config_json"])
    host = urlsplit(config["base_url"]).hostname
    state = json.loads((root / "state.json").read_text())
    state.update(
        real_provider=True,
        provider_hosts=[host],
        managed_binding_before=before,
        bounded_jobs=18,
        bounded_timeout_seconds=120,
    )
    (root / "state.json").write_text(json.dumps(state))
    runtime = container(root)
    with runtime.database.unit_of_work():
        runtime.database.execute("delete from model_connection_revision")
        runtime.database.execute("delete from model_connection")
        for table, field in [
            ("platform_secret", "secret"),
            ("platform_secret_version", "version"),
            ("model_connection", "connection"),
            ("model_connection_revision", "revision"),
        ]:
            row = bundle[field]
            columns = list(row)
            runtime.database.execute(
                f"insert into {table} ({','.join(columns)}) values ({','.join('?' for _ in columns)})",
                tuple(row.values()),
            )
    del bundle
    runtime.database.close()
    services = {}
    for node in "abc":
        services["runtime-" + node] = {
            "command": [
                "python",
                "-m",
                "uvicorn",
                "real_node:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8091",
                "--workers",
                "1",
            ],
            "environment": {
                "AGENT_RUNTIME_TEST_PROVIDER_MODE": "disabled",
                "MODEL_PROVIDER_HOST_ALLOWLIST": host,
                "APP_CONFIG_MASTER_KEY_FILE": "/run/secrets/managed-master",
                "RPOOL_MODEL_REVISION": before["revision_id"],
                "AGENT_MAX_TOOL_CALLS": "4",
            },
            "volumes": [
                str(Path(__file__).with_name("real_node.py").resolve())
                + ":/acceptance/real_node.py:ro"
            ],
            "secrets": [{"source": "managed-master", "target": "managed-master"}],
        }
    for service in ("worker", "dispatcher"):
        services[service] = {
            "environment": {
                "MODEL_PROVIDER_HOST_ALLOWLIST": host,
                "AGENT_MAX_RETRY_COUNT": "0",
                "AGENT_MAX_TOOL_CALLS": "4",
            }
        }
    (root / "compose.override.yml").write_text(
        json.dumps(
            {
                "services": services,
                "secrets": {"managed-master": {"file": str(master_file.resolve())}},
            }
        )
    )
    start_real(root)
    return root


def start_real(root: Path) -> None:
    state = json.loads((root / "state.json").read_text())
    before = state["managed_binding_before"]
    compose(root, "up", "-d", "runtime-a", "runtime-b", "runtime-c")
    state["nodes"] = {
        node: "http://" + compose(root, "port", "runtime-" + node, "8091") for node in "abc"
    }
    (root / "state.json").write_text(json.dumps(state))
    for base in state["nodes"].values():

        def ready() -> bool:
            try:
                with urlopen(base + "/ready", timeout=3) as response:
                    return response.status == 200
            except OSError:
                return False

        wait_for(ready)
    runtime = container(root)
    from app.acceptance.python_runtime_composition import (
        _activate_debug_application,
        _ensure_debug_connector,
    )

    code = "default-diagnostic-agent"
    detail = runtime.agent_config_service.get(code)
    draft = dict(detail["draft"]["config"])
    draft.pop("tools", None)
    draft.update(
        model_policy={
            "runtime": "claude_agent_sdk",
            "model": before["model"],
            "model_connection_revision_id": before["revision_id"],
        },
        execution={"max_turns": 4, "timeout_seconds": 120},
        mcp_tool_ids=[],
        skills=[],
        channels={"ingress": [], "delivery": []},
    )
    revision = runtime.agent_config_service.save_draft(
        actor_id="user_local_admin",
        agent_code=code,
        expected_revision=detail["draft"]["revision"],
        config=draft,
    )
    publication = runtime.agent_config_service.publish(
        actor_id="user_local_admin", agent_code=code, revision_id=revision["id"]
    )
    _ensure_debug_connector(runtime)
    state["publication"] = publication["id"]
    state["selection"] = _activate_debug_application(
        runtime, "user_local_admin", agent_publication_id=publication["id"]
    )
    (root / "state.json").write_text(json.dumps(state))
    runtime.database.close()
    assert binding_snapshot() == before
    compose(root, "up", "-d", "worker", "dispatcher")
    print(
        json.dumps(
            {
                "root": str(root),
                "model": before["model"],
                "provider_host": state["provider_hosts"][0],
                "nodes": 3,
                "max_jobs": 18,
            }
        )
    )


def synthetic_prompt(kind: str, marker: str) -> str:
    if kind == "isolation":
        return f"独立会话合成验收任务。你的唯一标记是 {marker}。请给出5条虚构设备检查说明，最后一行只输出本会话的标记，不要输出其他标记，不调用工具。"
    if kind in {"cancel", "takeover"}:
        return f"合成生成测试，标记 {marker}。请从 1 到 60 连续列出编号，每行解释一个虚构工厂检查项（约20个汉字），不要调用工具。末尾再次输出标记。"
    return f"合成数据处理测试。标记 {marker}。请输出20行虚构设备检查清单，每行包含编号、固定状态OK和约20个汉字的检查描述。最后单独输出标记。不要调用工具。"


def checked_job(runtime: Any, root: Path, kind: str) -> Any:
    count = runtime.database.execute_one("select count(*) as n from agent_job")["n"]
    assert count < 18, "Bounded acceptance job budget exhausted"
    marker = "RPOOL_SYNTH_" + uuid.uuid4().hex[:12]
    job = create_job(runtime, root, synthetic_prompt(kind, marker))
    return job, marker


def facts(runtime: Any, root: Path, jobs: list[tuple[Any, str]]) -> list[dict[str, Any]]:
    events = journal(root)
    rows = []
    for original, marker in jobs:
        job = runtime.agent_repository.get_job(original.id)
        invocation = runtime.database.execute_one(
            "select * from agent_runtime_invocation where job_id = ?", (job.id,)
        )
        selected = [e for e in events if e["invocation_id"].split(".attempt-")[0] == job.id]
        starts = [e for e in selected if e["kind"] == "sdk_query_start"]
        finished = [e for e in selected if e["kind"] == "sdk_finished"]
        ends = [e for e in selected if e["kind"] == "sdk_query_end"]
        result = job.result or ""
        snapshot = runtime.database.execute_one(
            "select request_json from agent_runtime_request_snapshot where invocation_id = ?",
            (job.id + ".attempt-0",),
        )
        context_markers = (
            set(re.findall(r"RPOOL_SYNTH_[a-f0-9]+", snapshot["request_json"]))
            if snapshot
            else set()
        )
        row = {
            "job_id": job.id,
            "session_id": job.session_id,
            "status": job.status.value,
            "error_code": job.last_error_code,
            "retry_count": job.retry_count,
            "worker_claim_version": job.worker_claim_version,
            "expected_marker_present": marker in result,
            "foreign_marker_present": any(other in result for _, other in jobs if other != marker),
            "frozen_context_isolated": context_markers == {marker},
            "result_sha256": hashlib.sha256(result.encode()).hexdigest(),
            "sdk_starts": len(starts),
            "sdk_start": starts[0]["time"] if starts else None,
            "sdk_end": ends[-1]["time"] if ends else None,
            "runtime": None
            if not invocation
            else {
                key: invocation[key]
                for key in (
                    "invocation_id",
                    "request_digest",
                    "node_id",
                    "instance_id",
                    "state",
                    "accepted_at",
                    "terminal_at",
                    "terminal_code",
                    "execution_quiesced_at",
                    "execution_deadline_at",
                )
            },
            "sdk_result": finished[-1] if finished else None,
            "sdk_boundary": {
                key: starts[0].get(key)
                for key in (
                    "credential_revision",
                    "credential_env_clean_before",
                    "sdk_cwd_matches_sandbox",
                    "sdk_version",
                )
            }
            if starts
            else None,
        }
        if invocation and starts:
            created = runtime.database.execute_one(
                "select created_at from agent_job where id = ?", (job.id,)
            )["created_at"]
            row["queue_seconds"] = starts[0]["time"] - datetime.fromisoformat(created).timestamp()
        if starts and ends:
            row["sdk_seconds"] = ends[-1]["time"] - starts[0]["time"]
        rows.append(row)
    return rows


def isolation_checks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "sdk_overlap_seconds": min(r["sdk_end"] or 0 for r in rows)
        - max(r["sdk_start"] or 0 for r in rows),
        "distinct_nodes": len({r["runtime"]["node_id"] for r in rows}),
        "distinct_sandboxes": len({r["sdk_result"]["sandbox"] for r in rows if r["sdk_result"]}),
        "sandbox_canary_preserved": all(
            r["sdk_result"] and r["sdk_result"]["sandbox_file_matches"] for r in rows
        ),
        "sdk_cwd_matches": all(
            r["sdk_boundary"] and r["sdk_boundary"]["sdk_cwd_matches_sandbox"] for r in rows
        ),
        "frozen_context_isolated": all(r["frozen_context_isolated"] for r in rows),
        "credential_environment_restored": all(
            r["sdk_result"] and r["sdk_result"]["credential_env_clean_after"] for r in rows
        ),
    }
    checks["passed"] = (
        checks["sdk_overlap_seconds"] > 0
        and checks["distinct_nodes"] == len(rows)
        and checks["distinct_sandboxes"] == len(rows)
        and all(
            checks[key]
            for key in (
                "sandbox_canary_preserved",
                "sdk_cwd_matches",
                "frozen_context_isolated",
                "credential_environment_restored",
            )
        )
    )
    return checks


def wave(root: Path, *, name: str, count: int, kind: str = "capacity", workers: int = 3) -> None:
    compose(root, "up", "-d", "--scale", f"worker={workers}", "worker")
    runtime = container(root)
    jobs = [checked_job(runtime, root, kind) for _ in range(count)]
    samples = []
    started = time.time()
    while time.time() - started < 300:
        states = [runtime.agent_repository.get_job(j.id).status.value for j, _ in jobs]
        samples.append(
            {
                "time": time.time(),
                "pending": sum(s in {"PENDING", "RETRY_WAIT"} for s in states),
                "running": states.count("RUNNING"),
                "terminal": sum(s in {"SUCCEEDED", "FAILED", "TIMEOUT"} for s in states),
            }
        )
        if samples[-1]["terminal"] == len(jobs):
            break
        time.sleep(0.25)
    rows = facts(runtime, root, jobs)
    result = {
        "case": name,
        "workload": kind,
        "workers": workers,
        "submitted_jobs": len(jobs),
        "started_at": started,
        "finished_at": time.time(),
        "jobs": rows,
        "queue_samples": samples,
        "status": "PASS"
        if all(
            r["status"] == "SUCCEEDED"
            and r["sdk_starts"] == 1
            and r["expected_marker_present"]
            and not r["foreign_marker_present"]
            for r in rows
        )
        else "FAIL",
    }
    if kind == "isolation":
        result["isolation_assertions"] = isolation_checks(rows)
        if not result["isolation_assertions"]["passed"]:
            result["status"] = "FAIL"
    (root / "evidence" / (name + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    runtime.database.close()
    print(
        json.dumps(
            {
                "case": name,
                "status": result["status"],
                "jobs": [(r["status"], r["error_code"]) for r in rows],
            }
        )
    )
    assert result["status"] == "PASS", (
        "Real Provider wave did not pass; inspect safe evidence before continuing"
    )


def control(root: Path, *, kind: str) -> None:
    from app.modules.job.application.cancel_agent_job import cancel_agent_job

    runtime = container(root)
    job, marker = checked_job(runtime, root, kind)

    def sdk_started() -> bool:
        return any(
            e["kind"] == "sdk_query_start" and e["invocation_id"].startswith(job.id + ".")
            for e in journal(root)
        )

    wait_for(sdk_started, 60)
    time.sleep(2)
    before = runtime.database.execute_one(
        "select * from agent_runtime_invocation where job_id = ?", (job.id,)
    )
    at = time.time()
    if kind == "cancel":
        assert cancel_agent_job(runtime.database, job.id, "user_local_admin") == "cancel_requested"
    else:
        compose(root, "kill", "--signal", "SIGKILL", "worker")
        compose(root, "up", "-d", "worker")
    final = terminal(runtime, job.id, 180)
    row = facts(runtime, root, [(job, marker)])[0]
    if kind == "cancel":
        passed = final.status.value == "FAILED" and final.last_error_code == "runtime_cancelled"
    else:
        passed = (
            final.status.value == "SUCCEEDED"
            and final.worker_claim_version > 1
            and row["expected_marker_present"]
        )
    passed = (
        passed and row["sdk_starts"] == 1 and row["runtime"]["execution_quiesced_at"] is not None
    )
    result = {
        "case": "RPOOL-20-" + kind,
        "status": "PASS" if passed else "FAIL",
        "fault_at": at,
        "job_terminal_seconds": time.time() - at,
        "stop_seconds": datetime.fromisoformat(row["runtime"]["execution_quiesced_at"]).timestamp()
        - at,
        "same_invocation": row["runtime"]["invocation_id"] == before["invocation_id"],
        "same_digest": row["runtime"]["request_digest"] == before["request_digest"],
        "same_deadline": row["runtime"]["execution_deadline_at"] == before["execution_deadline_at"],
        "job": row,
    }
    (root / "evidence" / (result["case"] + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    runtime.database.close()
    print(
        json.dumps(
            {
                "case": result["case"],
                "status": result["status"],
                "elapsed_seconds": result["job_terminal_seconds"],
            }
        )
    )
    assert passed, "Real Provider control case did not pass"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["init", "warmup", "parallel", "serial", "burst", "cancel", "takeover"]
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--master-file", type=Path)
    args = parser.parse_args()
    if args.action == "init":
        assert args.master_file is not None
        initialize_real(args.master_file)
    else:
        assert args.root is not None
        if args.action in {"cancel", "takeover"}:
            control(args.root, kind=args.action)
        else:
            choices = {
                "warmup": (1, "capacity", 1),
                "parallel": (3, "isolation", 3),
                "serial": (3, "capacity", 1),
                "burst": (6, "capacity", 3),
            }
            count, kind, workers = choices[args.action]
            wave(
                args.root, name="RPOOL-real-" + args.action, count=count, kind=kind, workers=workers
            )


if __name__ == "__main__":
    main()
