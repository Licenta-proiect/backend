# app\utils\config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "default@example.com")
    ADMIN_FIRST_NAME: str = os.getenv("ADMIN_FIRST_NAME", "Admin")
    ADMIN_LAST_NAME: str = os.getenv("ADMIN_LAST_NAME", "System")
    BACKUP_PATH: str = os.getenv("BACKUP_PATH", "./backups")
    BACKUP_FOLDER_ID: str = os.getenv("BACKUP_FOLDER_ID")
    GOOGLE_REFRESH_TOKEN: str = os.getenv("GOOGLE_REFRESH_TOKEN")
    GOOGLE_CLIENT_ID : str = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET : str = os.getenv("GOOGLE_CLIENT_SECRET")

settings = Settings()