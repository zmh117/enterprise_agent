# Internal API Platform (topology-aware, read-only)

The Internal API Platform is the second security layer between the Agent and real
data sources. It resolves structured addresses to concrete resources, enforces a
read-only + workshop-isolation policy, and audits every access decision.

## Topology model

```
Environment (e.g. sanjiu, mmk)
  └─ Base (business code, e.g. guanlan 观澜基地; one DB engine per base)
       ├─ Database / Redis / Loki   (base-level connections)
       └─ Workshop (logical partition, e.g. GL001, GL002)
            ├─ table_prefix     GL001_EBR_
            ├─ redis_key_prefix GL001:
            └─ loki_label       {workshop: GL001}
```

- **Bases use business codes**; IP/host are internal connection details, never exposed to the model.
- **Engine is per base** (one base = one of `mysql` / `sqlserver` / `oracle`).
- **Workshops are logical**: DB/Redis/Loki are base-level; workshops differ only by naming.
- **Degenerate base** (e.g. `mmk/main`): no workshops — still read-only + bounded, no prefix/label.

Configuration is a YAML file (see `backend/config/internal_platform_topology.example.yaml`)
pointed to by `INTERNAL_PLATFORM_TOPOLOGY_FILE`. Secrets are referenced as
`secret://<path>` and resolved from `SECRET_<UPPER_SNAKE_OF_PATH>` env vars — the
topology file never contains plaintext credentials.

## Structured addressing (tool contract)

Tools carry independent addressing fields; `project_code` remains an Agent-side coarse
permission and is **not** mapped to `environment`.

```json
POST /tools/database/query
{ "environment": "sanjiu", "base": "guanlan", "workshop": "GL001",
  "sql": "select * from GL001_EBR_order where status='WAITING_MATERIAL'", "limit": 100 }
```

Redis (`/tools/redis/get`, `/tools/redis/scan`) and Loki (`/tools/loki/query`) take the
same `environment/base/workshop`. The caller identity is read from `X-Agent-User-Id`.

Schema discovery is a dedicated read-only platform endpoint, not user-supplied SQL:

```json
POST /tools/schema/directory
{ "environment": "sanjiu", "base": "guanlan", "workshop": "GL001", "limit": 20 }
```

The response lists only authorized tables and columns for the target workshop, omits all
connection details, and marks `truncated=true` when bounded. Agent SQL must reference only
tables and columns from this directory. If the directory is empty or lacks fields needed
for the user question, the Agent should report `不具备诊断证据` instead of guessing table names.

### Multi-dialect schema preview

`SchemaInspectorFactory` selects a read-only inspector from the resolved base engine:

- MySQL: reads `information_schema.columns`.
- Oracle: reads `ALL_TABLES` and `ALL_TAB_COLUMNS`. Table bounds use a nested
  `ROWNUM` query, so metadata preview is compatible with Oracle 11g and does not require
  `FETCH FIRST`.
- SQL Server: reads `sys.tables`, `sys.schemas`, `sys.columns`, and `sys.types`.
  If the database binding does not set `schema`, the inspector uses `dbo`.

Schema preview returns ordinary table and column metadata only. It never samples business
rows, persists imported schema data, or exposes connection fields. `table_prefix`, search
text, table limits, and per-table column limits remain enforced for every engine.

Minimum metadata visibility:

- Oracle read-only users need access to the target owner's rows in `ALL_TABLES` and
  `ALL_TAB_COLUMNS`. Set the database binding `schema` to that owner; when omitted, the
  connection user is used.
- SQL Server read-only users need metadata visibility for the target database/schema
  (for example through ownership or an approved `VIEW DEFINITION` grant). Broader data
  write permissions are not required.

### ER context → addressing directory

`/tools/context/er` and `/tools/context/business-flow` return, in `summary.addressing`, an
**access-filtered** directory of environments → bases → workshops (codes + `display_name`
+ `aliases`, no connection details). This is how the model maps natural language to codes:

```
观澜基地 / 观澜 / 华南  -> base "guanlan"
一号车间               -> workshop "GL001"
```

