#!/usr/bin/env bash
# Install Oracle Instant Client into the image when vendor files are present.
# Skip apt entirely when Instant Client is absent (common local/dev path).
set -euo pipefail

DEBIAN_MIRROR="${DEBIAN_MIRROR:-https://mirrors.aliyun.com/debian}"
DEBIAN_SECURITY_MIRROR="${DEBIAN_SECURITY_MIRROR:-https://mirrors.aliyun.com/debian-security}"
VENDOR_DIR="${ORACLE_VENDOR_DIR:-/tmp/oracle-vendor}"
INSTALL_DIR="${ORACLE_CLIENT_LIB_DIR:-/opt/oracle/instantclient}"

has_libs=0
has_zip=0
if [[ -d "${VENDOR_DIR}/instantclient" ]] \
  && find "${VENDOR_DIR}/instantclient" -maxdepth 1 \( -name '*.so*' -o -name 'libclntsh*' \) | grep -q .; then
  has_libs=1
fi
if compgen -G "${VENDOR_DIR}/instantclient*.zip" >/dev/null; then
  has_zip=1
fi

mkdir -p "${INSTALL_DIR}"
echo "${INSTALL_DIR}" >/etc/ld.so.conf.d/oracle-instantclient.conf

if [[ "${has_libs}" -eq 0 && "${has_zip}" -eq 0 ]]; then
  echo "Oracle Instant Client not found under ${VENDOR_DIR}; skipping apt and thick-mode setup"
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

if [[ "${has_libs}" -eq 1 ]]; then
  cp -a "${VENDOR_DIR}/instantclient/." "${INSTALL_DIR}/"
else
  mkdir -p /tmp/oracle-unzip
  unzip -q "${VENDOR_DIR}"/instantclient*.zip -d /tmp/oracle-unzip
  client_dir="$(find /tmp/oracle-unzip -maxdepth 1 -type d -name 'instantclient*' | head -n 1)"
  cp -a "${client_dir}/." "${INSTALL_DIR}/"
fi

rm -rf "${VENDOR_DIR}" /tmp/oracle-unzip
ldconfig || true
