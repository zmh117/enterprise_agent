# Implementation Preflight

Recorded: 2026-08-12 (Asia/Shanghai)

## Checkout and planning state

- Branch: `mcp_new`.
- This change was the only dirty scope when apply started: proposal, design, delta specs, and tasks under `add-identity-aware-ones-mcp`.
- Active OpenSpec changes observed without reading unrelated change artifacts:
  - `add-identity-aware-ones-mcp`: 0/62 before implementation.
  - `consolidate-schema-fact-sources-and-retire-legacy-tables`: 43/53.
  - `stabilize-schema-baseline-and-runtime-config`: 26/26.

## Migration generations

- Code migration generation: `100_baseline_v1.sql`, `101_expand_canonical_job_message.sql`, `102_schema_consolidation_checkpoint.sql`, and `103_contract_retire_compatibility_shadows.sql`.
- `legacy-v1-manifest.json` retains immutable adoption evidence for `001–042`, including:
  - `038_retire_legacy_api_platform.sql`
  - `039_restore_ones_identity_binding.sql`
  - `040_remove_legacy_tool_registry.sql`
  - `041_remove_retired_authorization_and_target_storage.sql`
- The running PostgreSQL ledger contains legacy `038–041` and has not yet recorded `100–103`; this is an adopted-legacy migration state to be verified by the repository migrator before applying this change.
- This change reserves `104_add_identity_aware_ones_mcp.sql` and will not edit, reuse, or recreate versions `001–103` or the legacy manifest.

## Live non-secret counts

- Enabled and disabled ONES external identity rows combined: `1`.
- Agent Jobs in `RUNNING`: `0`.

No credential values, Tokens, passwords, database credentials, cookies, model keys, or original business messages were read or recorded.

## Boundary conclusion

The change can proceed as a forward-only extension from the current `100–103` code baseline. It must not restore retired API Capability/Connection tables, the historical HS256 MCP signing model, `runtime-tool-mcp`, arbitrary MCP URLs, or generic HTTP/GraphQL executors.
