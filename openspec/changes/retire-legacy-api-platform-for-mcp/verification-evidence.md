# Verification evidence

Verified on 2026-08-11 against the local Compose deployment.

## Migration protection and live upgrade

- Preflight confirmed PostgreSQL 18.4 and RabbitMQ 4.3.2 healthy.
- `agent.job.queue` had `ready=0` and `unacked=0`; retry/dead queues were absent (zero).
- A new custom-format PostgreSQL logical backup, globals, pre-migration metrics and checksums were created under `.local/compose-infra-upgrade/20260811T103444Z`. This path is local-only and MUST NOT be committed or uploaded.
- Before migration, schema head was `038`; the guard found zero unconverted active `agent_tool_binding` rows and zero channel references to the old Internal API connector.
- The Compose migrator applied `039,040` and reported schema head `040`.
- After migration, `ones_identity_verification_challenge` and `agent_publication_mcp_tool` exist; `agent_tool_binding`, `tool_definition`, `datasource_registry` and `external_api_credential` do not exist.
- The retained `user_external_identity` table remains the ONES identity fact source. No ONES identity existed in the local database before this upgrade, so no ONES row could be used for a data-preservation comparison.

## Static, unit and build verification

- MCP/ONES/migration/Python Runtime focused backend set: `52 passed`.
- Migration catalog and rollback/fail-closed set: `23 passed`, including a 039-to-040 active legacy-binding rejection test.
- Python Runtime fixed remote `tool-mcp` set: `7 passed`.
- Frontend: `84 passed`; ESLint, TypeScript checking and production Vite build passed.
- TypeScript Runtime: `31 passed`; ESLint, typecheck, build and generated-contract check passed.
- Backend Ruff and compileall passed.
- OpenSpec strict validation passed for both active changes and for all 86 specs/changes.
- `git diff --check`, Compose `config --quiet` and active source/config legacy-marker scans passed.

The repository-wide backend suite completed with `564 passed, 19 skipped, 56 failed`. The remaining failures are concentrated in pre-existing debug/test-header fixtures and legacy jobs created without a published Agent MCP snapshot; the production paths involved were not modified as part of this retirement. Because the repository-wide suite is not green, task 9.1 remains open rather than being reported as complete.

## Images and readiness

- Built current images for migrator, API, `tool-mcp`, Python Runtime, TypeScript Runtime, Agent Worker, supporting Workers and Admin Web.
- Recreated application services without deleting PostgreSQL, RabbitMQ, MinIO or their volumes.
- API readiness reports schema head `040`, both Runtime identities/database/master-key states ready, and default Runtime `python-v1`.
- `tool-mcp`, both Runtime services, API, DingTalk Runtime and health-checked Workers are healthy; Admin Web returns HTTP 200.
- Post-start log scan found only normal client-initiated RabbitMQ connection-close INFO events and no traceback, fatal or migration failure.

## Still requiring explicit acceptance evidence

- A real Python and TypeScript Job calling the test MySQL schema/query tools.
- A DingTalk greeting, permission denial and successful delivery round-trip after this exact build.
- ONES self bind, reverify, default-Team change, self-unbind and administrator read-only/disable flows against a configured ONES identity endpoint.

These live/external acceptance cases are not inferred from health checks or configuration-only evidence.
