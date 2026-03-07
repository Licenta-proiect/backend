# app\utils\config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "default@example.com")
    ADMIN_FIRST_NAME: str = os.getenv("ADMIN_FIRST_NAME", "Admin")
    ADMIN_LAST_NAME: str = os.getenv("ADMIN_LAST_NAME", "System")

settings = Settings()