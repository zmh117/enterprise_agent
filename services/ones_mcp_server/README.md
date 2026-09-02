# ONES MCP Server

This is an internal, identity-aware MCP server. It publishes code-registered ONES
tools over stateless Streamable HTTP. It is not an arbitrary GraphQL or HTTP proxy.

## Module boundaries

- `app.py`: MCP transport, HTTP security middleware, readiness, and lifecycle.
- `bootstrap.py`: platform dependency assembly.
- `auth/`: Principal JWT, frozen Job/Publication facts, and ONES identity resolution.
- `provider/http_client.py`: fixed Provider origin, bounded JSON transport, no redirects.
- `provider/graphql/`: reusable GraphQL client and code-owned operation registry.
- `provider/graphql/documents/`: code-owned GraphQL document files.
- `provider/graphql/operations/`: fixed paths, variables, and strict response parsers.
- `provider/rest/operations/`: fixed REST methods, paths, request bodies, and response parsers.
- `condition_dictionary.py` and `resources/`: validated, Team-scoped status and
  custom-option lookup snapshot; no Provider transport or personal directory data.
- `task_update_catalog.py`, `task_update.py`, and `provider/task_update.py`: bounded
  defect-write catalog, semantic Patch compiler, fixed detail query, and fixed
  `update3` adapter.
- `credentials/`: 401 refresh, per-credential locking, revision CAS, and refresh audit.
- `tools/`: MCP Tool validation and business/audit orchestration.

## Read-only query tools

The server keeps the legacy `ones_work_item_search` and
`ones_list_project_role_members` tools and also registers these fixed business
queries:

- Project discovery and structure: `ones_search_projects`,
  `ones_list_project_sprints`, and `ones_list_issue_types`.
- Work items: `ones_query_work_items` for its existing standard filters,
  `ones_query_work_items_with_custom_options` for dictionary-validated custom
  option filters, `ones_get_work_item_detail`, and `ones_list_work_item_messages`.
- Query conditions: `ones_resolve_query_conditions` performs a bounded local
  resource lookup for status and custom-option candidates after Principal Team
  validation. It is not GraphQL or REST and never refreshes Provider credentials.
- People: `ones_search_team_users` for live name search and
  `ones_get_users_by_uuids` for fixed REST batch lookup of UUID/name summaries.
- Test assets: `ones_list_testcase_libraries`, `ones_list_testcase_modules`,
  `ones_list_test_plans`, `ones_query_test_cases`, and
  `ones_get_test_case_detail`.

Every tool accepts only bounded business arguments. Provider origin, default Team,
credential headers, HTTP path, GraphQL document, and fixed query type remain
server-owned. New tools become callable only after the normal Agent/Application
publication flow freezes them into a new Job; adding them to the code manifest does
not widen an existing publication. The existing `ones_query_work_items` contract is
unchanged; custom-option support is a separate Tool so its schema hash cannot drift
for historical Publications or Jobs.

## Confirmed defect update

`ones_update_task` updates one existing defect by UUID. Its public schema contains
only semantic Patch fields; status, Team, Provider path, headers, and credentials are
not caller-controlled. The Tool can be prepared only by a DingTalk-source Job and
never writes during the MCP call. It computes the full Chinese old-to-new diff and
privately delivers the existing external-action confirmation card to the originating
operator. The shared external-action worker reauthorizes the frozen ONES identity,
Team, Publication and Job Tool snapshot, requires an unchanged
`serverUpdateStamp`, executes one fixed `update3` request, and verifies the result by
readback. Existing Publications, Applications, roles, and Jobs do not receive this
Tool automatically.

## Agent query orchestration

The optional `ones-query` Skill teaches an Agent how to combine live project,
sprint, issue-type, and user discovery with managed condition resolution and the
fixed work-item tools. It does not contain dictionary UUIDs or default statistical
formulas. The Skill is available to Agent Profile configuration but is loaded only
when a new Publication snapshot selects it; existing Publications and Jobs are not
modified automatically.

## Updating the managed query-condition snapshot

The ignored `ones_mock/ones/查询条件字典.yaml` is maintenance input only. Production,
Mock, and test runtime code must not read it. After reviewing an updated personal
capture, regenerate the minimal checked-in resource explicitly:

```bash
.venv/bin/python scripts/sync_ones_query_condition_dictionary.py \
  ones_mock/ones/查询条件字典.yaml \
  services/ones_mcp_server/resources/query_condition_dictionary.json
```

The generator accepts only Team metadata, statuses, and single/multi-select custom
options. It excludes people, projects, sprints, issue types, request headers, and
raw responses; malformed input does not replace the current resource. Run the
dictionary, ONES contract, architecture, Mock, and Runtime tests before rebuilding
and explicitly republishing the Agent/Application.

The defect-write field catalog is generated separately from the same maintenance
input. It contains only the reviewed defect fields and static option UUID/name pairs;
people, projects, sprints, products, modules, status, and raw Provider data remain
runtime-resolved or excluded:

```bash
.venv/bin/python scripts/sync_ones_task_update_field_catalog.py \
  ones_mock/ones/查询条件字典.yaml \
  services/ones_mcp_server/resources/task_update_field_catalog.json
```

## Adding a GraphQL-backed Tool

1. Add a fixed query operation under `provider/graphql/operations/`. The operation
   owns its path, document, variable builder, and response parser.
2. Register the operation in `bootstrap.py`. Never accept a document, URL, path,
   Header, Token, user ID, or Team ID from Tool input.
3. Add the MCP Tool service under `tools/`, with a closed input schema and explicit
   Principal scope, frozen Tool binding, business authorization, and audit events.
4. Add the Tool to the governed platform manifest and Runtime publication flow.
5. Extend Principal JWT scope issuance deliberately before publishing the Tool.
6. Add Mock, Provider failure, refresh, concurrent-call, exact-audit-link, and
   authentication-material exclusion tests.

## Adding a REST-backed Tool

1. Add one code-owned REST operation with the exact Method, relative Path,
   Headers, request body, and response parser supplied for that ONES interface.
2. Compose multiple operations only in the owning Tool service with a fixed call
   order. Do not add a workflow DSL or accept transport fields from Tool input.
3. Register the Tool in the ONES registry and governed platform manifest, then add
   exact Mock request and response tests before publication.

`runtime.py` is only a compatibility import surface. New implementation code should
import the owning module directly.
