# Deploy JobMatch ke VPS — Langkah-langkah

Persiapan server (sekali): RAM >= 8 GB, disk free >= 10 GB.
Install di VPS: `sudo apt update && sudo apt install -y python3 python3-venv python3-pip postgresql-client nginx certbot rsync`

## 1. Backup & pindahkan database (jalankan di laptop)

```bash
# 1a. dump seluruh data Postgres lokal
./deploy/dump_db.sh

# 1b. pilih tujuan, lalu restore. Contoh ke Neon:
./deploy/restore_db.sh deploy/db_dump_XXXX.dump "postgresql://user:pass@host-nya-neon/dbname"

# 1c. verifikasi (harus kembalikan angka nyata)
psql "URL_NEON" -c 'SELECT count(*) FROM app.vacancies;'
psql "URL_NEON" -c 'SELECT count(*) FROM app.users;'
```

Catatan: kalau Neon pakai pooler (pgbouncer), `pg_restore` bisa gagal —
pakai **host direct** (non-pooler) untuk restore.

## 2. Kirim kode + data ke VPS (jalankan di laptop)

```bash
./deploy/rsync.sh user@vps-ip
# kalau folder beda: ./deploy/rsync.sh user@vps-ip /srv/jobmatch
```

File yang TIDAK ikut (sengaja): `.env`, `venv`, `database/*.json`,
`data/all_jobs_clean.jsonl`, `data/jobs.csv`, `postings_final.csv`.

## 3. Di VPS

```bash
cd /opt/jobmatch

# 3a. buat .env (isi DB_URL = URL Neon/PG hasil restore, SECRET_KEY baru)
cat > .env <<EOF
DB_URL=postgresql://user:pass@host/dbname
SECRET_KEY=$(openssl rand -hex 32)
PORT=8000
USE_SQLITE=0
EOF

# 3b. venv + dependencies (download model HF terjadi saat pertama boot)
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3c. folder writable (JSON fallback + CV upload)
sudo chown -R www-data:www-data uploads database

# 3d. systemd service
sudo cp deploy/jobmatch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jobmatch
sudo systemctl status jobmatch

# cek log kalau ada error
journalctl -u jobmatch -f
```

Boot pertama lambat (model embeddings ~2,5 GB di-download + cache),
tunggu hingga log menampilkan "Job embeddings ready!".

## 4. Nginx + HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/jobmatch
sudo sed -i 's/ganti.dengan.domain.com/domain-anda.com/' /etc/nginx/sites-available/jobmatch
sudo ln -s /etc/nginx/sites-available/jobmatch /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS (Let's Encrypt)
sudo certbot --nginx -d domain-anda.com
```

## 5. Verifikasi

- Buka https://domain-anda.com → halaman utama
- Login user lama → profil, lamaran, tersimpan ikut (data dari DB yang di-restore)
- `/jobs` → pencarian jalan (pakai `all_jobs_clean.db` yang sudah di-rsync)

## Rollback / update

- Update kode: `./deploy/rsync.sh user@vps-ip` lalu `sudo systemctl restart jobmatch`
- Backup rutin: `./deploy/dump_db.sh`
