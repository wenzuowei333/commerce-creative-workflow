#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s backups/image-studio-TIMESTAMP.sql.gz\n' "$0" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
archive="$1"

test -f "$archive"
printf 'This restores %s into the configured database. Type RESTORE to continue: ' "$archive"
read -r confirmation
[[ "$confirmation" == "RESTORE" ]]

gzip -dc "$archive" | docker compose exec -T postgres psql \
  --username "${POSTGRES_USER:-image_studio}" \
  --dbname "${POSTGRES_DB:-image_studio}" \
  --single-transaction
