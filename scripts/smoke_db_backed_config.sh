#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
ADMIN_USER_ID="${ADMIN_USER_ID:-local-user}"
AGENT_USER_ID="${AGENT_USER_ID:-local-user}"
PROJECT_CODE="${PROJECT_CODE:-default}"
CONVERSATION_ID="${CONVERSATION_ID:-smoke-db-backed-config}"
SECRET_CODE="${SECRET_CODE:-deepseek_api_key}"
REAL_CLAUDE="${REAL_CLAUDE:-false}"
SMOKE_BUILD="${SMOKE_BUILD:-true}"
SMOKE_RUN_ID="${SMOKE_RUN_ID:-$(date +%Y%m%d%H%M%S)}"
SMOKE_SECRET_VALUE="${SMOKE_SECRET_VALUE:-smoke-local-secret-not-real}"
MAX_POLLS="${MAX_POLLS:-60}"
POLL_SECONDS="${POLL_SECONDS:-2}"

if [[ "$REAL_CLAUDE" == "true" ]]; then
  if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
    echo "REAL_CLAUDE=true requires DEEPSEEK_API_KEY. The script will not prompt or print it."
    exit 2
  fi
  SMOKE_SECRET_VALUE="$DEEPSEEK_API_KEY"
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

json_file="$tmp_dir/payload.json"
response_file="$tmp_dir/response.json"

run_curl() {
  curl --noproxy '*' -fsS "$@"
}

post_json() {
  local path="$1"
  run_curl -X POST "$API_BASE_URL$path" \
    -H 'content-type: application/json' \
    -H "x-admin-user-id: $ADMIN_USER_ID" \
    --data-binary @"$json_file" > "$response_file"
}

assert_json() {
  python3 - "$response_file" "$@" <<'PY'
import json
import sys

path = sys.argv[1]
expr = sys.argv[2]
message = sys.argv[3]
data = json.load(open(path, encoding="utf-8"))
if not eval(expr, {"data": data}):
    raise SystemExit(message + "\nResponse: " + json.dumps(data, ensure_ascii=False))
PY
}

assert_no_secret() {
  if grep -Fq "$SMOKE_SECRET_VALUE" "$response_file"; then
    echo "Secret value leaked in response for $1"
    exit 3
  fi
}

echo "==> Starting Docker Compose services"
(
  cd "$ROOT_DIR"
  compose_args=(up -d)
  if [[ "$SMOKE_BUILD" == "true" ]]; then
    compose_args+=(--build)
  fi
  compose_args+=(postgres rabbitmq api-server agent-worker)
  APP_CONFIG_MASTER_KEY="${APP_CONFIG_MASTER_KEY:-local-dev-config-master-key}" \
  FEATURE_REAL_CLAUDE="$REAL_CLAUDE" \
  FEATURE_REAL_INTERNAL_TOOLS="${FEATURE_REAL_INTERNAL_TOOLS:-false}" \
  docker compose "${compose_args[@]}"
)

echo "==> Waiting for api-server readiness"
for _ in $(seq 1 "$MAX_POLLS"); do
  if run_curl "$API_BASE_URL/api/ready" > "$response_file" 2>/dev/null; then
    break
  fi
  sleep "$POLL_SECONDS"
done
assert_json "data.get('database') is True" "api-server database is not ready"

echo "==> Creating Web-managed secret $SECRET_CODE"
python3 - "$json_file" "$SECRET_CODE" "$SMOKE_SECRET_VALUE" <<'PY'
import json
import sys

_, path, code, value = sys.argv
json.dump(
    {"code": code, "value": value, "purpose": "compose-smoke"},
    open(path, "w", encoding="utf-8"),
    ensure_ascii=False,
)
PY
post_json "/api/platform/secrets"
assert_no_secret "secret create"
assert_json "data['secret']['secret_ref'] == 'secret://platform/' + data['secret']['code']" "secret_ref missing"
echo "    secret_ref=$(python3 - "$response_file" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['secret']['secret_ref'])
PY
)"

