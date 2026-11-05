#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p backups
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="backups/image-studio-${timestamp}.sql.gz"

docker compose exec -T postgres pg_dump \
  --username "${POSTGRES_USER:-image_studio}" \
  --dbname "${POSTGRES_DB:-image_studio}" \
  --format plain | gzip -9 > "$archive"

docker compose exec -T --user root api \
  python -m app.ops upload-backup "/backups/$(basename "$archive")"
find backups -type f -name 'image-studio-*.sql.gz' -mtime +30 -delete
printf 'Backup completed: %s\n' "$archive"
