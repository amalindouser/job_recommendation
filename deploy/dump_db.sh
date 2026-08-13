#!/usr/bin/env bash
# Dump seluruh data Postgres lokal (users, vacancies, dsb) ke file .dump
# Cara pakai:  ./dump_db.sh [nama_file.dump]
# Hasil: file dump siap di-restore ke Neon / Postgres VPS.
set -euo pipefail
cd "$(dirname "$0")/.."

DB_URL="$(grep -E '^DB_URL=' .env | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/[[:space:]]*$//')"
if [ -z "$DB_URL" ]; then
  echo "[!] DB_URL tidak ditemukan di .env" >&2
  exit 1
fi

OUT="${1:-deploy/db_dump_$(date +%Y%m%d_%H%M).dump}"
mkdir -p "$(dirname "$OUT")"

echo "[*] Dumping database ke $OUT ..."
pg_dump --no-owner --no-privileges -Fc "$DB_URL" -f "$OUT"
echo "[OK] Selesai: $OUT ($(du -h "$OUT" | cut -f1))"
