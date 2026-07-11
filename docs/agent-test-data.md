# Agent test data environment

This local environment is for debugging the read-only diagnostic Agent against real
MySQL, SQL Server, and Redis services. It is isolated behind the
`agent-test-data` Compose profile and is not part of the default stack.

Oracle remains supported by the Internal API Platform, but it is intentionally
excluded from this local test-data profile because the Oracle test image is not
available in the current environment.

## Services

| Base | Database service | Redis service | Host ports by default |
| --- | --- | --- | --- |
| `agent_test/mysql` | `agent-test-mysql` | `agent-test-redis-mysql` | MySQL `3307`, Redis `6381` |
| `agent_test/sqlserver` | `agent-test-sqlserver` | `agent-test-redis-sqlserver` | SQL Server `14330`, Redis `6382` |

Container-to-container topology uses service DNS names and standard ports. The
host ports are only for local inspection.

## Resource and architecture notes

- MySQL uses `mysql:8.4`.
- Redis uses `redis:7.4`.
- SQL Server uses `mcr.microsoft.com/mssql/server:2022-latest` with
  `AGENT_TEST_SQLSERVER_PLATFORM=linux/amd64`.

On ARM64 Macs, SQL Server is an emulated local test path and must pass the real
health check. If it does not, run the full validation on an x86-64 Docker host.

## Lifecycle commands

```bash
scripts/agent_test_data.sh up
scripts/agent_test_data.sh seed
scripts/agent_test_data.sh verify
scripts/agent_test_data.sh reset --yes
```

- `up` starts the four data services, waits for health checks, seeds, and verifies.
- `seed` restores the deterministic fixture baseline on existing volumes.
- `verify` checks direct DB/Redis data and then checks the Internal API Platform
  routing path through `real-tools`.
- `reset --yes` stops only the test-data services and removes only the four
  explicitly named test volumes.

Do not use `docker compose down -v` for this workflow; that can delete unrelated
PostgreSQL/RabbitMQ data.

## Fixture scenario

Both databases contain the same MES model:

- `production_order`
- `equipment`
- `equipment_alarm`
- `material_inventory`
- `quality_inspection`
- `production_event`

The fixed diagnostic chain is:

- `PO-STUCK-001` is still running with `completed_qty=36`.
- `EQ-MIX-01` is linked to that order, has stale heartbeat, and is `OFFLINE` in DB.
- `ALM-CRIT-001` is an uncleared `CRITICAL` `TEMP_HIGH` alarm.
- `MAT-001` has DB available quantity `10`.
- The matching Redis instance intentionally says `EQ-MIX-01` is `ONLINE`, order
  progress is `completed_qty=72`, and `MAT-001` available quantity is `80`.

The correct Agent behavior is to query the database and the matching Redis for
the same base, compare evidence, and report the deterministic cache mismatch. Do
not expose raw connection details to the Agent; it should address resources by
`environment=agent_test` and `base=mysql|sqlserver`.

## Example Agent debugging prompt

Ask the Agent to diagnose one base at a time:

```text
在 agent_test/mysql 基地，查询 PO-STUCK-001、EQ-MIX-01、TEMP_HIGH、MAT-001 的数据库证据，
再读取同一基地 Redis 中 agent_test:mysql:* 的相关 key。
请指出订单停滞、设备异常、库存不足，以及 Redis 与数据库不一致的具体字段和值。
不要输出数据库或 Redis 连接信息。
```

Repeat with `agent_test/sqlserver`, changing the Redis namespace to
`agent_test:sqlserver:*`.
