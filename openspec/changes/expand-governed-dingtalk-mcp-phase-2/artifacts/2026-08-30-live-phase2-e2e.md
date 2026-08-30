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

- Fresh representative read Job `job_e022d40048ac4c26aad65bbb9218fff8` completed one Tool call for contacts, department, tasks, calendar and notable. All five Tool Calls reached `SUCCEEDED`; their bounded list counts were respectively users `0`, departments `0`, todos `0`, events `0` and AI tables `1`. This distinguishes valid empty results from a non-empty but still bounded AI-table search without reproducing any item value.

After the successful work-notification mutation, fresh Job `job_27b1b8e644934553803141d8426f0c1f` called `dingtalk_get_work_notification_progress` and `dingtalk_get_work_notification_result` in order. The Job reached `SUCCEEDED` with Tool contract status `MATCH`; both Tool calls and their MCP audits reached `SUCCEEDED`, both authorization decisions were `ALLOW` with reason `principal_identity_snapshot_and_tool_grant_allowed`, and request/response truncation flags were false. The bounded response summaries contained only the declared `progress`/`result` and `untrusted_data` fields. The Job created zero Action Intents. Its frozen snapshot recorded both tools as `read`, confirmation policy `none`, and target policy `current_user_work_notification_history`.

Together with the representative contacts, department, tasks, calendar and notable calls above, this closes the Phase 2 read-only Profile gate. Mutation agree/reject chains, terminal card states, and exclusion visibility checks remain to be completed below.

## Contact string-ID regression run

- After deploying the fixed string-userId projection, fresh Job `job_1cd689f0422f4a008c035699e705b443` invoked `dingtalk_search_users` through the frozen Phase 2 Tool snapshot.
- Tool Call `tool_b3e4b9845db340c797fa7bed79b209fc` and MCP call `mcp_call_e06a9b1ce7ea4224b89be5d49d111e8f` both completed successfully; authorization was `ALLOW` with reason `principal_identity_snapshot_and_tool_grant_allowed`.
- The bounded MCP audit recorded exactly two projected user candidates and no Provider response body or complete user ID. This proves that a real string userId list no longer fails as `dingtalk_response_invalid`.
- The Runtime then attempted `dingtalk_get_user` twice, but both attempts failed before an MCP call ID or MCP operation audit was created. The search regression is fixed, while the detail-read request boundary still requires a fresh exact-argument run before same-name disambiguation can be accepted.

### Schema-declared user ID Runtime gate

- Fresh Job `job_99a298dbefb548c0be4f8386051179cc` again called `dingtalk_search_users` successfully. Its bounded MCP response summary recorded exactly two candidates, authorization was `ALLOW`, and no Action Intent was created.
- The same immutable Job snapshot contained both `dingtalk_search_users` and `dingtalk_get_user`, but the Job still produced no detail Tool Call. Combined with the preceding pre-MCP failures, code diagnosis proved that Python Runtime's generic Tool-input guard treated every field named `user_id` as a Principal override even when the current frozen Tool schema declared it as an explicit business target.
- The Runtime guard now allows an identity-like top-level field only when the exact current Job binding matches the code-owned server, Tool, schema hash, and declared input property. Undeclared `actor_id`, nested overrides, and bindings with schema drift remain denied; the DingTalk MCP server still performs closed-schema validation and Principal/target injection.
- Regression evidence: 57 Python Runtime tests and 43 DingTalk MCP/contract tests passed, Ruff and `git diff --check` passed, and the rebuilt `python-agent-runtime` is healthy. A post-deployment fresh Job is still required before detail-read acceptance.
- Post-deployment Job `job_29da96acf5aa46e3abddb11d684937d2` proved the Runtime fix: it called search once and `dingtalk_get_user` twice in the same Job. Both detail calls crossed the Runtime gate, created Tool Call and MCP audit IDs, and passed current Principal/Job/Application/role authorization with `ALLOW`.
- The search again returned exactly two bounded candidates. Both detail Provider calls were then explicitly rejected with stable public classification `dingtalk_provider_rejected`; no Action Intent was created. The remaining blocker is therefore the DingTalk application-side `qyapi_get_member` capability and contact visible scope (or an equivalent Provider-side rejection), not Job Tool authorization or the Runtime input gate.
- After the administrator added the requested contact capability and visible scope, fresh Job `job_b5dbbf968a454ddb9d0ae5ee3a1a30e9` reproduced the same bounded chain: one successful search, two detail calls with platform authorization `ALLOW`, and two Provider rejections. This disproved the earlier permission-only diagnosis.
- Comparison with the pinned official `dingtalk-mcp@1.1.21` runtime identified the transport mismatch: official code adds `access_token` to the query string for authenticated `oapi.dingtalk.com` endpoints and reserves `x-acs-dingtalk-access-token` for `api.dingtalk.com`. The project had sent the Header form to both hosts. That explains why new-API search succeeded while legacy `topapi/v2/user/get` failed for both candidates.
- The fixed Provider transport now applies the host-specific official authentication projection. Regression tests assert that legacy calls have the query token and no token Header, while new calls have the Header and no query token. A fresh post-deployment read Job is required to verify both user-detail calls and same-name disambiguation.
- Post-deployment Job `job_2f4debfdc5ae4d4b960bb4081576902c` closed that read-only gate. It invoked one `dingtalk_search_users` call and two `dingtalk_get_user` calls; all three Tool Calls and MCP operation audits reached `SUCCEEDED`, and every authorization audit recorded `ALLOW` with reason `principal_identity_snapshot_and_tool_grant_allowed`.
- The persisted bounded response summaries recorded exactly two search candidates, non-truncated audit payloads, and a declared detail object for each of the two detail calls. No Action Intent was created. Full user IDs, directory records, Provider bodies, credentials, and the original request were neither read into this artifact nor reproduced here.
- A later fresh Job `job_2fc2bb04a7524e1eb66306d3cda546b4` repeated the same bounded chain after the final service rebuild: one search and two detail calls all reached `SUCCEEDED`; all three MCP authorization records were `ALLOW`, both request/response truncation flags were false, and no Action Intent was created. This confirms that the accepted contact behavior is present in the currently running images rather than only an earlier container revision.

