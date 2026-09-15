#!/usr/bin/env bash
# Install only an approved 64-bit Oracle Instant Client 19c.
# Valid non-19c archives are ignored; verifier and archive errors fail the build.
set -euo pipefail

DEBIAN_MIRROR="${DEBIAN_MIRROR:-https://mirrors.aliyun.com/debian}"
DEBIAN_SECURITY_MIRROR="${DEBIAN_SECURITY_MIRROR:-https://mirrors.aliyun.com/debian-security}"
VENDOR_DIR="${ORACLE_VENDOR_DIR:-/tmp/oracle-vendor}"
INSTALL_DIR="${ORACLE_CLIENT_LIB_DIR:-/opt/oracle/instantclient}"
VERIFIER="${ORACLE_CLIENT_VERIFIER:-/tmp/verify_oracle_client.py}"

configure_libaio_compatibility() {
  local libaio_package="$1" oracle_dir="$2" libaio_target
  if [[ "${libaio_package}" != "libaio1t64" ]] || \
      python -c 'import ctypes; ctypes.CDLL("libaio.so.1")' >/dev/null 2>&1; then
    return 0
  fi
  # Use the installed distro package, never download an old deb or replace a
  # system library. The client has already passed the 64-bit/architecture check.
  libaio_target="$(dpkg-query -L "${libaio_package}" | awk '/\/libaio[.]so[.]1t64$/ { print }')"
  if [[ -z "${libaio_target}" || ! -f "${libaio_target}" ]]; then
    echo "Oracle libaio compatibility target is missing or ambiguous" >&2
    return 1
  fi
  if [[ ! -e "${oracle_dir}/libaio.so.1" && ! -L "${oracle_dir}/libaio.so.1" ]]; then
    ln -s "${libaio_target}" "${oracle_dir}/libaio.so.1"
  fi
}

# Use the image's interpreter, not an executable bit or a possibly CRLF shebang.
if ! python "${VERIFIER}" --help >/dev/null; then
  echo "Oracle client verifier cannot run; refusing to build without verification" >&2
  exit 1
fi

client_library="$(find "${VENDOR_DIR}" -type f -name 'libclntsh.so.19*' -print -quit 2>/dev/null || true)"
client_zip=""
while IFS= read -r archive; do
  if python "${VERIFIER}" --find-in-archive "${archive}" >/dev/null; then
    client_zip="${archive}"
    break
  else
    detection_status=$?
    # Exit 3 is reserved for a readable ZIP without a 19c member. Python
    # failures (including exit 1) must never be interpreted as no client.
    if [[ "${detection_status}" -ne 3 ]]; then
      echo "Oracle client archive detection failed (exit ${detection_status}); refusing to skip client installation" >&2
      exit "${detection_status}"
    fi
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

python "${VERIFIER}" "${client_library}"
cp -a "${client_dir}/." "${INSTALL_DIR}/"
configure_libaio_compatibility "${libaio_pkg}" "${INSTALL_DIR}"
ldconfig
# Set the loader path before starting Python. Finding an ELF file alone does
# not prove the OS dependencies or python-oracledb Thick initialization work.
LD_LIBRARY_PATH="${INSTALL_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
  python "${VERIFIER}" "$(find "${INSTALL_DIR}" -maxdepth 1 -type f -name 'libclntsh.so.19*' -print -quit)" --load-client

rm -rf "${VENDOR_DIR}" /tmp/oracle-unzip
