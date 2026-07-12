#!/usr/bin/env bash
# PostgreSQL 16 -> 18 / RabbitMQ 3 -> 4 的本地 Compose 安全升级入口。
# 所有子命令都保留旧卷和备份；本脚本不包含 volume rm、down -v 或 queue purge。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${COMPOSE_INFRA_BACKUP_ROOT:-${ROOT_DIR}/.local/compose-infra-upgrade}"
POSTGRES_USER="${POSTGRES_USER:-enterprise_agent}"
POSTGRES_DB="${POSTGRES_DB:-enterprise_agent}"
MANAGED_QUEUES=(
  "${AGENT_JOB_QUEUE:-agent.job.queue}"
  "${AGENT_RETRY_QUEUE:-agent.job.retry.queue}"
  "${AGENT_DEAD_QUEUE:-agent.job.dead.queue}"
)

usage() {
  cat <<'USAGE'
用法:
  scripts/compose_infra_upgrade.sh preflight [--require-empty-rabbitmq]
  scripts/compose_infra_upgrade.sh ensure-rabbitmq-empty
  scripts/compose_infra_upgrade.sh backup-postgres [backup-dir]
  scripts/compose_infra_upgrade.sh restore-postgres18 <backup-dir>
  scripts/compose_infra_upgrade.sh verify <backup-dir>

说明:
  preflight             只读检查实际镜像、磁盘、PostgreSQL 和 RabbitMQ。
  ensure-rabbitmq-empty 确认三个 Agent 队列没有 ready/unacked 消息。
  backup-postgres       生成 custom-format 数据库备份、globals 和迁移前指标。
  restore-postgres18    仅允许恢复到 PostgreSQL 18；会重建目标数据库但不删卷。
  verify                比较迁移前后数据指标并检查 PostgreSQL 18/RabbitMQ 4。

默认备份目录:
  .local/compose-infra-upgrade/<UTC timestamp>
USAGE
}

compose() {
  (cd "$ROOT_DIR" && docker compose "$@")
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令: $1" >&2
    exit 2
  }
}

service_container_id() {
  local service="$1"
  local container_id
  container_id="$(compose ps -q "$service")"
  if [[ -z "$container_id" ]]; then
    echo "服务未运行: $service" >&2
    return 1
  fi
  printf '%s\n' "$container_id"
}

image_report() {
  local service="$1"
  local container_id image_id image_name repo_digests
  container_id="$(service_container_id "$service")"
  image_id="$(docker inspect -f '{{.Image}}' "$container_id")"
  image_name="$(docker inspect -f '{{.Config.Image}}' "$container_id")"
  repo_digests="$(docker image inspect -f '{{json .RepoDigests}}' "$image_id" 2>/dev/null || printf '[]')"
  printf '%s image=%s image_id=%s repo_digests=%s\n' \
    "$service" "$image_name" "$image_id" "$repo_digests"
}

mount_report() {
  local service="$1"
  local container_id
  container_id="$(service_container_id "$service")"
  echo "$service mounts:"
  docker inspect -f '{{range .Mounts}}  type={{.Type}} name={{.Name}} source={{.Source}} destination={{.Destination}}{{println}}{{end}}' \
    "$container_id"
}

postgres_exec() {
  compose exec -T postgres "$@"
}

rabbitmq_exec() {
  compose exec -T rabbitmq "$@"
}

postgres_version() {
  postgres_exec psql -X -A -t -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "select current_setting('server_version');"
}

rabbitmq_version() {
  rabbitmq_exec rabbitmq-diagnostics -q server_version
}

queue_rows() {
  rabbitmq_exec rabbitmqctl -q list_queues name messages_ready messages_unacknowledged
}

print_queue_rows() {
  local rows
  rows="$(queue_rows)"
  echo "RabbitMQ managed queues (missing queue means zero/not declared):"
  local managed name ready unacked found
  for managed in "${MANAGED_QUEUES[@]}"; do
    found="false"
    while read -r name ready unacked; do
      [[ -z "${name:-}" ]] && continue
      if [[ "$name" == "$managed" ]]; then
        printf '  %s ready=%s unacked=%s\n' "$name" "$ready" "$unacked"
        found="true"
      fi
    done <<< "$rows"
    if [[ "$found" == "false" ]]; then
      printf '  %s ready=0 unacked=0 (not declared)\n' "$managed"
    fi
  done
}

ensure_rabbitmq_empty() {
  local rows managed name ready unacked failed
  rows="$(queue_rows)"
  failed=0
  print_queue_rows
  for managed in "${MANAGED_QUEUES[@]}"; do
    while read -r name ready unacked; do
      [[ "$name" == "$managed" ]] || continue
      if (( ready > 0 || unacked > 0 )); then
        echo "拒绝切换 RabbitMQ: $name 仍有 ready=$ready unacked=$unacked" >&2
        failed=1
      fi
    done <<< "$rows"
  done
  if (( failed != 0 )); then
    echo "请先停止入口、等待 worker 完成任务，再重新检查；脚本不会 purge 队列。" >&2
    return 3
  fi
  echo "RabbitMQ 切换保护通过: 受管队列均已排空。"
}