## Mutation agree chains

### Provider contract corrections found by confirmation E2E

- Confirmed work-notification Intent `action_174d21db14ba4fb793429c1dfd0afb52` created one confirmation card and one Provider attempt, then failed with `dingtalk_provider_rejected`. The running `external-action-worker` image was inspected and still contained the pre-fix legacy authentication projection, proving the read-side `dingtalk-mcp` rebuild had not updated the independent mutation worker.
- Confirmed current-conversation robot Intent `action_825fa04e20f14a91916ac2b9142f9037` also created one card and one Provider attempt, then failed with `dingtalk_http_400`. Comparison with the pinned official package proved that robot `msgParam` uses `extendType=json` and is serialized with `JSON.stringify` before the API request; the project had sent an object instead of the required JSON string.
- The Provider client and contract tests now apply both corrections: host-specific legacy authentication and JSON-string robot `msgParam`. A rebuilt external-action worker and fresh confirmation Jobs are required; historical failed Intents remain terminal and are not replayed.
- After rebuilding both services, fresh work-notification Job `job_57a81f39b750468ab48bf5bed028aab7` prepared Intent `action_b4e1e3f06a1f4b759c5b56034903ac2f`. The original actor approved revision 1; the Intent reached `SUCCEEDED` with exactly one execution attempt and a non-empty Provider task identifier. Its `CREATE` and `RESULT_UPDATE` card outbox rows each reached `SUCCEEDED` in one delivery attempt, and the MCP authorization audit recorded `ALLOW` for the exact mutation contract.
- Fresh current-source robot Job `job_b7c5bc851d1948ac96dc9d4ea6a86f7a` prepared Intent `action_068c549a2be24b03b6af74631fc4f22f` after the `msgParam` correction. The original actor approved it; the Intent reached `SUCCEEDED` with exactly one execution attempt and a non-empty Provider request identifier. Its `CREATE` and `RESULT_UPDATE` card rows each reached `SUCCEEDED` in one attempt, and the exact MCP mutation authorization was `ALLOW`. No message title, body, complete target identity, Provider response, Secret or Token is retained here.

### Todo create

- Job `job_e8797d60b30848ffbb6d602aa37acfa6` called `dingtalk_create_todo` once through MCP and completed successfully.
- Tool Call `tool_02bfbe77c8854cf98115100e286ca0c3` is linked to MCP call `mcp_call_0f0f65f6679d4b85a9bc13837268ce88`; its authorization audit recorded `ALLOW` with reason `principal_identity_snapshot_and_confirmation_policy_allowed`.
- Intent `action_286de708fce246a88a252a299e6a8b50` froze operation `dingtalk.todo.create`, revision 1, and reached `SUCCEEDED` after the original user approved it.
- The Intent records exactly one execution attempt, a non-empty Provider task identifier, and bounded result keys `created,task_id`.
- Both `CREATE` and `RESULT_UPDATE` card outbox rows reached `SUCCEEDED` in one attempt. Audit events form `external_action.prepared -> external_action.approved -> external_action.executed`.
- The original user independently confirmed that the todo exists in DingTalk. No todo title, description, Provider body, external identity, Secret, or Token is retained in this artifact.

### Calendar create and read-back

- Fresh Job `job_5e0fe1fdc6ab4ae3a85c89e5085d1191` prepared calendar-create Intent `action_8e540e55b01a4124ae38b1ae7604dba1`. The exact Tool authorization was `ALLOW`; the original actor approved the current revision; one Provider execution attempt returned a non-empty event identifier; the Intent and both `CREATE`/`RESULT_UPDATE` card rows reached `SUCCEEDED` in one attempt.
- The original user then reported that the event was not visible in the DingTalk client, so the mutation's platform success state alone was not accepted as proof of the external business result.
- Fresh read-only Job `job_369a62129b444838a5307cf8839bbde3` used the exact returned event identifier with `dingtalk_get_calendar_event`, then queried the bounded expected time window with `dingtalk_list_calendar_events`. The Job reached `SUCCEEDED` with Tool contract status `MATCH`; both Tool Calls and Tool audits reached `SUCCEEDED`; both authorization decisions were `ALLOW` with reason `principal_identity_snapshot_and_tool_grant_allowed`; the bounded list contained exactly one event; and no Action Intent was created.
- The precise identifier lookup proves that the created event exists through the current principal's primary-calendar API, while the bounded list proves that one event is visible in the requested time window. This closes the Provider-side external-result check. The user's earlier client observation is retained as a separate DingTalk client display, filter, or synchronization uncertainty and is not represented as API creation failure.
- The fixed request method, path and payload field projection match the pinned official `dingtalk-mcp@1.1.21` `createEvent` contract. No title, description, complete event identifier, credential or raw Provider response is retained here.
