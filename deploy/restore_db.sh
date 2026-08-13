#!/usr/bin/env bash
# Restore dump ke Postgres tujuan (Neon / VPS).
# Cara pakai:  ./restore_db.sh deploy/db_dump_XXXX.dump "postgresql://user:pass@host/dbname"
# Catatan:
#  - Tujuan harus kosong atau boleh punya tabel; pg_restore akan membuat schema app.*
#  - Kalau tujuan pakai pooler Neon (pgbouncer), pakai host direct bukan pooler,
#    karena pg_restore butuh session transaction.
set -euo pipefail
cd "$(dirname "$0")/.."

DUMP="${1:?argumen 1: file dump (.dump)}"
TARGET="${2:?argumen 2: URL Postgres tujuan}"
[ -f "$DUMP" ] || { echo "[!] File dump tidak ditemukan: $DUMP" >&2; exit 1; }

echo "[*] Restore $DUMP ke $TARGET ..."
pg_restore --no-owner --no-privileges --verbose -d "$TARGET" "$DUMP"
echo "[OK] Restore selesai."
echo "Verifikasi: psql \"$TARGET\" -c 'SELECT count(*) FROM app.vacancies;'"
