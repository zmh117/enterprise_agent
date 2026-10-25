"""Collect only synthetic identity, lifecycle and timing evidence from this fixture."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import subprocess

from backend.tests.support.runtime_pool.run import ROOT, container, journal


def collect(root: Path) -> dict[str, object]:
    runtime = container(root)
    cases = [
        json.loads(path.read_text())
        for path in sorted((root / "evidence").glob("*.json"))
        if path.name != "summary.json" and path.name != "cutover-preflight.json"
    ]
    ids = set()
    for case in cases:
        ids.update(case.get("job_ids", []))
        for field in ("job_id", "new_job_id", "successor_id"):
            if case.get(field):
                ids.add(case[field])
    facts = []
    for job_id in sorted(ids):
        facts.append(
            {
                "job": runtime.database.execute_one(
                    "select id,session_id,status,retry_count,worker_claim_version,admission_deadline_at,cancel_requested_at,last_error_code,created_at,finished_at from agent_job where id = ?",
                    (job_id,),
                ),
                "invocations": runtime.database.execute(
                    "select invocation_id,attempt,request_digest,node_id,instance_id,state,accepted_at,execution_deadline_at,cancel_requested_at,terminal_code,terminal_at,execution_quiesced_at from agent_runtime_invocation where job_id = ? order by attempt",
                    (job_id,),
                ),
                "dispatch": runtime.database.execute_one(
                    "select status,attempt_count,wait_reason from job_dispatch_outbox where job_id = ?",
                    (job_id,),
                ),
                "delivery_count": runtime.database.execute_one(
                    "select count(*) as n from delivery_outbox where job_id = ?", (job_id,)
                )["n"],
            }
        )
    runtime.database.close()
    changed = set(
        subprocess.check_output(["git", "diff", "--name-only"], text=True, cwd=ROOT).splitlines()
    )
    changed.update(
        subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"], text=True, cwd=ROOT
        ).splitlines()
    )
    fingerprints = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(changed)
        if (ROOT / name).is_file()
        and (
            name.startswith("backend/app/")
            or name.startswith("backend/migrations/")
            or name.startswith("contracts/")
            or name in {"backend/Dockerfile", "docker-compose.yml"}
        )
    }
    images = {
        name: subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", name], text=True
        ).strip()
        for name in ("ea-runtime-pool-test:local", "ea-runtime-pool-worker-test:local")
    }
    return {
        "collected_at": datetime.now(UTC).isoformat(),
        "host_architecture": platform.machine(),
        "base_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=ROOT
        ).strip(),
        "uncommitted_worktree": True,
        "topology": {
            "runtime_nodes": 3,
            "workers": 3,
            "postgres": 18,
            "rabbitmq": 4,
            "execution_slots_per_node": 1,
        },
        "provider": "deterministic test adapter; no real SDK/Provider invocation",
        "build_identity": {
            "source_revision": "local-dev",
            "build_id": "local-dev",
            "platform": "linux/arm64",
        },
        "cutover_preflight": json.loads((root / "evidence/cutover-preflight.json").read_text()),
        "fixture_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path(__file__).parent.iterdir()
            if path.suffix in {".py", ".yml"}
        },
        "final_image_ids": images,
        "source_sha256": fingerprints,
        "build_scope": "Fault cases ran during incremental builds. Final product code rechecked parallelism, concurrent admission, cross-node terminal recovery and cancellation. The final images including timeout contract alignment additionally rechecked concurrent admission, cross-node recovery and full/minimal HTTP replay after body pruning. Actual PostgreSQL grants were reverified after permission tightening.",
        "cases": cases,
        "lifecycle_facts": facts,
        "provider_events": [
            event for event in journal(root) if event["invocation_id"].split(".attempt-")[0] in ids
        ],
        "not_run": ["RPOOL-19", "RPOOL-20"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = collect(args.root)
    target = args.root / "evidence/summary.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "output": str(target),
                "cases": len(result["cases"]),
                "jobs": len(result["lifecycle_facts"]),
            }
        )
    )


if __name__ == "__main__":
    main()