The directory only lists what the caller (`X-Agent-User-Id`) is authorized for, so the
model cannot address bases/workshops it lacks access to. The Agent system prompt instructs
the model to resolve `environment/base/workshop` from this directory before calling any
data tool, and never to invent codes absent from it. Add `display_name`/`aliases` to the
topology YAML at environment, base, and workshop level to improve mapping quality.

## Multi-dialect read-only SQL safety

Pipeline (fails closed at every step):

1. Comment stripping + first-keyword check (`SELECT`/`WITH` only).
2. Parse with `sqlglot` (dialect: mysql / tsql / oracle); exactly one statement.
3. Read-only AST: reject non-query, `SELECT ... INTO`, `FOR UPDATE`, PL/SQL blocks / batches.
4. Real table extraction (excludes CTE names).
5. Workshop table-prefix enforcement (case-folded; Oracle upper-cases unquoted identifiers).
6. Schema-directory availability check for the referenced physical tables.
7. Dialect-correct row bound: MySQL `LIMIT`, SQL Server `TOP`, Oracle `FETCH FIRST`
   (modern) or `ROWNUM` wrapper when the base sets `oracle_compat: legacy`.

Defense in depth: SQL parser + read-only DB account + statement timeout + row/byte caps.
Cross-workshop (`GL002_*` in a `GL001` request) and prefix-less tables are rejected.

### Oracle thick / Instant Client

- The `internal-api-platform` image can bundle Oracle Instant Client (see
  `backend/vendor/oracle/README.md`). Set `ORACLE_CLIENT_LIB_DIR` if the libraries live
  elsewhere.
- Topology database fields (Oracle bases):
  - `oracle_client_mode`: `auto` (default) | `thin` | `thick`
  - `oracle_compat`: `modern` (default, `FETCH FIRST`) | `legacy` (`ROWNUM`)
  - `use_sid`: `true` to connect by SID instead of service name
  - `connect_descriptor`: optional full TNS / connect descriptor
- `thick` fails closed if Instant Client is missing or failed to initialize (no silent
  thin fallback). Local development without Instant Client can keep `auto`/`thin`.

## Redis / Loki isolation

- Redis: base-level connection; read-only command whitelist (`get` / bounded `scan`);
  keys/patterns must fall inside `workshop.redis_key_prefix`; `*` / empty patterns rejected.
- Redis modes (topology `redis.mode`):
  - `standalone` (default): single `host`/`port`/`db`
  - `cluster`: `nodes: [{host, port}, ...]` (or a single host as startup node); logical
    `db` must be `0` / omitted. Workshop key-prefix policy is unchanged; cluster SCAN may
    be slower across slots.
- Loki: base-level upstream (with tenant); the workshop label is injected on top of the
  caller selector, time range, and line limit.

## Access control & audit

`AccessPolicy` maps each `X-Agent-User-Id` to grants over `environment/base/workshop`
(`*` wildcards allowed). Denials are non-retryable (`403`). Every decision is logged by
`internal_api_platform.audit` with caller, target, decision, and reason.

## Verification

Local unit + contract coverage:

```
make check
```

Live MySQL smoke test (read-only), against a real database:

```
INTERNAL_PLATFORM_TOPOLOGY_FILE=... \
python -m uvicorn app.internal_api_platform:create_app --factory --port 9000
# then POST /tools/database/query with environment/base/workshop + a SELECT
```

Optional live schema preview tests:

```bash
RUN_ORACLE_SCHEMA_INTEGRATION=1 \
ORACLE_HOST=... ORACLE_SERVICE=... ORACLE_USER=... ORACLE_PASSWORD=... \
ORACLE_SCHEMA=... \
.venv/bin/pytest backend/tests/test_redis_oracle_integration.py \
  -k OracleSchemaInspectorIntegrationTests -q

RUN_SQLSERVER_SCHEMA_INTEGRATION=1 \
SQLSERVER_HOST=... SQLSERVER_DATABASE=... \
SQLSERVER_USER=... SQLSERVER_PASSWORD=... SQLSERVER_SCHEMA=dbo \
.venv/bin/pytest backend/tests/test_redis_oracle_integration.py \
  -k SqlServerSchemaInspectorIntegrationTests -q
```

Docker (topology-aware profile):

```
docker compose --profile real-tools up -d --build
# set INTERNAL_API_BASE_URL=http://internal-api-platform:9000 for api-server/agent-worker
```
