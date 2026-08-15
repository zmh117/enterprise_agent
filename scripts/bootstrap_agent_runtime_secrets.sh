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
probe_token="$target_dir/model-probe-auth-token"
principal_private_key="$target_dir/principal-jwt-private.pem"
principal_public_der="$target_dir/principal-jwt-public.der"
principal_jwks="$target_dir/principal-jwks.json"
file_worker_bootstrap_token="$target_dir/file-worker-bootstrap-token"
delivery_worker_bootstrap_token="$target_dir/delivery-worker-bootstrap-token"

for temporary_key in "$principal_public_der"; do
  if [ -e "$temporary_key" ]; then
    echo "refusing to use stale temporary key material: $temporary_key" >&2
    exit 1
  fi
done

if [ -e "$private_key" ] || [ -e "$public_key" ]; then
  if [ ! -e "$private_key" ] || [ ! -e "$public_key" ]; then
    echo "runtime grant key pair is incomplete; refusing to overwrite it" >&2
    exit 1
  fi
else
  openssl genpkey -algorithm ED25519 -out "$private_key"
  openssl pkey -in "$private_key" -pubout -out "$public_key"
fi

if [ ! -e "$probe_token" ]; then
  openssl rand -base64 48 | tr -d '\n' > "$probe_token"
fi

if [ -e "$principal_private_key" ] || [ -e "$principal_jwks" ]; then
  if [ ! -e "$principal_private_key" ] || [ ! -e "$principal_jwks" ]; then
    echo "Principal JWT key pair is incomplete; refusing to overwrite it" >&2
    exit 1
  fi
else
  openssl genpkey -algorithm ED25519 -out "$principal_private_key"
  openssl pkey -in "$principal_private_key" -pubout -outform DER -out "$principal_public_der"
  python3 - "$principal_public_der" "$principal_jwks" <<'PY'
import base64
import hashlib
import json
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_bytes()[-32:]
encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
core = {"crv": "Ed25519", "kty": "OKP", "x": encode(raw)}
thumbprint = json.dumps(core, sort_keys=True, separators=(",", ":")).encode("ascii")
jwk = {
    **core,
    "alg": "EdDSA",
    "use": "sig",
    "kid": encode(hashlib.sha256(thumbprint).digest()),
}
pathlib.Path(sys.argv[2]).write_text(
    json.dumps({"keys": [jwk]}, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
  rm -f "$principal_public_der"
fi

if [ ! -e "$file_worker_bootstrap_token" ]; then
  openssl rand -base64 48 | tr -d '\n' > "$file_worker_bootstrap_token"
fi

if [ ! -e "$delivery_worker_bootstrap_token" ]; then
  openssl rand -base64 48 | tr -d '\n' > "$delivery_worker_bootstrap_token"
fi

chmod 0600 "$private_key" "$public_key" "$probe_token"
chmod 0400 \
  "$principal_private_key" \
  "$file_worker_bootstrap_token" \
  "$delivery_worker_bootstrap_token"
chmod 0644 "$principal_jwks"

echo "Agent Runtime secret files are complete in $target_dir"
