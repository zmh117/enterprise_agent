#!/usr/bin/env bash
# =============================================================================
# agent_test_data.sh — 本地 Agent 多库/Redis 测试数据环境入口
#
# 做什么
#   启动 Compose profile `agent-test-data` 下的隔离测试拓扑：
#     - agent-test-mysql          MySQL 8（模拟一个测试基地）
#     - agent-test-sqlserver      SQL Server 2022（另一个测试基地，linux/amd64）
#     - agent-test-redis-mysql    对应 MySQL 基地的 Redis
#     - agent-test-redis-sqlserver对应 SQL Server 基地的 Redis
#   再用 seeder 写入确定性 MES 表结构 + 正常/异常样例，以及故意不一致的 Redis 缓存，
#   最后校验「直连数据源」和「Internal API Platform 路由」是否通。
#
# 不做什么
#   - 不会启动默认的 api-server / agent-worker / postgres / rabbitmq
#   - 不会碰生产样例拓扑（sanjiu/mmk 等）；环境码是 agent_test
#   - Oracle 不在本 profile 内
#
# 前置
#   - 在仓库根目录执行（依赖同目录 docker-compose.yml）
#   - 已安装 Docker Compose
#   - ARM64 Mac：SQL Server 走 amd64 模拟，首次较慢，健康检查可能失败
#
# 常用用法
#   scripts/agent_test_data.sh up              # 一键：启动 → 等健康 → 播种 → 校验
#   scripts/agent_test_data.sh seed            # 仅重新播种（服务已在跑时）
#   scripts/agent_test_data.sh verify          # 仅校验直连 + platform 路由
#   scripts/agent_test_data.sh reset --yes     # 停服务并删除四个测试专用卷（需 --yes）
#   scripts/agent_test_data.sh -h              # 简短帮助
#
# 典型联调顺序
#   1) scripts/agent_test_data.sh up
#   2) 另开终端启动 real-tools / api-server / worker（按 README）
#   3) 用 Agent 工具查 agent_test 环境下的 MySQL/SQL Server 基地
#   4) 数据脏了或想回到基线：scripts/agent_test_data.sh seed
#   5) 彻底清空：scripts/agent_test_data.sh reset --yes
#
# 注意
#   - seed 可重复执行；reset 会删卷，下次 up 需重新拉起并播种
#   - reset 只删脚本里写死的四个 allowlist 卷名，不会动主库/RabbitMQ 卷
# =============================================================================
set -euo pipefail

PROFILE=agent-test-data
REAL_TOOLS_PROFILE=real-tools

# 四个持久化数据服务（不含一次性 seeder）
DATA_SERVICES=(
  agent-test-mysql
  agent-test-sqlserver
  agent-test-redis-mysql
  agent-test-redis-sqlserver
)

# reset 时一并移除的服务（含 seeder 容器）
RESET_SERVICES=(
  "${DATA_SERVICES[@]}"
  agent-test-data-seeder
)

# Compose 里声明的命名卷（name: enterprise_agent_agent_test_*）
# reset --yes 只允许删除这些卷，防止误删主环境数据
TEST_VOLUMES=(
  enterprise_agent_agent_test_mysql_data
  enterprise_agent_agent_test_sqlserver_data
  enterprise_agent_agent_test_redis_mysql_data
  enterprise_agent_agent_test_redis_sqlserver_data
)

usage() {
  cat <<'USAGE'
用法:
  scripts/agent_test_data.sh up
  scripts/agent_test_data.sh seed
  scripts/agent_test_data.sh verify
  scripts/agent_test_data.sh reset --yes

命令:
  up       启动四个数据服务，等待健康检查，播种，再校验。
  seed     恢复确定性的数据库与 Redis 测试数据基线。
  verify   校验直连数据源，以及 Internal API Platform 路由。
  reset    停止测试服务，并仅删除白名单内的四个测试卷。
USAGE
}

compose() {
  docker compose "$@"
}

# ARM64 上 SQL Server 只能 amd64 模拟，提前提示，避免误以为脚本坏了
warn_arch() {
  case "$(uname -m)" in
    arm64|aarch64)
      echo "WARNING: SQL Server is configured as linux/amd64 on ARM64; full success still requires its health check to pass." >&2
      ;;
  esac
}

# 先校验 compose 配置可解析，再 up，失败更早暴露
config_check() {
  compose --profile "${PROFILE}" config --quiet
}

# 轮询单服务 healthcheck，最多约 10 分钟（120 * 5s）
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

# 一键：启动四服务 → 等健康 → seed → verify
cmd_up() {
  warn_arch
  config_check
  compose --profile "${PROFILE}" up -d "${DATA_SERVICES[@]}"
  wait_all_healthy
  cmd_seed
  cmd_verify
}

# 幂等播种：重建 MES 表/样例行与两套 Redis fixture 基线
cmd_seed() {
  compose --profile "${PROFILE}" run --rm agent-test-data-seeder \
    python -m app.agent_test_data.seeder seed
}

# 直连 MySQL / SQL Server / Redis 校验 fixture 是否符合预期
cmd_verify_direct() {
  compose --profile "${PROFILE}" run --rm agent-test-data-seeder \
    python -m app.agent_test_data.seeder verify
}

# 拉起 internal-api-platform，校验拓扑路由能打到本测试数据源。
# 当前镜像可能偏旧（缺 agent_test_data / SchemaInspector 新 API）。
# 全量 --build 依赖 apt，网络不稳时易失败；verify 前把本地源码同步进容器。
cmd_verify_platform() {
  compose --profile "${PROFILE}" --profile "${REAL_TOOLS_PROFILE}" up -d internal-api-platform
  local container_id=""
  container_id="$(compose --profile "${PROFILE}" --profile "${REAL_TOOLS_PROFILE}" ps -q internal-api-platform)"
  if [ -z "${container_id}" ]; then
    echo "internal-api-platform container not found" >&2
    return 1
  fi
  # 目标目录已存在时，docker cp dir dest 会嵌套成 dest/dir；先删再拷。
  compose --profile "${PROFILE}" --profile "${REAL_TOOLS_PROFILE}" exec -T internal-api-platform \
    rm -rf /app/backend/app/agent_test_data /app/backend/app/modules/internal_api_platform /app/backend/app/shared
  docker cp backend/app/agent_test_data "${container_id}:/app/backend/app/agent_test_data"
  docker cp backend/app/modules/internal_api_platform "${container_id}:/app/backend/app/modules/internal_api_platform"
  docker cp backend/app/shared "${container_id}:/app/backend/app/shared"
  # config 已是 compose 只读挂载，无需 docker cp
  compose --profile "${PROFILE}" --profile "${REAL_TOOLS_PROFILE}" exec -T internal-api-platform \
    python -m app.agent_test_data.platform_verify
}

cmd_verify() {
  cmd_verify_direct
  cmd_verify_platform
}

# 停测试服务并只删 allowlist 卷；必须显式传 --yes
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
