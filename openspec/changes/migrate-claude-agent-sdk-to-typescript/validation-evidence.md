# Validation evidence

Date: 2026-08-10

## Completed automated gates

- TypeScript Runtime: `preflight:static`, ESLint, TypeScript typecheck, 28 unit/contract tests, generated-contract check and production build passed.
- Container build: `migrator`, `agent-runtime`, `runtime-tool-mcp` and `agent-worker` images built successfully from the updated Compose/Dockerfiles.
- Python focused migration suite: 131 tests passed, covering protocol, migration gate, Runtime client, MCP authorization, model probe, readiness, Compose/database policy, model connections, legacy Python rollback client, retry/failure Delivery, transactional Delivery Outbox and schema migration.
- Backend Ruff passed for the full `backend` tree.
- `docker compose config --quiet`, OpenSpec strict validation and `git diff --check` passed.

## Repository-existing failures outside this change

A broader focused run initially reported 129 passed and 20 failed. Six failures were stale schema-head assertions caused by the new `034` migration and were updated; the migration suite now passes 27/27. The remaining 14 failures are existing seed-policy mismatches in untouched legacy suites:

- 6 `test_agent_runtime_and_worker.py` cases create Jobs as `local-user`, which the current seed policy does not grant `project:default:use`.
- 8 Phase 3A/platform Secret cases use `local-user` or legacy admin headers without the current `secret:manage`/platform-config permissions.

These unrelated failures were not bypassed by changing production authorization or widening seed permissions.

## Gates intentionally still open

- No real Provider credential, DingTalk ingress, Runtime service deployment or production database role was used in this validation.
- Tasks 7.1-7.4 require a disposable Application and real end-to-end execution, including MCP, cancellation, retry, restart, Delivery, sensitive-data inspection and rollback of unstarted TypeScript Jobs.
- The default Runtime remains permanently `python-v1`; no production default or canary publication was switched.
- Python `claude-agent-sdk`, its CLI/Node Worker layer and the in-process adapter are a supported long-term Runtime, not a temporary deletion candidate.
