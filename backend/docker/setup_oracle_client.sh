#!/usr/bin/env bash
# Install only an approved 64-bit Oracle Instant Client 19c.
# Unrelated or unsupported archives are ignored and Oracle remains unavailable.
set -euo pipefail

DEBIAN_MIRROR="${DEBIAN_MIRROR:-https://mirrors.aliyun.com/debian}"
DEBIAN_SECURITY_MIRROR="${DEBIAN_SECURITY_MIRROR:-https://mirrors.aliyun.com/debian-security}"
VENDOR_DIR="${ORACLE_VENDOR_DIR:-/tmp/oracle-vendor}"
INSTALL_DIR="${ORACLE_CLIENT_LIB_DIR:-/opt/oracle/instantclient}"
VERIFIER="${ORACLE_CLIENT_VERIFIER:-/tmp/verify_oracle_client.py}"

client_library="$(find "${VENDOR_DIR}" -type f -name 'libclntsh.so.19*' -print -quit 2>/dev/null || true)"
client_zip=""
while IFS= read -r archive; do
  if "${VERIFIER}" --find-in-archive "${archive}" >/dev/null; then
    client_zip="${archive}"
    break
  fi
done < <(find "${VENDOR_DIR}" -maxdepth 2 -type f -name '*.zip' -print 2>/dev/null)

mkdir -p "${INSTALL_DIR}"
echo "${INSTALL_DIR}" >/etc/ld.so.conf.d/oracle-instantclient.conf

if [[ -z "${client_library}" && -z "${client_zip}" ]]; then
  echo "Approved Oracle Instant Client 19c not found; Oracle remains blocked"
  rm -rf "${VENDOR_DIR}"
  exit 0
fi

if [[ -f /etc/apt/sources.list.d/debian.sources ]]; then
  sed -i \
    -e "s|https\\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
    -e "s|https\\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
    /etc/apt/sources.list.d/debian.sources
elif [[ -f /etc/apt/sources.list ]]; then
  sed -i \
    -e "s|https\\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
    -e "s|https\\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
    /etc/apt/sources.list
fi

apt_retry() {
  local n=0
  until [[ "${n}" -ge 3 ]]; do
    if "$@"; then
      return 0
    fi
    n=$((n + 1))
    echo "apt retry ${n}/3 failed, sleeping..."
    sleep $((n * 5))
  done
  return 1
}

apt_retry apt-get update
libaio_pkg=libaio1
if apt-cache show libaio1t64 >/dev/null 2>&1; then
  libaio_pkg=libaio1t64
fi
apt_retry apt-get install -y --no-install-recommends unzip ca-certificates "${libaio_pkg}"
rm -rf /var/lib/apt/lists/*

if [[ -n "${client_library}" ]]; then
  client_dir="$(dirname "${client_library}")"
else
  mkdir -p /tmp/oracle-unzip
  unzip -q "${client_zip}" -d /tmp/oracle-unzip
  client_library="$(find /tmp/oracle-unzip -type f -name 'libclntsh.so.19*' -print -quit)"
  client_dir="$(dirname "${client_library}")"
fi

"${VERIFIER}" "${client_library}"
cp -a "${client_dir}/." "${INSTALL_DIR}/"
"${VERIFIER}" "$(find "${INSTALL_DIR}" -maxdepth 1 -type f -name 'libclntsh.so.19*' -print -quit)"

rm -rf "${VENDOR_DIR}" /tmp/oracle-unzip
ldconfig || true
