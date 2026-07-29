# Phase 3B Oracle image evidence

Date: 2026-07-28

## Implemented contract

- Oracle Resource accepts structured `host`, `port`, `username`,
  `password_ref`, and exactly one of `service_name` or `sid`.
- Arbitrary connect descriptors, RAC/SCAN inputs, Thin/auto fallback, and
  Oracle 12c `FETCH FIRST` are rejected.
- Runtime requires python-oracledb Thick with a matching 64-bit Instant
  Client 19c ELF library. Oracle 11.2 queries always use a `ROWNUM` wrapper.
- The technical probe checks server version `11.2.0.4`, read-only effective
  privileges, a read-only transaction, `AL32UTF8`, and `AL16UTF16`.

## Static and unit evidence

```text
70 passed, 1 warning, 4 subtests passed
36 passed
Ruff: All checks passed
bash -n backend/docker/setup_oracle_client.sh: passed
```

The ignored local archive is Instant Client 23.26 for x86-64. Its
`libclntsh.so.19.1` entry is only a symbolic link to the 23c library. The
installer now ignores this archive instead of misreporting 19c availability.
The user-owned archive was not modified or deleted.

## Image build and startup

```text
docker compose build internal-api-platform
Approved Oracle Instant Client 19c not found; Oracle remains blocked
Image enterprise_agent-internal-api-platform Built

docker run --rm enterprise_agent-internal-api-platform ...
IMAGE_START_OK oracle=blocked reason=approved_19c_missing
IMAGE_ARCH=aarch64
POINTER_BITS=64
IMAGE_START_OK arch=aarch64 drivers=mysql,sqlserver,oracle,redis oracle=blocked
```

The service image starts for the other supported Providers. Oracle does not
fall back to Thin. The final image uses a dedicated `database-deps` stage and
imports the MySQL, SQL Server, python-oracledb, and Redis drivers successfully.

## Deferred real acceptance

No reachable Oracle 11.2.0.4 instance exists locally. A fake/unit probe and
image startup are not accepted as publication evidence. Default Oracle Draft
verification therefore returns `BLOCKED` with
`real_connection_verified=false`; Oracle revisions cannot be published until
a later protected real-connection acceptance is explicitly enabled and
completed.
