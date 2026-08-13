#!/usr/bin/env bash
# Sinkronisasi kode + data ke VPS.
# Cara pakai:  ./rsync.sh user@vps-ip [folder_tujuan]
# Default folder tujuan: /opt/jobmatch
# Yang DIKECUALIKAN (tidak perlu di VPS / diatur manual):
#   - .env  (buat manual di VPS)
#   - venv  (dibuat di VPS lewat requirements.txt)
#   - database/*.json (DB-first, app akan buat ulang)
#   - data/all_jobs_clean.jsonl, data/jobs.csv, postings_final.csv (hanya untuk build/eval)
#   - data_salin, template docx, .git, .vscode
set -euo pipefail
cd "$(dirname "$0")/.."

VPS="${1:?argumen 1: user@host (mis. root@1.2.3.4)}"
TARGET="${2:-/opt/jobmatch}"

rsync -avz --progress -e ssh \
  --exclude='.git' \
  --exclude='.vscode' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='data_salin' \
  --exclude='database/*.json' \
  --exclude='data/all_jobs_clean.jsonl' \
  --exclude='data/jobs.csv' \
  --exclude='postings_final.csv' \
  --exclude='data/postings_final.csv' \
  --exclude='template ICE3IS _3.docx' \
  ./ "$VPS:$TARGET/"

echo ""
echo "[OK] Selesai. Langkah berikutnya di VPS:"
echo "  1. buat .env (lihat deploy/DEPLOY.md)"
echo "  2. python3 -m venv venv && venv/bin/pip install -r requirements.txt"
echo "  3. restore DB (lihat deploy/restore_db.sh)"
echo "  4. systemd + nginx (file di deploy/)"
