#!/bin/sh
set -eu

target_dir=${1:-}
docker_acl=${2:-}
if [ -z "$target_dir" ] || [ "${target_dir#/}" = "$target_dir" ]; then
  echo "usage: $0 /absolute/secret/directory [--docker-acl]" >&2
  exit 2
fi
if [ -n "$docker_acl" ] && [ "$docker_acl" != "--docker-acl" ]; then
  echo "unsupported bootstrap option" >&2
  exit 2
fi
if [ "$docker_acl" = "--docker-acl" ] && ! command -v setfacl >/dev/null 2>&1; then
  echo "Docker file secrets require setfacl; install the Linux acl package" >&2
  exit 1
fi

umask 077
if [ -L "$target_dir" ]; then
  echo "secret directory must not be a symbolic link" >&2
  exit 1
fi
mkdir -p "$target_dir"
chmod 0700 "$target_dir"

private_key="$target_dir/runtime-grant-private.pem"
public_key="$target_dir/runtime-grant-public.pem"
probe_token="$target_dir/model-probe-auth-token"
principal_private_key="$target_dir/principal-jwt-private.pem"
principal_public_der="$target_dir/principal-jwt-public.der"
principal_jwks="$target_dir/principal-jwks.json"
file_worker_bootstrap_token="$target_dir/file-worker-bootstrap-token"
file_processing_worker_bootstrap_token="$target_dir/file-processing-worker-bootstrap-token"
delivery_worker_bootstrap_token="$target_dir/delivery-worker-bootstrap-token"
knowledge_bootstrap_token="$target_dir/knowledge-bootstrap-token"
docling_api_key="$target_dir/docling-api-key"
master_key="$target_dir/app-config-master-key"

# Validate metadata before generating anything; never rotate or print existing material.
for existing_file in "$private_key" "$public_key" "$probe_token" \
  "$principal_private_key" "$principal_jwks" "$file_worker_bootstrap_token" \
  "$file_processing_worker_bootstrap_token" "$delivery_worker_bootstrap_token" \
  "$knowledge_bootstrap_token" "$docling_api_key" "$master_key"; do
  if [ -L "$existing_file" ] || { [ -e "$existing_file" ] && { [ ! -f "$existing_file" ] || [ ! -s "$existing_file" ]; }; }; then
    echo "existing secret must be a nonempty regular file; initialization refused" >&2
    exit 1
  fi
done

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

if [ ! -e "$file_processing_worker_bootstrap_token" ]; then
  openssl rand -base64 48 | tr -d '\n' > "$file_processing_worker_bootstrap_token"
fi

if [ ! -e "$knowledge_bootstrap_token" ]; then
  openssl rand -base64 48 | tr -d '\n' > "$knowledge_bootstrap_token"
fi

if [ ! -e "$docling_api_key" ]; then
  openssl rand -base64 48 | tr -d '\n' > "$docling_api_key"
fi

python3 - "$master_key" <<'PY'
import base64
import os
import pathlib
import secrets
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("EA_MASTER_KEY_V1:" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=") + "\n")
PY

chmod 0600 "$private_key" "$public_key" "$probe_token"
chmod 0400 \
  "$principal_private_key" \
  "$file_worker_bootstrap_token" \
  "$file_processing_worker_bootstrap_token" \
  "$delivery_worker_bootstrap_token" \
  "$knowledge_bootstrap_token" \
  "$docling_api_key" \
  "$master_key"
chmod 0644 "$principal_jwks"

if [ "$docker_acl" = "--docker-acl" ]; then
  # File-backed Compose secrets keep host ownership. Grant only the fixed consumer
  # UIDs read access; the entrypoint copies them into private 0400 runtime files.
  # No directory traversal or world-readable permission is granted to these UIDs.
  setfacl --set u::r,g::---,o::---,u:0:r,u:10001:r,u:10002:r,u:10003:r,u:10005:r,u:10007:r "$master_key"
  setfacl --set u::r,g::---,o::---,u:0:r "$private_key" "$principal_private_key" \
    "$file_worker_bootstrap_token" "$delivery_worker_bootstrap_token"
  setfacl --set u::r,g::---,o::---,u:10002:r "$public_key"
  setfacl --set u::r,g::---,o::---,u:0:r,u:10002:r "$probe_token"
  setfacl --set u::r,g::---,o::---,u:0:r,u:10006:r "$file_processing_worker_bootstrap_token"
  setfacl --set u::r,g::---,o::---,u:0:r,u:10008:r "$knowledge_bootstrap_token"
  setfacl --set u::r,g::---,o::---,u:1001:r,u:10006:r "$docling_api_key"
fi

echo "Agent Runtime secret files are complete in $target_dir"
