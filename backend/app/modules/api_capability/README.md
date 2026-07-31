# Governed API capability boundary

This module owns declarative external API capabilities whose stable identifiers
use the reserved `cap__` namespace.

It does not extend or replace the code-defined internal Handler registry:

| Concern | Internal tools | Governed external API |
| --- | --- | --- |
| Python module | `modules/internal_tools` | `modules/api_capability` |
| Implementation | Code-defined Handler registry | Fixed `http-json-v1` executor plus published declarative plan |
| Persistence | `handler_installation`, `handler_publication`, application resource bindings | `api_*` identities, revisions, drafts, releases and exact publication bindings |
| Resolver | `HandlerExecutionResolver` | Separate governed Capability resolver |
| Runtime permission | Existing role/data-scope policy | Agent envelope, application allowlist, Release state and current-user credential |
| Model name | Existing internal Tool name | Stable `cap__<provider>__<domain>__<operation>` identifier |

The external resolver must never fall back to an internal Handler, shared
credential, administrator identity, service account, another Team or a floating
revision.

