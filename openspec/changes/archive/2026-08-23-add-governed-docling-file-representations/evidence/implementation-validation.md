# Implementation validation — refreshed 2026-08-21

## Confirmed in the current checkout

- OpenSpec strict validation: `openspec validate add-governed-docling-file-representations --strict` passed.
- Compose rendering: `docker compose config --quiet` passed.
- Backend focused regression: 179 passed, 18 skipped. The skipped cases are PostgreSQL integration cases that require an explicitly configured test PostgreSQL environment; SQLite migration coverage passed.
- Frontend type checking: `npm run typecheck` passed.
- Business Application UI regression: 9 passed.
- Ruff checks and `git diff --check` passed.
- The focused regression covered schema/migration, processing profile, File Service protocol, provider, worker, RabbitMQ topology, Business Application publication, attachment readiness, Manifest v3/v4 compatibility paths, representation-only materialization, Compose security, secret bootstrap, service-principal authorization, and File Service security.

## Frozen upstream boundary

- Docling Serve image: `quay.io/docling-project/docling-serve:v1.30.0`.
- Multi-architecture digest: `sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807`.
- The provider contract was checked against the official v1.30.0 source and uses only internal multipart async submit, poll, and fetch endpoints; the v1.29/v1.30 multiple-target, chunking, and callback additions are not exposed by the governed profile.
- Runtime configuration disables remote sources, callbacks, plugins, custom pipelines, VLM, UI exposure, and runtime model downloads.

## Remaining release limitations

- The upstream release still has no official SBOM. Local SPDX JSON for the pinned digest
  is compensating evidence only, so environments requiring a vendor SBOM remain blocked.
- The ARM64 CPU benchmark and fresh isolated seven-format Compose E2E are recorded in
  `cpu-benchmark.md` and `synthetic-compose-e2e.md`; concurrency remains one.
- Source-stream authorization and safe read-audit evidence are implemented and covered by
  focused tests.
- The isolated fresh database intentionally has no model credential, so its
  `runtime_model_binding_missing` failure remains a valid fail-closed fixture. The
  separate live Runtime-to-Delivery success and governed failure paths were accepted on
  2026-08-21 and are recorded in `live-runtime-delivery-e2e.md` without business content
  or credential material.
- Production rollout remains disabled by default profile `NONE`. The observed
  `docling-text-v1` path was confined to one isolated synthetic publication.

## Local Compose deployment evidence

- The live PostgreSQL migration ledger advanced from `111` to `113`; the migrator reported only `112,113` applied and preserved existing bootstrap identities and storage credentials.
- `docling-serve` runs the pinned arm64 image on the internal `document-processing` network with a read-only root filesystem, non-root UID `1001`, no host port publication, CPU execution, and preloaded artifacts. Its `/ready` health check passed.
- `file-processing-worker` runs as UID/GID `10006`, with a read-only root filesystem and no published ports. Its health check confirmed RabbitMQ, File Service, and Docling readiness.
- The isolated Docling network contained exactly `docling-serve` and `file-processing-worker`. An unauthenticated conversion request from the worker network returned HTTP `401`.
- RabbitMQ exposed the dedicated main, retry, and dead-letter queues. At validation time the main queue had one consumer and all three queues had zero ready or unacknowledged messages.
- The database reported zero publications with a non-`NONE` document-processing profile and zero processing runs. This proves the deployment did not silently activate document processing for an existing application; it does not prove a conversion or end-to-end business path.
- An idle resource snapshot showed Docling at approximately `1.45 GiB / 8 GiB` and the processing worker at approximately `39 MiB / 512 MiB`. This is an operational sample, not the required CPU benchmark.
