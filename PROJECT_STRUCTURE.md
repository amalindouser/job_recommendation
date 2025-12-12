# Project Structure

```
job_recommendation3/
├── app.py                           # Main Flask app
├── wsgi.py                          # Production WSGI entry point
├── requirements.txt                 # Python dependencies
├── vercel.json                      # Vercel config
├── Procfile                         # Heroku config (legacy)
├── .env                             # Environment variables (DO NOT COMMIT)
├── .gitignore                       # Git ignore rules
│
├── src/                             # Source code modules
│   ├── __init__.py
│   ├── recommender_sentence.py      # Recommendation algorithm
│   └── ...
│
├── templates/                       # HTML templates
│   ├── base.html                    # Base template
│   ├── index.html                   # Job search page
│   ├── login.html                   # Login page
│   ├── register.html                # Register page
│   ├── saved.html                   # Saved jobs page
│   ├── landing.html                 # Landing page
│   └── dashboard.html               # Dashboard page
│
├── static/                          # Static files (CSS, JS, images)
│   ├── css/
│   ├── js/
│   └── images/
│
├── data/                            # Data files
│   ├── graph_jobs_clean.graphml     # Knowledge graph
│   ├── graph_jobs.graphml           # Knowledge graph (backup)
│   ├── knowledge_graph_light.graphml# Lightweight graph
│   └── ...
│
├── database/                        # Database files
│   └── (users.db - local only)      # SQLite local (DO NOT COMMIT)
│
└── scripts/                         # Utility scripts
    └── ...
```

## File Cleanup

**Files to remove/ignore:**
- `users.db` → Remove (use cloud DB)
- `__pycache__/` → Already in .gitignore
- `recommender.py` → Move to `src/` if still used

**Missing directories to create:**
- `static/` → For CSS, JS, images

## Environment Variables (.env)

```
DB_URL=postgresql://...
SECRET_KEY=your-secret-key-here
FLASK_ENV=production
```

## Deployment

- **Local:** Run `python app.py`
- **Vercel:** Uses `vercel.json` config
- **WSGI:** Run with gunicorn: `gunicorn wsgi:app`
