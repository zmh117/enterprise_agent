# Verification record

Date: 2026-07-31

## Functional and integration gates

- `.venv/bin/pytest -q`
  - `763 passed, 22 skipped, 4 subtests passed`
  - The skips are opt-in external-runtime tests without credentials in the
    default suite.
- `MIGRATION_POSTGRES_DSN=<admin-dsn> .venv/bin/pytest -q
  backend/tests/test_governed_api_capability_postgres_integration.py
  backend/tests/test_schema_migration_postgres_integration.py`
  - `8 passed` against the local PostgreSQL 18 container.
  - This run found and verified the fix for the original SQLite-only `instr`
    constraint in migration 025.
- `cd frontend && npm run lint && npm run typecheck &&
  npm test -- --run && npm run build`
  - ESLint and TypeScript passed.
  - Vitest: `12` files and `62` tests passed.
  - Production build passed; Vite reported only the existing large-chunk
    advisory.

## Specification and static gates

- `openspec validate add-governed-api-capability-handlers --strict`
  - Passed.
- `.venv/bin/ruff check .`
  - Passed for the entire repository.
- Strict mypy over the changed governed-API, external-credential, Agent,
  Claude-tool, and Job integration paths
  - `Success: no issues found in 28 source files`.
- Ruff format check over the 34 newly added Python source/test files
  - Passed.

## Existing repository-wide baseline

The composite `make check` cannot yet be reported green for reasons outside
this change:

- `.venv/bin/mypy backend/app` reports 22 existing errors in 11 unrelated
  files.
- `.venv/bin/ruff format --check .` reports 194 existing files that would be
  reformatted.

These unrelated files were not mass-edited. Task 14.6 remains open until the
repository-wide type and formatting baseline is repaired or explicitly
baselined.

## Runtime deployment

Date: 2026-07-31

- Created and validated a PostgreSQL custom-format backup before migration:
  `/private/tmp/enterprise-agent-025.9vH2sx/enterprise_agent_pre_025.dump`
  (`SHA-256 4cdba44d7d68f2bc6f5c32682a5cbbc93d5c7e71b4283335162f1b753014df05`).
- Confirmed all RabbitMQ ready and unacknowledged counts were zero before
  stopping ingress and workers.
- Rebuilt `migrator`, all Python runtime services, and `admin-web`. The first
  build exposed a missing `api_capability` copy in the Worker image; the
  Dockerfile was corrected and the repeated build passed its import check.
- Applied migration 025 with `MIGRATION_SUCCEEDED: head=025 baselined=0
  applied=025`.
- Verified all five new tables exist and the pre-migration counts for
  `user_external_identity`, `agent_publication`,
  `business_application_publication`, and `agent_job` were unchanged.
- Recreated the stateless services from the new images without recreating
  PostgreSQL, RabbitMQ, or MinIO.
- Container-local smoke checks passed: `/api/ready` returned HTTP 200 with
  `schema_head=025`; governed connection, capability, and ONES identity routes
  were present in OpenAPI; `admin-web` returned HTTP 200; DingTalk Runtime and
  health-checked workers were healthy; queues remained empty; startup logs had
  no `ERROR`, `Traceback`, `ModuleNotFoundError`, or `Exception` lines.

## Enterprise plain-HTTP opt-in gates

Date: 2026-08-02

- `.venv/bin/pytest -q`
  - `765 passed, 22 skipped, 4 subtests passed`.
- `cd frontend && npm run lint && npm run typecheck && npm test -- --run &&
  npm run build`
  - ESLint and TypeScript passed.
  - Vitest: `12` files and `63` tests passed.
  - Production build passed with only the existing large-chunk advisory.
- Focused Ruff checks, `openspec validate
  add-governed-api-capability-handlers --strict`, and `git diff --check`
  passed.
- Regression coverage proves production HTTP is accepted only with explicit
  `allow_plain_http`, missing authorization fails closed, HTTPS canonicalizes
  the flag to false, the legacy request alias remains accepted, conflicting
  aliases fail closed, and migration 026 preserves the stored authorization.

## Runtime deployment 026

Date: 2026-08-02

- Before maintenance, schema head was 025, all RabbitMQ ready and
  unacknowledged counts were zero, and the three API Connection tables each
  contained zero rows.
- Created and validated a PostgreSQL custom-format backup with 1099 TOC
  entries at
  `/private/tmp/enterprise-agent-026.hMVwWr/enterprise_agent_pre_026.dump`
  (`SHA-256 55bdf0e99af9f914490eee63f10da62c34b8461a4d1ab7f9332a2f51b345ecd0`).
- Stopped ingress before workers, rebuilt `migrator`, `api-server`, all Python
  workers, `internal-api-platform`, and `admin-web`, then applied migration 026
  with `MIGRATION_SUCCEEDED: head=026 baselined=0 applied=026`.
- PostgreSQL verification showed only `allow_plain_http` on both
  `api_connection_draft` and `api_connection_revision`; the legacy column was
  absent, and all three API Connection table counts remained unchanged.
- Recreated the stateless services from the new images. `/api/ready` returned
  `status=ready` and `schema_head=026`; `admin-web` returned HTTP 200 from the
  application network; all Compose services were running/healthy; queues
  remained empty; and startup logs contained no `ERROR`, `Traceback`,
  `CRITICAL`, or `MIGRATION_FAILED` lines.
- From the rebuilt API image, production normalization accepted fixed origin
  `http://host.docker.internal:19121` only with `allow_plain_http=true`, OpenAPI
  exposed the new field, and ONES Mock health returned HTTP 200. No persistent
  Connection was created solely for the smoke test.
