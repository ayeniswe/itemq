#!/usr/bin/env sh
set -eu

export ITEMQ_DB_PATH="${ITEMQ_DB_PATH:-/data/itemq.db}"
export ITEMQ_MEDIA_PATH="${ITEMQ_MEDIA_PATH:-/data/media}"

exec "$@"
