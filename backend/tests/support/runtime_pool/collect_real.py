"""Summarize real acceptance using safe metadata, never prompts, responses or credentials."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any

from backend.tests.support.runtime_pool.real import binding_snapshot, facts, isolation_checks
from backend.tests.support.runtime_pool.run import ROOT, compose, container, journal


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("A percentile requires observations")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 4)


def distribution(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max(values), 4),
    }


def memory_bytes(value: str) -> int:
    match = re.fullmatch(r"([0-9.]+)\s*(B|KiB|MiB|GiB)", value)
    if match is None:
        raise ValueError("Unexpected Docker memory measurement unit")
    amount, unit = match.groups()
    return int(float(amount) * {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}[unit])


def peak_concurrency(events: list[dict[str, Any]]) -> dict[str, int]:
    peaks = {}
    for node in "abc":
        changes = sorted(
            (e["time"], 1 if e["kind"] == "sdk_query_start" else -1)
            for e in events
            if e["node_id"] == node and e["kind"] in {"sdk_query_start", "sdk_query_end"}
        )
        current = maximum = 0
        for _, delta in changes:
            current += delta
            maximum = max(maximum, current)
            assert current >= 0
        assert current == 0
        peaks[node] = maximum
    return peaks


def collect(root: Path) -> dict[str, Any]:  # noqa: PLR0915
    runtime = container(root)
    state = json.loads((root / "state.json").read_text())
    before = state["managed_binding_before"]
    after = binding_snapshot()
    assert before == after, "Source managed binding or encrypted credential changed"
    reports = {}
    for name in ("warmup", "parallel", "serial", "burst"):
        path = root / "evidence" / f"RPOOL-real-{name}.json"
        report = json.loads(path.read_text())
        jobs = []
        for row in report["jobs"]:
            job = runtime.agent_repository.get_job(row["job_id"])
            marker = re.search(r"RPOOL_SYNTH_[a-f0-9]+", job.input_message).group()
            jobs.append((job, marker))
        report["jobs"] = facts(runtime, root, jobs)
        assert report["status"] == "PASS"
        reports[name] = report
    isolation = isolation_checks(reports["parallel"]["jobs"])
    assert isolation["passed"]
    events = journal(root)
    peaks = peak_concurrency(events)
    assert peaks == {"a": 1, "b": 1, "c": 1}
    sandbox_cleanup = {}
    topology = {}
    for node in "abc":
        value = compose(
            root,
            "exec",
            "-T",
            "runtime-" + node,
            "python",
            "-c",
            "import os,json;from pathlib import Path;p=Path('/tmp/python-agent-runtime/sandboxes');print(json.dumps({'uid':os.getuid(),'remaining_job_sandboxes':len(list(p.glob('job-*'))),'real_provider_disabled_fake':os.environ.get('AGENT_RUNTIME_TEST_PROVIDER_MODE')=='disabled'}))",
        )
        topology[node] = json.loads(value)
        assert topology[node]["uid"] != 0 and topology[node]["real_provider_disabled_fake"]
        assert topology[node]["remaining_job_sandboxes"] == 0
        sandbox_cleanup[node] = True
    controls = {
        kind: json.loads((root / "evidence" / f"RPOOL-20-{kind}.json").read_text())
        for kind in ("cancel", "takeover")
    }
    assert all(
        case["status"] == "PASS"
        and case["same_invocation"]
        and case["same_digest"]
        and case["same_deadline"]
        for case in controls.values()
    )
    phases = {}
    for name in ("serial", "burst"):
        case = reports[name]
        rows = case["jobs"]
        duration = case["finished_at"] - case["started_at"]
        phases[name] = {
            "workers": case["workers"],
            "jobs": len(rows),
            "duration_seconds": duration,
            "observed_jobs_per_second": len(rows) / duration,
            "queue_seconds": distribution([r["queue_seconds"] for r in rows]),
            "sdk_seconds": distribution([r["sdk_seconds"] for r in rows]),
            "max_pending": max(s["pending"] for s in case["queue_samples"]),
            "final_pending": case["queue_samples"][-1]["pending"],
            "unexpected_errors": sum(r["status"] != "SUCCEEDED" for r in rows),
        }
    resources = {}
    samples = 0
    for line in (root / "metrics/resources.jsonl").read_text().splitlines():
        sample = json.loads(line)
        samples += 1
        for item in sample["containers"]:
            name = item["Name"]
            entry = resources.setdefault(
                name, {"peak_cpu_percent": 0.0, "peak_memory_bytes": 0, "peak_pids": 0}
            )
            entry["peak_cpu_percent"] = max(
                entry["peak_cpu_percent"], float(item["CPUPerc"].rstrip("%"))
            )
            entry["peak_memory_bytes"] = max(
                entry["peak_memory_bytes"], memory_bytes(item["MemUsage"].split(" / ")[0])
            )
            entry["peak_pids"] = max(entry["peak_pids"], int(item["PIDs"]))
    rows = runtime.database.execute(
        "select id,status,last_error_code,retry_count,worker_claim_version from agent_job order by created_at"
    )
    assert len(rows) <= 18 and all(
        r["status"] in {"SUCCEEDED", "FAILED", "TIMEOUT"} and r["retry_count"] == 0 for r in rows
    )
    assert sum(r["last_error_code"] == "runtime_cancelled" for r in rows) == 1
    assert all(
        r["status"] == "SUCCEEDED" or r["last_error_code"] == "runtime_cancelled" for r in rows
    )
    starts = [e for e in events if e["kind"] == "sdk_query_start"]
    assert len(starts) == len(rows) and len({e["invocation_id"] for e in starts}) == len(rows)
    completed = [e for e in events if e["kind"] == "sdk_finished"]
    assert all(e["credential_env_clean_before"] for e in starts)
    assert all(e["credential_env_clean_after"] for e in completed)
    schema = runtime.database.execute_one("select max(version) as head from schema_migration")
    runtime.database.close()
    source_files = sorted(
        set(
            subprocess.check_output(
                ["git", "diff", "--name-only"], cwd=ROOT, text=True
            ).splitlines()
            + subprocess.check_output(
                ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True
            ).splitlines()
        )
    )
    result = {
        "collected_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "case_ids": ["RPOOL-19", "RPOOL-20"],
        "task_ids": ["11.1", "11.2"],
        "domains": ["execution-delivery", "channel-conversation", "platform-operations"],
        "provider": "real Claude Agent SDK and managed Anthropic-compatible Provider; no fake responses",
        "managed_model": {
            k: before[k]
            for k in ("connection_id", "revision_id", "config_hash", "model", "active_version")
        },
        "source_configuration_unchanged": True,
        "encrypted_credential_record_unchanged": True,
        "credential_scope": "One existing managed credential version shared by three isolated processes. No rotation or new credential. Real multi-credential switching was not exercised; credential isolation evidence is exact binding, read-only mount and environment restoration.",
        "hardware": json.loads((root / "evidence/hardware.json").read_text()),
        "runtime_topology": topology,
        "build_identity": {
            "source_revision": "local-dev",
            "build_id": "local-dev",
            "platform": "linux/arm64",
        },
        "base_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "image_ids": {
            tag: subprocess.check_output(
                ["docker", "image", "inspect", "--format", "{{.Id}}", tag], text=True
            ).strip()
            for tag in ("ea-runtime-pool-test:local", "ea-runtime-pool-worker-test:local")
        },
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in source_files
            if (ROOT / name).is_file()
            and (
                name.startswith("backend/app/")
                or name.startswith("backend/tests/support/runtime_pool/")
                or name.startswith("contracts/")
                or name == "backend/Dockerfile"
            )
        },
        "schema": schema,
        "bounds": {
            "job_limit": 18,
            "jobs_submitted": len(rows),
            "business_retry_limit": 0,
            "max_model_turns": 4,
            "configured_timeout_ceiling_seconds": 120,
            "observed_application_timeout_seconds": 60,
        },
        "parallel": isolation,
        "max_sdk_concurrency_per_node": peaks,
        "sandbox_cleanup": sandbox_cleanup,
        "capacity_phases": phases,
        "percentile_method": "Linear interpolation; 3 and 6 samples. Descriptive observations, not a capacity guarantee or tail-latency SLO.",
        "controls": controls,
        "surface_model_rate_limit_errors": sum(
            e.get("error_code") == "runtime_model_rate_limited" for e in completed
        ),
        "model_rate_limit_observation": "No surfaced rate-limit error. Provider quotas and hidden SDK HTTP retries were not measured.",
        "resources": {
            "sample_count": samples,
            "approximately_seconds_between_samples": 2,
            "containers": resources,
        },
        "jobs": rows,
        "sdk_events": events,
        "waves": reports,
        "fixture_corrections": state.get("fixture_corrections", []),
        "superseded_isolation_attempt": json.loads(
            (root / "evidence/RPOOL-real-parallel-attempt1.json").read_text()
        )
        if (root / "evidence/RPOOL-real-parallel-attempt1.json").exists()
        else None,
        "limitations": [
            "Synthetic short text on one host and one model only.",
            "Sandbox isolation uses actual per-job SDK cwd, transparent canary files and cleanup; file tool integration is outside this load test.",
            "Only SDK query spans are used for overlap; Provider-reported API duration is corroborating data, not a trace of remote server scheduling.",
            "Cancelled execution stops local SDK; upstream processing or billing after cancellation cannot be observed.",
        ],
    }
    (root / "evidence/real-summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    value = collect(args.root)
    print(
        json.dumps(
            {
                "status": value["status"],
                "jobs": len(value["jobs"]),
                "parallel": value["parallel"],
                "capacity": value["capacity_phases"],
                "controls": {
                    k: {n: v[n] for n in ("status", "job_terminal_seconds", "stop_seconds")}
                    for k, v in value["controls"].items()
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
