#!/usr/bin/env bash
set -euo pipefail

PROFILE=agent-test-data
REAL_TOOLS_PROFILE=real-tools

DATA_SERVICES=(
  agent-test-mysql
  agent-test-sqlserver
  agent-test-redis-mysql
  agent-test-redis-sqlserver
)

RESET_SERVICES=(
  "${DATA_SERVICES[@]}"
  agent-test-data-seeder
)

TEST_VOLUMES=(
  enterprise_agent_agent_test_mysql_data
  enterprise_agent_agent_test_sqlserver_data
  enterprise_agent_agent_test_redis_mysql_data
  enterprise_agent_agent_test_redis_sqlserver_data
)

usage() {
  cat <<'USAGE'
Usage:
  scripts/agent_test_data.sh up
  scripts/agent_test_data.sh seed
  scripts/agent_test_data.sh verify
  scripts/agent_test_data.sh reset --yes

Commands:
  up       Start four data services, wait for health, seed, then verify.
  seed     Restore the deterministic DB and Redis fixture baseline.
  verify   Verify direct data sources and Internal API Platform routing.
  reset    Stop test services and delete only the four allowlisted test volumes.
USAGE
}

compose() {
  docker compose "$@"
}

warn_arch() {
  case "$(uname -m)" in
    arm64|aarch64)
      echo "WARNING: SQL Server is configured as linux/amd64 on ARM64; full success still requires its health check to pass." >&2
      ;;
  esac
}

config_check() {
  compose --profile "${PROFILE}" config --quiet
}

wait_service_healthy() {
  local service="$1"
  local container_id=""
  local status=""
  local attempts=0
  while [ "${attempts}" -lt 120 ]; do
    container_id="$(compose ps -q "${service}")"
    if [ -n "${container_id}" ]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container_id}")"
      if [ "${status}" = "healthy" ]; then
        echo "${service}: healthy"
        return 0
      fi
    fi
    attempts=$((attempts + 1))
    sleep 5
  done
  echo "${service}: did not become healthy; last status=${status:-missing}" >&2
  if [ "${service}" = "agent-test-sqlserver" ]; then
    echo "SQL Server failed. On ARM64, use an x86-64 Docker host if linux/amd64 emulation cannot pass health checks." >&2
  fi
  return 1
}

wait_all_healthy() {
  local failed=0
  for service in "${DATA_SERVICES[@]}"; do
    wait_service_healthy "${service}" || failed=1
  done
  return "${failed}"
}

cmd_up() {
  warn_arch
  config_check
  compose --profile "${PROFILE}" up -d "${DATA_SERVICES[@]}"
  wait_all_healthy
  cmd_seed
  cmd_verify
}

cmd_seed() {
  compose --profile "${PROFILE}" run --rm agent-test-data-seeder \
    python -m app.agent_test_data.seeder seed
}

cmd_verify_direct() {
  compose --profile "${PROFILE}" run --rm agent-test-data-seeder \
    python -m app.agent_test_data.seeder verify
}

cmd_verify_platform() {
  compose --profile "${PROFILE}" --profile "${REAL_TOOLS_PROFILE}" up -d internal-api-platform
  compose --profile "${PROFILE}" --profile "${REAL_TOOLS_PROFILE}" exec -T internal-api-platform \
    python -m app.agent_test_data.platform_verify
}

cmd_verify() {
  cmd_verify_direct
  cmd_verify_platform
}

cmd_reset() {
  if [ "${1:-}" != "--yes" ]; then
    echo "Refusing to reset without explicit --yes." >&2
    usage
    return 2
  fi
  compose --profile "${PROFILE}" rm -sfv "${RESET_SERVICES[@]}"
  local volume=""
  for volume in "${TEST_VOLUMES[@]}"; do
    docker volume rm "${volume}" >/dev/null 2>&1 || true
    echo "removed volume if present: ${volume}"
  done
}

main() {
  local command="${1:-}"
  case "${command}" in
    up)
      cmd_up
      ;;
    seed)
      cmd_seed
      ;;
    verify)
      cmd_verify
      ;;
    reset)
      shift
      cmd_reset "$@"
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      usage
      return 2
      ;;
  esac
}

main "$@"
