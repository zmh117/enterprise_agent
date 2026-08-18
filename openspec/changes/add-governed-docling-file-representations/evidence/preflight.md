# Docling apply preflight

Checked at 2026-08-17 on branch `one_runtime`.

## Checkout and ownership

- Apply started from `6469f56` (`feat(platform): 统一工具资源范围并清理旧平台残留`), one commit ahead of `origin/one_runtime`.
- The only pre-existing unstaged path at preflight was `.github/workflows/ci.yml`; its quote-only edit is outside this change and must remain untouched.
- This change owns `openspec/changes/add-governed-docling-file-representations/` plus the implementation paths explicitly added or modified while applying it. It must not clean, revert, stage, or silently absorb other worktree changes.

## Canonical and active-change boundary

- The relevant canonical specs are `business-application`, `channel-conversation`, `execution-delivery`, `platform-operations`, and `task-file-workspace`.
- The current canonical baseline still explicitly forbids `docling-serve`, limits the accepted workspace source to the existing text policy, and defines `file-service` as the only MinIO/object-location boundary. The Docling requirements therefore remain this change's delta until sync/archive; they are not claimed as current capability during apply.
- `support-log-and-markdown-workspace-files` is at 39/40 tasks. Its code-level `text-v2`, Manifest v3, Runtime protocol v1.3, TXT/LOG/Markdown action matrix, and migration `111` are present in the checkout. Its remaining real end-to-end acceptance is not treated as completed evidence for this change.
- `sync-platform-topology-spec-to-code-manifest` is at 14/14 tasks and is included in current HEAD. It does not own the file-processing topology, but its canonical synchronization and migration `112` must not be rewritten.

## Unique implementation coordinates

- The next monotonic expand migration is `113`; migrations `111` and `112` remain immutable.
- Manifest v3 and Runtime protocol v1.3 are the implemented text-workspace base. This change alone introduces Manifest v4 representation fields while preserving v1-v3 compatibility.
- Existing service names remain `file-service` and `file-worker`. This change adds exactly `file-processing-worker` and `docling-serve`; it does not add `file-mcp`, Redis, RQ, or Ray.
- `file-worker` retains attachment download/import and lifecycle cleanup. `file-processing-worker` exclusively consumes the new processing queue and calls Docling through the fixed `DocumentProcessor` provider seam.
- File Service remains the sole PostgreSQL/object-storage fact boundary. Neither new service receives MinIO credentials or object keys.
- The fixed profile identifier is `docling-text-v1`; the default publication value is `NONE`.

## Candidate upstream image

- Official image: `quay.io/docling-project/docling-serve:v1.30.0`.
- Multi-architecture index digest: `sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807`.
- Linux amd64 manifest: `sha256:0ccbc00b5f8b443334a7c4f36a5c6ff89c684c6fbe18ff7c1bc41e00b8e01657`.
- Linux arm64 manifest: `sha256:b09477515c6234bb86c8a90c9db3af2b5d6991aeb6b64c3348283be264dba63c`.
- OCI metadata identifies release `v1.30.0`, source revision `69192d178924bbae2f1733e2d7cd21ffd04259c5`, license `MIT`, runtime user `1001`, and preloaded model artifacts.
- Registry attestations contain SLSA provenance for both architectures. No upstream SBOM attestation was exposed by the OCI index (`docker buildx imagetools inspect --format '{{json .SBOM}}'` returned `{}`). A local Docker Scout SPDX generation against the exact arm64 image was attempted twice and stopped after bounded waits while still indexing the 4.4 GB compressed image. Local Compose wiring may be validated with the profile left at `NONE`; production profile enablement remains blocked on a successfully generated and retained SBOM digest. Provenance alone is not treated as an SBOM.

Official references:

- <https://github.com/docling-project/docling-serve/releases/tag/v1.30.0>
- <https://github.com/docling-project/docling-serve#container-images>
- <https://github.com/docling-project/docling-serve/blob/v1.30.0/LICENSE>
