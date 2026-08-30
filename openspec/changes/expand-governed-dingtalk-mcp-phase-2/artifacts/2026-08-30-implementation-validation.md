# DingTalk MCP Phase 2 implementation validation

Date: 2026-08-30

This artifact records bounded, non-secret implementation and deployment evidence. It does not claim that the pending real DingTalk publication or external E2E scenarios have completed.

## Implemented catalog

- The built `dingtalk-mcp` image exposes exactly 27 fixed contracts: 18 read tools and 9 mutation tools.
- Every mutation maps one-to-one to a fixed operation code and requires a fresh original-user confirmation card.
- Dynamic profiles, arbitrary endpoints, arbitrary recipients, delete/revoke/DING operations, AI-table structural mutation, `ACTIVE_PROFILES`, provider YAML and `ROBOT_ACCESS_TOKEN` are not runtime inputs.

## Automated validation

- DingTalk MCP and control-plane targeted pytest: 192 passed.
- Relevant backend `unit or contract` layer, excluding the unrelated Python Runtime architecture assertion file: 1262 passed, 1 skipped, 247 deselected, 2 subtests passed.
- Unfiltered `make test-fast`: 1265 passed, 1 skipped, 247 deselected, 2 subtests passed, with one unrelated existing failure in `test_python_runtime_has_no_dynamic_plugin_or_runtime_registry`; the assertion's expected dynamic-import list does not include `claude_agent_sdk._cli_version`.
- Changed Python files: Ruff format check passed for 28 files; Ruff check passed; targeted mypy passed for 21 source files.
- Repository Ruff lint passed.
- Frontend lint and typecheck passed; 119 frontend tests passed; production build passed with only existing Vite warnings.
- Target change strict validation passed; all OpenSpec validation passed, 21 items with 0 failures.
- `git diff --check` and `docker compose config --quiet` passed.

Known unrelated repository baselines remain outside this change: the Python Runtime architecture assertion above, full mypy reports existing Docling/File Workspace failures, and full repository format check reports existing unformatted files. These were not hidden by weakening the targeted checks.

## Built and deployed runtime

- Rebuilt and redeployed `dingtalk-mcp`, `external-action-worker`, `api-server`, and `admin-web`.
- `dingtalk-mcp`, `external-action-worker`, and `api-server` are healthy; `admin-web` is running.
- Runtime health returned `status=ok` and `server_code=dingtalk-mcp`.
- Database schema head is migration 123, `123_expand_governed_external_actions.sql`.

## Read-only live control-plane observation

- The current Application Publication remains revision 34 with 13 tools.
- Its Agent Publication also has 13 tools.
- Both frozen publications expose only `dingtalk_create_todo` from `dingtalk-mcp`; no Phase 2 tool was silently added to either snapshot.
- The bound DingTalk connector is enabled, registered, connected and belongs to an active enterprise, but delivery is disabled and no positive work-notification Agent ID is configured.

## Pending real-publication and E2E conditions

No new live Agent/Application Publication or role grant was created because the current connector cannot satisfy the work-notification readiness gate. Completing tasks 8.1 through 8.5 requires:

1. Configure the connector's positive work-notification Agent ID and enable the intended delivery capability.
2. Confirm the DingTalk application has the documented permissions for each selected profile.
3. Create new Agent and Application Publications plus explicit role grants for the exact selected tools.
4. Start new real DingTalk Jobs for representative reads and each mutation agree/reject chain.
5. Save bounded evidence joining Job, Tool Call, Intent, card callback, provider attempt and final result, without secrets, tokens or unbounded business content.

Until those conditions are met, the existing Publication and old Jobs remain frozen and do not gain the new capabilities.
