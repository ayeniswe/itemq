#!/usr/bin/env sh
set -eu

DATA_DIR="${ITEMQ_DATA_DIR:-/data}"
MEDIA_DIR="$DATA_DIR/media"

mkdir -p "$MEDIA_DIR" /app/data

ln -sfn "$MEDIA_DIR" /app/data/media

export ITEMQ_DB_PATH="${ITEMQ_DB_PATH:-$DATA_DIR/itemq.db}"

exec "$@"
