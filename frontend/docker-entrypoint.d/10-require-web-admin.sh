#!/bin/sh
set -eu

if [ "${FEATURE_WEB_ADMIN:-false}" != "true" ]; then
  echo "admin-web disabled: FEATURE_WEB_ADMIN must be true" >&2
  exit 1
fi
