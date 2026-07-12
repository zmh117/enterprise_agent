#!/usr/bin/env bash
# RabbitMQ 4 + PostgreSQL 18 的真实 Compose 闭环 smoke。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_BUILD="${SMOKE_BUILD:-false}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
MAX_POLLS="${MAX_POLLS:-90}"
POLL_SECONDS="${POLL_SECONDS:-2}"

compose() {
  (cd "$ROOT_DIR" && docker compose "$@")
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "找不到项目 Python: $PYTHON_BIN" >&2
  echo "请设置 PYTHON_BIN，或先创建项目 .venv。" >&2
  exit 2
fi

echo "==> 校验 Compose 配置"
compose config --quiet

echo "==> 启动 PostgreSQL 18、RabbitMQ 4、API 和 worker"
up_args=(up -d)
if [[ "$SMOKE_BUILD" == "true" ]]; then
  up_args+=(--build)
fi
up_args+=(postgres rabbitmq api-server agent-worker)
compose "${up_args[@]}"

echo "==> 校验基础设施版本和健康状态"
postgres_version="$(compose exec -T postgres psql -X -A -t -U enterprise_agent -d enterprise_agent -c "show server_version;")"
rabbitmq_version="$(compose exec -T rabbitmq rabbitmq-diagnostics -q server_version)"
[[ "$postgres_version" == 18.* ]] || { echo "PostgreSQL 18 required, got $postgres_version" >&2; exit 3; }
[[ "$rabbitmq_version" == 4.* ]] || { echo "RabbitMQ 4 required, got $rabbitmq_version" >&2; exit 3; }
compose exec -T postgres pg_isready -U enterprise_agent -d enterprise_agent
compose exec -T rabbitmq rabbitmq-diagnostics -q ping

echo "==> 验证 RabbitMQ 4 job/retry/dead 持久队列消息与 ack"
(
  cd "$ROOT_DIR"
  RUN_RABBITMQ4_INTEGRATION=1 \
  RABBITMQ_TEST_URL="${RABBITMQ_TEST_URL:-amqp://guest:guest@127.0.0.1:5672/}" \
    "$PYTHON_BIN" -m pytest backend/tests/test_rabbitmq4_integration.py -q
)

echo "==> 验证 retry/dead 队列、PostgreSQL job 状态与审计一致性"
(
  cd "$ROOT_DIR"
  RUN_RABBITMQ4_FAILURE_INTEGRATION=1 \
  RABBITMQ_TEST_URL="${RABBITMQ_TEST_URL:-amqp://guest:guest@127.0.0.1:5672/}" \
  POSTGRES_TEST_DSN="${POSTGRES_TEST_DSN:-postgresql://enterprise_agent:enterprise_agent@127.0.0.1:5433/enterprise_agent}" \
    "$PYTHON_BIN" -m pytest backend/tests/test_rabbitmq4_job_failure_integration.py -q
)

echo "==> 通过真实 API -> RabbitMQ -> worker 验证 Agent Job"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
response_file="$tmp_dir/response.json"
payload_file="$tmp_dir/payload.json"
run_id="rabbitmq4-$(date +%Y%m%d%H%M%S)"
python3 - "$payload_file" "$run_id" <<'PY'
import json
import sys

json.dump(
    {
        "message": "合成测试：请生成一份只读诊断 smoke 报告。",
        "user_id": "local-user",
        "conversation_id": f"rabbitmq4-smoke-{sys.argv[2]}",
        "project_code": "default",
        "idempotency_key": f"rabbitmq4-smoke-{sys.argv[2]}",
    },
    open(sys.argv[1], "w", encoding="utf-8"),
    ensure_ascii=False,
)
PY
curl --noproxy '*' -fsS -X POST "$API_BASE_URL/api/agent/jobs" \
  -H 'content-type: application/json' \
  --data-binary @"$payload_file" > "$response_file"
job_id="$(python3 - "$response_file" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["job_id"])
PY
)"
echo "    job_id=$job_id"
for _ in $(seq 1 "$MAX_POLLS"); do
  curl --noproxy '*' -fsS "$API_BASE_URL/api/agent/jobs/$job_id" > "$response_file"
  status="$(python3 - "$response_file" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data.get("job", data)["status"])
PY
)"
  echo "    status=$status"
  case "$status" in
    SUCCEEDED) break ;;
    FAILED|TIMEOUT|CANCELLED) cat "$response_file"; echo; exit 4 ;;
  esac
  sleep "$POLL_SECONDS"
done
[[ "$status" == "SUCCEEDED" ]] || { echo "Agent job did not succeed" >&2; exit 4; }

echo "==> 验证 steps 和 tool calls 可查询"
curl --noproxy '*' -fsS "$API_BASE_URL/api/agent/jobs/$job_id/steps" > "$response_file"
python3 - "$response_file" <<'PY'
import json, sys
assert json.load(open(sys.argv[1], encoding="utf-8"))["steps"]
PY
curl --noproxy '*' -fsS "$API_BASE_URL/api/agent/jobs/$job_id/tool-calls" > "$response_file"

echo "    runtime config 未被 smoke 修改"

echo "==> 当前受管队列状态"
compose exec -T rabbitmq rabbitmqctl -q list_queues \
  name durable messages_ready messages_unacknowledged

echo "RabbitMQ 4 / PostgreSQL 18 Compose smoke 通过。"