collect_db_metrics() {
  local output_file="$1"
  local tmp_file="${output_file}.tmp"
  postgres_exec psql -X -A -t -F $'\t' -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$tmp_file" <<'SQL'
SELECT 'server_version_num', current_setting('server_version_num');
SELECT 'data_directory', current_setting('data_directory');
SELECT 'public_table_count', count(*)::text
FROM pg_tables
WHERE schemaname = 'public';
SELECT format(
  'SELECT %L, count(*)::text FROM %I.%I;',
  'table.' || tablename,
  schemaname,
  tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN (
    'agent_session',
    'agent_job',
    'agent_message',
    'agent_step',
    'agent_tool_call',
    'agent_artifact',
    'audit_event',
    'platform_environment',
    'platform_base',
    'platform_workshop',
    'platform_resource_binding',
    'platform_access_grant',
    'platform_secret',
    'platform_secret_version',
    'platform_runtime_config_definition',
    'platform_runtime_config_value'
  )
ORDER BY tablename
\gexec
SELECT format(
  'SELECT %L, coalesce(max(revision), 0)::text FROM %I.%I;',
  'revision.' || tablename,
  schemaname,
  tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN (
    'platform_environment',
    'platform_base',
    'platform_workshop',
    'platform_resource_binding',
    'platform_access_grant',
    'platform_secret',
    'platform_runtime_config_definition',
    'platform_runtime_config_value'
  )
ORDER BY tablename
\gexec
SQL
  LC_ALL=C sort "$tmp_file" > "$output_file"
  rm -f "$tmp_file"
}

checksum_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file"
  else
    shasum -a 256 "$file"
  fi
}

write_metadata() {
  local backup_dir="$1"
  {
    printf 'created_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'postgres_version=%s\n' "$(postgres_version)"
    image_report postgres
    mount_report postgres
    checksum_file "$backup_dir/globals.sql"
    checksum_file "$backup_dir/enterprise_agent.dump"
    checksum_file "$backup_dir/before-metrics.tsv"
  } > "$backup_dir/metadata.txt"
}

preflight() {
  local require_empty="${1:-}"
  require_command docker
  require_command df
  compose config --quiet
  mkdir -p "$BACKUP_ROOT"
  echo "Backup root: $BACKUP_ROOT"
  df -Pk "$BACKUP_ROOT" | tail -n 1
  image_report postgres
  image_report rabbitmq
  mount_report postgres
  mount_report rabbitmq
  echo "PostgreSQL version: $(postgres_version)"
  postgres_exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"
  echo "RabbitMQ version: $(rabbitmq_version)"
  rabbitmq_exec rabbitmq-diagnostics -q ping
  echo "RabbitMQ feature flags:"
  rabbitmq_exec rabbitmqctl -q list_feature_flags name state
  print_queue_rows
  if [[ "$require_empty" == "--require-empty-rabbitmq" ]]; then
    ensure_rabbitmq_empty
  elif [[ -n "$require_empty" ]]; then
    echo "未知 preflight 参数: $require_empty" >&2
    return 2
  fi
}

backup_postgres() {
  local backup_dir="${1:-${BACKUP_ROOT}/$(date -u +%Y%m%dT%H%M%SZ)}"
  local tmp_dir="${backup_dir}.tmp"
  if [[ -e "$backup_dir" || -e "$tmp_dir" ]]; then
    echo "备份目录已存在，拒绝覆盖: $backup_dir" >&2
    return 2
  fi
  mkdir -p "$tmp_dir"
  echo "正在导出 PostgreSQL，目标目录: $backup_dir"
  postgres_exec pg_dumpall -U "$POSTGRES_USER" --globals-only --no-role-passwords \
    > "$tmp_dir/globals.sql"
  postgres_exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --format=custom --no-owner --no-acl > "$tmp_dir/enterprise_agent.dump"
  collect_db_metrics "$tmp_dir/before-metrics.tsv"
  write_metadata "$tmp_dir"
  mv "$tmp_dir" "$backup_dir"
  echo "PostgreSQL 逻辑备份完成: $backup_dir"
  echo "BACKUP_DIR=$backup_dir"
  echo "恢复前请保留该目录和当前旧容器/卷。"
}

verify_backup_files() {
  local backup_dir="$1"
  for name in enterprise_agent.dump before-metrics.tsv metadata.txt; do
    if [[ ! -s "$backup_dir/$name" ]]; then
      echo "备份文件缺失或为空: $backup_dir/$name" >&2
      return 2
    fi
  done
}

run_migrations_and_seed() {
  compose run --rm --no-deps \
    -e APP_STARTUP_MIGRATE=true \
    -e SEED_LOCAL_CONFIG=true \
    api-server python -c \
    "from app.bootstrap import build_api_container; from app.shared.config import load_settings; c=build_api_container(load_settings(), migrate=True, seed=True); c.database.close()"
}

restore_postgres18() {
  local backup_dir="${1:-}"
  if [[ -z "$backup_dir" ]]; then
    echo "restore-postgres18 必须提供备份目录" >&2
    return 2
  fi
  verify_backup_files "$backup_dir"
  local version data_directory
  version="$(postgres_version)"
  if [[ "$version" != 18.* ]]; then
    echo "拒绝恢复: 当前 PostgreSQL 不是 18.x，而是 $version" >&2
    return 3
  fi
  data_directory="$(postgres_exec psql -X -A -t -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "show data_directory;")"
  if [[ "$data_directory" != /var/lib/postgresql/18/* ]]; then
    echo "拒绝恢复: PostgreSQL 18 data_directory 不符合预期: $data_directory" >&2
    return 3
  fi
  echo "将恢复到 PostgreSQL $version ($data_directory)"
  echo "目标数据库 $POSTGRES_DB 会被重建；命名卷和备份不会被删除。"
  postgres_exec dropdb -U "$POSTGRES_USER" --maintenance-db=postgres --if-exists --force "$POSTGRES_DB"
  postgres_exec createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"
  postgres_exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --exit-on-error --no-owner --no-acl < "$backup_dir/enterprise_agent.dump"
  run_migrations_and_seed
  collect_db_metrics "$backup_dir/after-metrics.tsv"
  echo "PostgreSQL 18 恢复和 migration/seed 完成。"
  echo "下一步: scripts/compose_infra_upgrade.sh verify '$backup_dir'"
}

verify_migration() {
  local backup_dir="${1:-}"
  if [[ -z "$backup_dir" ]]; then
    echo "verify 必须提供备份目录" >&2
    return 2
  fi
  verify_backup_files "$backup_dir"
  local version data_directory rabbit_version
  version="$(postgres_version)"
  data_directory="$(postgres_exec psql -X -A -t -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "show data_directory;")"
  rabbit_version="$(rabbitmq_version)"
  [[ "$version" == 18.* ]] || { echo "PostgreSQL 主版本不是 18: $version" >&2; return 3; }
  [[ "$data_directory" == /var/lib/postgresql/18/* ]] || {
    echo "PostgreSQL data_directory 错误: $data_directory" >&2
    return 3
  }
  [[ "$rabbit_version" == 4.* ]] || { echo "RabbitMQ 主版本不是 4: $rabbit_version" >&2; return 3; }
  collect_db_metrics "$backup_dir/after-metrics.tsv"
  python3 - "$backup_dir/before-metrics.tsv" "$backup_dir/after-metrics.tsv" <<'PY'
import sys


def load(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with open(path, encoding="utf-8") as stream:
        for raw_line in stream:
            key, value = raw_line.rstrip("\n").split("\t", 1)
            result[key] = value
    return result


before = load(sys.argv[1])
after = load(sys.argv[2])
errors: list[str] = []
for key, before_value in before.items():
    if key == "public_table_count" or key.startswith("table."):
        after_value = after.get(key)
        if after_value != before_value:
            errors.append(f"{key}: before={before_value} after={after_value or '<missing>'}")
    elif key.startswith("revision."):
        after_value = after.get(key)
        if after_value is None or int(after_value) < int(before_value):
            errors.append(f"{key}: revision regressed before={before_value} after={after_value or '<missing>'}")
        elif int(after_value) > int(before_value):
            print(f"migration/seed advanced {key}: {before_value} -> {after_value}")

if errors:
    raise SystemExit("Database migration metrics failed:\n" + "\n".join(errors))
print("Database table counts match and configuration revisions did not regress.")
PY
  postgres_exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select 1;" >/dev/null
  rabbitmq_exec rabbitmq-diagnostics -q ping
  print_queue_rows
  image_report postgres
  image_report rabbitmq
  echo "基础设施迁移核验通过。"
}

main() {
  local command="${1:-}"
  case "$command" in
    preflight)
      shift
      preflight "${1:-}"
      ;;
    ensure-rabbitmq-empty)
      ensure_rabbitmq_empty
      ;;
    backup-postgres)
      backup_postgres "${2:-}"
      ;;
    restore-postgres18)
      restore_postgres18 "${2:-}"
      ;;
    verify)
      verify_migration "${2:-}"
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "未知命令: $command" >&2
      usage >&2
      return 2
      ;;
  esac
}

main "$@"
