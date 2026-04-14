# app\utils\config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL")
    
    # Admin data for the account in the database
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "default@example.com")
    ADMIN_FIRST_NAME: str = os.getenv("ADMIN_FIRST_NAME", "Admin")
    ADMIN_LAST_NAME: str = os.getenv("ADMIN_LAST_NAME", "System")
    
    # Database backup folder
    BACKUP_PATH: str = os.getenv("BACKUP_PATH", "./backups")
    BACKUP_FOLDER_ID: str = os.getenv("BACKUP_FOLDER_ID")
    
    # For Authentication (OAuth2)
    GOOGLE_REFRESH_TOKEN: str = os.getenv("GOOGLE_REFRESH_TOKEN")
    GOOGLE_CLIENT_ID : str = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET : str = os.getenv("GOOGLE_CLIENT_SECRET")
    SECRET_KEY : str = os.getenv("SECRET_KEY")

    # For Scraper Calendar (Gemini)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")

    # 2FA
    EMAIL_SENDER: str = os.getenv("EMAIL_SENDER")
    EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD")

settings = Settings()