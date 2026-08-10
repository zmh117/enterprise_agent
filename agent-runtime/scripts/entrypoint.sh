#!/bin/sh
set -eu

node scripts/preflight.mjs
exec "$@"
