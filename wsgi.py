"""
WSGI entry point for production deployment (Railway, Vercel, Heroku, etc).
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
    print("WARNING: DB_URL not set, using defaults")

if not secret_key:
    print("WARNING: SECRET_KEY not set, using defaults")

# For Railway/Heroku: use PORT environment variable
port = int(os.getenv('PORT', 5000))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=port)
