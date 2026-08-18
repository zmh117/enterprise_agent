# Implementation validation — 2026-08-18

## Confirmed in the current checkout

- OpenSpec strict validation: `openspec validate add-governed-docling-file-representations --strict` passed.
- Compose rendering: `docker compose config --quiet` passed.
- Backend focused regression: 179 passed, 18 skipped. The skipped cases are PostgreSQL integration cases that require an explicitly configured test PostgreSQL environment; SQLite migration coverage passed.
- Frontend type checking: `npm run typecheck` passed.
- Business Application UI regression: 9 passed.
- Ruff checks and `git diff --check` passed.
- The focused regression covered schema/migration, processing profile, File Service protocol, provider, worker, RabbitMQ topology, Business Application publication, attachment readiness, Manifest v3/v4 compatibility paths, representation-only materialization, Compose security, secret bootstrap, service-principal authorization, and File Service security.

## Frozen upstream boundary

- Docling Serve image: `ghcr.io/docling-project/docling-serve-cpu:v1.30.0`.
- Multi-architecture digest: `sha256:061d35c03611bc15b73d024c8e8387bcf0624279f8b57c16c1567326f214ba56`.
- The provider contract was checked against the official v1.30.0 source and uses only internal multipart async submit, poll, and fetch endpoints; the v1.29/v1.30 multiple-target, chunking, and callback additions are not exposed by the governed profile.
- Runtime configuration disables remote sources, callbacks, plugins, custom pipelines, VLM, UI exposure, and runtime model downloads.

## Intentionally not claimed complete

- No official SBOM artifact was found for the pinned release, so task 1.3 remains open even though version, digest, architecture, license, provenance, and non-root metadata were checked.
- No CPU benchmark has been run on the deployment target; the phase-1 concurrency of one and the current CPU/memory limits are conservative configuration, not benchmark evidence.
- No fresh live PostgreSQL/RabbitMQ/MinIO/Docling synthetic seven-format E2E has been run.
- No real Runtime-to-Delivery business-chain evidence has been captured.
- The source-stream authorization path is implemented and tested, but dedicated read-access audit evidence remains open.
- Production rollout remains disabled by the default publication profile `NONE`; enabling `docling-text-v1` requires a controlled test publication and observation window.
