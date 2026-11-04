#!/bin/sh
set -eu
mkdir -p /state
chown 10003:10003 /state
chmod 0750 /state
exec "$@"
