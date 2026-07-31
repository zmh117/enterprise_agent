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
