# Oracle Instant Client (for internal-api-platform thick mode)

The `internal-api-platform` Docker image can bundle Oracle Instant Client so
`oracledb` thick mode works against older Oracle servers (e.g. 11g / early 12c).

## License

Oracle Instant Client is distributed under Oracle's license. You must accept
Oracle's terms before downloading. Do **not** commit the Instant Client zip or
extracted libraries to git (they are gitignored).

## Install into the build context

1. Download **Instant Client Basic Light** (or Basic) for Linux x86-64 from Oracle,
   matching a recent 19c/21c/23ai Instant Client release.
2. Either:
   - Extract into `backend/vendor/oracle/instantclient/` so that
     `libclntsh.so*` (and related `.so` files) sit directly in that directory, or
   - Place the zip as `backend/vendor/oracle/instantclient-basiclite-linux.x64-*.zip`
     (the Dockerfile will unzip it at build time).
3. Rebuild:

```bash
docker compose --profile real-tools build internal-api-platform
```

The image sets:

- `ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient`
- `LD_LIBRARY_PATH=/opt/oracle/instantclient`

## Runtime behavior

- If Instant Client libraries are present, the platform process initializes thick
  mode once at startup (`oracledb.init_oracle_client`).
- If they are absent (local venv / image built without vendor files), the platform
  stays in **thin** mode. Bases with `oracle_client_mode: thick` will fail closed
  with a clear configuration error instead of silently falling back.
- `api-server` and `agent-worker` images do **not** include Instant Client.

## Topology knobs

See comments in `backend/config/internal_platform_topology.example.yaml`:

- `oracle_client_mode`: `auto` | `thin` | `thick`
- `oracle_compat`: `modern` (FETCH FIRST) | `legacy` (ROWNUM)
- `use_sid`: use SID instead of service name when building the DSN
- `connect_descriptor`: optional full connect descriptor / TNS string
