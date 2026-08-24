#!/bin/sh
set -eu

fail() {
  printf '%s\n' "SECRET_FILE_NORMALIZATION_FAILED: $1" >&2
  exit 70
}

if [ "$#" -eq 0 ]; then
  fail "container command is missing"
fi

runtime_tmpdir=${TMPDIR:-/tmp}
case "$runtime_tmpdir" in
  /*) ;;
  *) fail "TMPDIR must be an absolute path" ;;
esac

target_dir=${runtime_tmpdir%/}/ea-secrets
if [ -L "$target_dir" ] || { [ -e "$target_dir" ] && [ ! -d "$target_dir" ]; }; then
  fail "runtime secret directory is invalid"
fi
umask 077
if ! mkdir -p "$target_dir" 2>/dev/null || ! chmod 700 "$target_dir" 2>/dev/null; then
  fail "runtime secret directory is not writable"
fi

secret_file_variables='
APP_CONFIG_MASTER_KEY_FILE
DELIVERY_WORKER_BOOTSTRAP_TOKEN_FILE
DINGTALK_RUNTIME_AUTH_TOKEN_FILE
DOCLING_SERVE_API_KEY_FILE
FILE_PROCESSING_WORKER_BOOTSTRAP_TOKEN_FILE
FILE_STORAGE_BOOTSTRAP_ACCESS_KEY_FILE
FILE_STORAGE_BOOTSTRAP_SECRET_KEY_FILE
FILE_WORKER_BOOTSTRAP_TOKEN_FILE
INITIAL_ADMIN_PASSWORD_FILE
MODEL_PROBE_AUTH_TOKEN_FILE
PRINCIPAL_JWKS_FILE
PRINCIPAL_JWT_PRIVATE_KEY_FILE
RUNTIME_GRANT_PRIVATE_KEY_FILE
RUNTIME_GRANT_PUBLIC_KEY_FILE
'

for variable_name in $secret_file_variables; do
  source_path=$(printenv "$variable_name" 2>/dev/null || true)
  if [ -z "$source_path" ]; then
    continue
  fi
  case "$source_path" in
    /*) ;;
    *) fail "$variable_name must reference an absolute path" ;;
  esac
  if [ ! -e "$source_path" ] && [ ! -L "$source_path" ]; then
    continue
  fi
  if [ -L "$source_path" ] || [ ! -f "$source_path" ] || [ ! -r "$source_path" ]; then
    fail "$variable_name must reference a readable regular non-symlink file"
  fi

  target_file=$target_dir/$variable_name
  temporary_file=$target_file.tmp.$$
  if [ -L "$target_file" ] || { [ -e "$target_file" ] && [ ! -f "$target_file" ]; }; then
    fail "$variable_name runtime target is invalid"
  fi
  if [ -e "$temporary_file" ] || [ -L "$temporary_file" ]; then
    fail "$variable_name temporary target already exists"
  fi
  if ! cp "$source_path" "$temporary_file" 2>/dev/null; then
    fail "$variable_name could not be copied"
  fi
  if ! chmod 400 "$temporary_file" 2>/dev/null; then
    fail "$variable_name permissions could not be restricted"
  fi
  if ! mv -f "$temporary_file" "$target_file" 2>/dev/null; then
    fail "$variable_name runtime target could not be installed"
  fi
  export "$variable_name=$target_file"
done

exec "$@"
