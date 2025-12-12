"""
WSGI entry point for production deployment (Vercel, Heroku, etc).
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from app import app

# Production config
app.config['DEBUG'] = False
app.config['ENV'] = 'production'

# Ensure required environment variables are set
db_url = os.getenv('DB_URL')
secret_key = os.getenv('SECRET_KEY')

if not db_url:
    raise RuntimeError("DB_URL environment variable is required for production!")

if not secret_key or secret_key == 'dev-secret-key-change-in-prod':
    raise RuntimeError("SECRET_KEY must be set in environment variables for production!")

if __name__ == '__main__':
    app.run()
