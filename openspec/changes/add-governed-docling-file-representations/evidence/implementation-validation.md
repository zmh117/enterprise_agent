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

- Docling Serve image: `quay.io/docling-project/docling-serve:v1.30.0`.
- Multi-architecture digest: `sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807`.
- The provider contract was checked against the official v1.30.0 source and uses only internal multipart async submit, poll, and fetch endpoints; the v1.29/v1.30 multiple-target, chunking, and callback additions are not exposed by the governed profile.
- Runtime configuration disables remote sources, callbacks, plugins, custom pipelines, VLM, UI exposure, and runtime model downloads.

## Intentionally not claimed complete

- No official SBOM artifact was found for the pinned release, so task 1.3 remains open even though version, digest, architecture, license, provenance, and non-root metadata were checked.
- No CPU benchmark has been run on the deployment target; the phase-1 concurrency of one and the current CPU/memory limits are conservative configuration, not benchmark evidence.
- No fresh live PostgreSQL/RabbitMQ/MinIO/Docling synthetic seven-format E2E has been run.
- No real Runtime-to-Delivery business-chain evidence has been captured.
- The source-stream authorization path is implemented and tested, but dedicated read-access audit evidence remains open.
- Production rollout remains disabled by the default publication profile `NONE`; enabling `docling-text-v1` requires a controlled test publication and observation window.

## Local Compose deployment evidence

- The live PostgreSQL migration ledger advanced from `111` to `113`; the migrator reported only `112,113` applied and preserved existing bootstrap identities and storage credentials.
- `docling-serve` runs the pinned arm64 image on the internal `document-processing` network with a read-only root filesystem, non-root UID `1001`, no host port publication, CPU execution, and preloaded artifacts. Its `/ready` health check passed.
- `file-processing-worker` runs as UID/GID `10006`, with a read-only root filesystem and no published ports. Its health check confirmed RabbitMQ, File Service, and Docling readiness.
- The isolated Docling network contained exactly `docling-serve` and `file-processing-worker`. An unauthenticated conversion request from the worker network returned HTTP `401`.
- RabbitMQ exposed the dedicated main, retry, and dead-letter queues. At validation time the main queue had one consumer and all three queues had zero ready or unacknowledged messages.
- The database reported zero publications with a non-`NONE` document-processing profile and zero processing runs. This proves the deployment did not silently activate document processing for an existing application; it does not prove a conversion or end-to-end business path.
- An idle resource snapshot showed Docling at approximately `1.45 GiB / 8 GiB` and the processing worker at approximately `39 MiB / 512 MiB`. This is an operational sample, not the required CPU benchmark.
