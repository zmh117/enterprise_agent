# Schema migration baseline

The active migration generation starts at `100_baseline_v1.sql`. New schema
changes must use monotonically increasing three-digit versions beginning at
`101`; versions `001` through `100` must never be reused.

`legacy-v1-manifest.json` is immutable evidence for the retired `001`–`042`
chain. It freezes every legacy version, filename and SHA-256 checksum, the
catalog digest, the final SQLite/PostgreSQL schema fingerprints, and the
PostgreSQL table/column comment digest. The retired SQL remains available from
Git history and is not loaded by current runtime images.

## Cutover inventory

Before the cutover, migration state was referenced by:

- `backend/app/shared/migrations.py` for catalog, ledger, migration, adoption,
  rollback and readiness validation;
- `backend/app/shared/database.py::default_migrations_dir()` for the canonical
  directory;
- `backend/app/cli/migrate.py` and business-service startup validators;
- `backend/Dockerfile` and `docker-compose.yml` for the one-shot migrator image
  and dependency gate;
- backend migration, readiness, schema-comment and PostgreSQL integration
  tests;
- deployment, recovery and database runbooks under `docs/`.

The retired head was `042_document_public_schema.sql`; it also contained the
complete final PostgreSQL comment list. The baseline generator at
`backend/maintenance/build_schema_baseline.py` must be run against a clean Git
checkout containing exactly legacy `001`–`042`, never against the active
migration directory. Its optional PostgreSQL mode creates two random temporary
databases, compares old-chain and baseline semantics, and drops both databases.

Supported ledger shapes are:

- fresh generation: `100[, 101, ...]` with no adoption metadata;
- adopted legacy generation: exact `001..042, 100[, 101, ...]` with one matching
  `schema_baseline_adoption` row.

Partial legacy heads, checksum drift, unknown generations, non-empty schemas
without a ledger, or forged adoption metadata fail closed.
