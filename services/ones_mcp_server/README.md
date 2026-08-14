# ONES MCP Server

This is an internal, identity-aware MCP server. It publishes code-registered ONES
tools over stateless Streamable HTTP. It is not an arbitrary GraphQL or HTTP proxy.

## Module boundaries

- `app.py`: MCP transport, HTTP security middleware, readiness, and lifecycle.
- `bootstrap.py`: platform dependency assembly.
- `auth/`: Principal JWT, frozen Job/Publication facts, and ONES identity resolution.
- `provider/http_client.py`: fixed Provider origin, bounded JSON transport, no redirects.
- `provider/graphql/`: reusable GraphQL client and code-owned operation registry.
- `provider/graphql/operations/`: fixed documents, variables, and strict response parsers.
- `credentials/`: 401 refresh, per-credential locking, revision CAS, and refresh audit.
- `tools/`: MCP Tool validation and business/audit orchestration.

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

`runtime.py` is only a compatibility import surface. New implementation code should
import the owning module directly.
