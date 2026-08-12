# Verification evidence (2026-08-12)

## Database

- SQLite migration/runtime tests: `41 passed, 15 skipped`; skipped cases are the
  opt-in PostgreSQL DSN matrix.
- A dedicated temporary PostgreSQL database applied `100,101,102,103,104` from
  empty state and reported head `104`.
- PostgreSQL metadata verification found both new tables, seven MCP audit
  indexes, six encrypted challenge columns, and seven MCP audit foreign keys.
- Re-running the repository migrator against the existing business database
  stopped at the migration 103 independent-approval gate. No approval record was
  fabricated, no ledger was edited, and the business database remained at head
  102.
- All temporary PostgreSQL databases used by this verification were dropped.

## Focused behavior

- Identity, credential, Principal JWT, authorization, publication, dual Runtime,
  ONES MCP and audit suite: `106 passed`.
- Final ONES MCP suite: `28 passed`, including Mock query, one-time 401 refresh,
  second 401, login failure, subject/Team drift, CAS conflict, current user and
  Tool revocation, Host/Origin/body bounds, Provider failure classification,
  exact unmasked business evidence, authentication-secret rejection, audit
  transaction rollback, retention, and admin audit-read authorization.
- TypeScript Runtime: `34 passed`; contract generation check, lint, typecheck and
  build passed.
- Frontend: `87 passed`; lint, typecheck and production build passed. The build
  emitted only the existing large-chunk warning.

## Deployment

- `docker compose config --quiet` passed.
- After the authorized empty-database rebuild, the main Compose migrator applied
  `100,101,102,103,104`; a read-only database check confirmed head `104` and
  both `external_identity_credential` and `mcp_operation_audit` tables.
- Main Compose now includes the repository `ones-mock` on the internal Runtime
  network only. It has no host-published port, runs as UID/GID `10004`, uses a
  read-only filesystem, drops all capabilities, and is a health-gated dependency
  of `ones-mcp`.
- A live query from the running `ones-mcp` container to the internal Mock
  returned exactly one expected work item. `ones-mock`, `ones-mcp`, both
  Runtimes, the API and every other service with a healthcheck were healthy.
- `ones-mcp`, `agent-worker`, `python-agent-runtime`,
  `typescript-agent-runtime`, and `api-server` image builds completed. The first
  ONES image build exposed a missing MCP SDK dependency; the dependency is now a
  pinned, image-specific `ones-mcp` optional dependency and the rebuilt image
  imports successfully.
- The rebuilt ONES MCP image returned successful `/health` against a temporary
  PostgreSQL head 104 with a temporary JWKS and the configured master-key mount.
  Temporary verification keys were deleted afterwards.
- Static deployment tests confirm no host port, read-only filesystems, fixed
  networks, private-key-only Worker mounting, public-JWKS-only ONES MCP mounting,
  fixed ONES MCP URLs in both Runtimes, and production rejection of the local
  HTTP Provider default.
- Secret bootstrap verification passed for a fresh directory, an idempotent
  second run, and an upgrade directory that already contained the complete
  Runtime secret group. A deliberately incomplete Principal key pair was
  rejected without overwrite. All temporary secret directories were deleted.

## Repository-wide checks

- OpenSpec change strict validation passed.
- OpenSpec all strict validation passed: `12 passed, 0 failed`.
- `git diff --check` passed.
- Backend full pytest: `764 passed, 27 skipped, 2 failed` plus two passing
  subtests. Both remaining failures predate and are outside this change: tests
  still expect migration 103-retired `agent_session` compatibility columns.
- Repository-wide mypy still reports three pre-existing errors in
  `agent_config/api/controller.py` and `shared/schema_consolidation.py`.
- Repository-wide Ruff still reports five pre-existing findings: three unrelated
  no-placeholder f-strings in `job/infrastructure/repositories.py` and two unused
  imports in `shared/schema_consolidation.py`. Focused ONES MCP Ruff and mypy
  checks pass.

## Acceptance boundary

Repository Mock acceptance does not prove compatibility with a real ONES
deployment. Real DingTalk -> Runtime -> ONES -> Delivery end-to-end validation
was not executed, so this evidence does not claim production readiness.