write_runtime_value() {
  local key="$1"
  local value="$2"
  python3 - "$json_file" "$key" "$value" <<'PY'
import json
import sys

_, path, key, value = sys.argv
try:
    parsed = int(value)
except ValueError:
    if value.lower() == "true":
        parsed = True
    elif value.lower() == "false":
        parsed = False
    else:
        parsed = value
json.dump({"key": key, "value": parsed}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
PY
  post_json "/api/platform/runtime-config/values"
  assert_no_secret "runtime value $key"
}

write_runtime_secret() {
  local key="$1"
  local ref="$2"
  python3 - "$json_file" "$key" "$ref" <<'PY'
import json
import sys

_, path, key, ref = sys.argv
json.dump({"key": key, "secret_ref": ref}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
PY
  post_json "/api/platform/runtime-config/values"
  assert_no_secret "runtime secret $key"
}

echo "==> Writing DB-backed runtime config"
write_runtime_value "FEATURE_REAL_CLAUDE" "$REAL_CLAUDE"
write_runtime_value "ANTHROPIC_BASE_URL" "https://api.deepseek.com/anthropic"
write_runtime_value "ANTHROPIC_MODEL" "deepseek-v4-pro[1m]"
write_runtime_secret "ANTHROPIC_API_KEY" "secret://platform/$SECRET_CODE"
write_runtime_value "AGENT_MAX_TURNS" "12"

echo "==> Checking runtime config snapshot"
run_curl "$API_BASE_URL/api/platform/runtime-config/snapshot?service_name=agent-worker" > "$response_file"
assert_no_secret "runtime snapshot"
assert_json "'ANTHROPIC_API_KEY' in data['snapshot']['effective_masked']" "ANTHROPIC_API_KEY missing from snapshot"

echo "==> Restarting api-server and agent-worker to apply startup overlay"
(
  cd "$ROOT_DIR"
  APP_CONFIG_MASTER_KEY="${APP_CONFIG_MASTER_KEY:-local-dev-config-master-key}" \
  docker compose restart api-server agent-worker >/dev/null
)

echo "==> Waiting for DB-backed ready state"
for _ in $(seq 1 "$MAX_POLLS"); do
  if run_curl "$API_BASE_URL/api/ready" > "$response_file" 2>/dev/null; then
    if python3 - "$response_file" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
raise SystemExit(0 if data.get("runtime_config", {}).get("source") == "database" else 1)
PY
    then
      break
    fi
  fi
  sleep "$POLL_SECONDS"
done
assert_no_secret "ready"
assert_json "data['runtime_config']['source'] == 'database'" "runtime_config.source is not database"
assert_json "data['runtime_config']['degraded'] is False" "runtime_config is degraded"
echo "    runtime_config=$(python3 - "$response_file" <<'PY'
import json, sys
rc = json.load(open(sys.argv[1], encoding='utf-8'))['runtime_config']
print(f"source={rc['source']} revision={rc['revision']} hash={rc['config_hash'][:12]}")
PY
)"

echo "==> Creating smoke Agent job"
python3 - "$json_file" "$AGENT_USER_ID" "$CONVERSATION_ID" "$PROJECT_CODE" "$SMOKE_RUN_ID" <<'PY'
import json
import sys

_, path, user_id, conversation_id, project_code, run_id = sys.argv
json.dump(
    {
        "message": "合成测试：请生成一份只读诊断 smoke 报告，不要访问真实业务数据。",
        "user_id": user_id,
        "conversation_id": f"{conversation_id}-{run_id}",
        "project_code": project_code,
        "idempotency_key": f"smoke-db-backed-config-compose-{run_id}",
    },
    open(path, "w", encoding="utf-8"),
    ensure_ascii=False,
)
PY
run_curl -X POST "$API_BASE_URL/api/agent/jobs" \
  -H 'content-type: application/json' \
  --data-binary @"$json_file" > "$response_file"
job_id="$(python3 - "$response_file" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['job_id'])
PY
)"
echo "    job_id=$job_id"

echo "==> Polling job"
for _ in $(seq 1 "$MAX_POLLS"); do
  run_curl "$API_BASE_URL/api/agent/jobs/$job_id" > "$response_file"
  status="$(python3 - "$response_file" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding='utf-8'))
job = data.get('job', data)
if 'status' not in job:
    print(json.dumps(data, ensure_ascii=False))
    raise SystemExit(2)
print(job['status'])
PY
)"
  echo "    status=$status"
  case "$status" in
    SUCCEEDED) break ;;
    FAILED|TIMEOUT|CANCELLED) cat "$response_file"; echo; exit 4 ;;
  esac
  sleep "$POLL_SECONDS"
done
assert_json "data.get('job', data)['status'] == 'SUCCEEDED'" "job did not succeed"

echo "==> Checking steps"
run_curl "$API_BASE_URL/api/agent/jobs/$job_id/steps" > "$response_file"
assert_no_secret "steps"
assert_json "len(data['steps']) > 0" "steps are empty"

echo "==> Checking tool calls"
run_curl "$API_BASE_URL/api/agent/jobs/$job_id/tool-calls" > "$response_file"
assert_no_secret "tool calls"
python3 - "$response_file" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"    tool_calls={len(data.get('tool_calls', []))}")
PY

echo "==> Smoke complete"
echo "    mode=$( [[ "$REAL_CLAUDE" == "true" ]] && echo real-claude || echo stub-claude )"
echo "    run_id=$SMOKE_RUN_ID"
echo "    job_id=$job_id"
echo "    secret value was not printed; API responses were checked for leakage"
