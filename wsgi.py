"""
WSGI entry point for production deployment (Vercel, Heroku, etc).
"""
import os
from app import app

# Disable Flask debug in production
app.config['DEBUG'] = False

# Ensure SECRET_KEY is set from environment or use default (override in .env)
if not app.config.get('SECRET_KEY') or app.config['SECRET_KEY'] == 'dev-secret-key-change-in-prod':
    raise RuntimeError("SECRET_KEY must be set in environment variables for production!")

if __name__ == '__main__':
    app.run()
