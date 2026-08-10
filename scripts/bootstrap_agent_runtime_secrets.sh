#!/bin/sh
set -eu

target_dir=${1:-}
if [ -z "$target_dir" ] || [ "${target_dir#/}" = "$target_dir" ]; then
  echo "usage: $0 /absolute/secret/directory" >&2
  exit 2
fi

umask 077
mkdir -p "$target_dir"

private_key="$target_dir/runtime-grant-private.pem"
public_key="$target_dir/runtime-grant-public.pem"
mcp_key="$target_dir/runtime-tool-mcp-signing-key"
probe_token="$target_dir/model-probe-auth-token"

for path in "$private_key" "$public_key" "$mcp_key" "$probe_token"; do
  if [ -e "$path" ]; then
    echo "refusing to overwrite existing secret: $path" >&2
    exit 1
  fi
done

openssl genpkey -algorithm ED25519 -out "$private_key"
openssl pkey -in "$private_key" -pubout -out "$public_key"
openssl rand -base64 48 | tr -d '\n' > "$mcp_key"
openssl rand -base64 48 | tr -d '\n' > "$probe_token"
chmod 0600 "$private_key" "$public_key" "$mcp_key" "$probe_token"

echo "Agent Runtime secret files created in $target_dir"
