# DingTalk MCP Phase 2 live E2E evidence

Date: 2026-08-30

This artifact records bounded control-plane and runtime facts only. It excludes Secret, Token, authorization headers, external identity values, raw user messages, provider response bodies, and unbounded business content.

## Publication and role grant

- Agent Publication revision 20 is active and is the single Agent Publication referenced by the current Application Publication.
- Application Publication revision 36 contains 39 tools in total and exactly 27 `dingtalk-mcp` tools, including `dingtalk_create_calendar_event`.
- The enabled `业务E2E` role grants exactly the same 27 DingTalk tools for the target application.
- The DingTalk connector is enabled, connected, belongs to an active enterprise, and has a valid positive work-notification Agent ID. Only the masked suffix `***4638` was observed.

## Frozen historical boundary

- The most recent pre-Phase-2 Job remains bound to the earlier Agent/Application Publications.
- Its immutable Job MCP Tool Snapshot still contains five total tools and only one DingTalk tool: `dingtalk_create_todo`.
- Publishing and granting Phase 2 therefore did not add tools to the historical Publication or old Job.

## First fresh read Job and deployment correction

- Fresh Job `job_3bc1102beb9448088fe872e356ae817a` used the current Publications and froze 31 tools in total, including exactly 27 DingTalk tools.
- The Job made one call each to `dingtalk_search_users`, `dingtalk_search_departments`, `dingtalk_list_todos`, `dingtalk_list_calendar_events`, and `dingtalk_search_aitables`.
- All five calls passed Principal, Publication, Job Snapshot, Application, and role authorization. Each authorization audit recorded `ALLOW` with reason `principal_identity_snapshot_and_tool_grant_allowed`.
- All five Provider attempts then failed before a DingTalk endpoint result was available. Container-level diagnosis proved that `dingtalk-mcp` could not resolve `api.dingtalk.com`, while the egress-enabled external action worker could.
- Root cause was a missing `provider-egress` network attachment for `dingtalk-mcp`; the generic `dingtalk_mcp_denied` response was a separate observability defect caused by missing Access Token error codes.
- The deployment now attaches `dingtalk-mcp` to both `agent-runtime-control` and `provider-egress`, preserves the internal-only MCP listener, and maps Access Token transport/HTTP/invalid-response/rejection failures to stable bounded codes.
- Regression evidence: 43 targeted tests passed, Ruff passed, `docker compose config --quiet` passed, `git diff --check` passed, both affected containers are healthy, and the rebuilt `dingtalk-mcp` resolves the DingTalk API host.

## Pending live tool calls

A post-fix fresh DingTalk read Job completed as `job_25b4b0d627e64dd182c1899d9cc9abce`:

- The five Tool calls again passed Principal, Publication, Job Snapshot, Application, and role authorization with `ALLOW`.
- `dingtalk_list_todos` succeeded with an empty bounded `todos` collection.
- `dingtalk_list_calendar_events` succeeded with an empty bounded `events` collection.
- `dingtalk_search_users`, `dingtalk_search_departments`, and `dingtalk_search_aitables` reached DingTalk after the network fix and returned the stable `dingtalk_permission_denied` classification.
- No raw Provider body or business collection values were inspected or persisted in this evidence.

A later post-permission run exposed `dingtalk_http_400` only for fuzzy user search. A bounded live A/B probe against the same Connector and keyword proved that sending optional `fullMatchField=0` is rejected, while omitting the field succeeds with an empty result. The fixed Provider contract now omits `fullMatchField` for fuzzy search and sends only the documented `fullMatchField=1` for exact search. No user rows or raw Provider response were printed or retained.

The notice-status read after a successful work-notification mutation, mutation agree/reject chains, provider-attempt counts, terminal card states, and exclusion visibility checks remain to be recorded below.

## Mutation agree chains

### Todo create

- Job `job_e8797d60b30848ffbb6d602aa37acfa6` called `dingtalk_create_todo` once through MCP and completed successfully.
- Tool Call `tool_02bfbe77c8854cf98115100e286ca0c3` is linked to MCP call `mcp_call_0f0f65f6679d4b85a9bc13837268ce88`; its authorization audit recorded `ALLOW` with reason `principal_identity_snapshot_and_confirmation_policy_allowed`.
- Intent `action_286de708fce246a88a252a299e6a8b50` froze operation `dingtalk.todo.create`, revision 1, and reached `SUCCEEDED` after the original user approved it.
- The Intent records exactly one execution attempt, a non-empty Provider task identifier, and bounded result keys `created,task_id`.
- Both `CREATE` and `RESULT_UPDATE` card outbox rows reached `SUCCEEDED` in one attempt. Audit events form `external_action.prepared -> external_action.approved -> external_action.executed`.
- The original user independently confirmed that the todo exists in DingTalk. No todo title, description, Provider body, external identity, Secret, or Token is retained in this artifact.
