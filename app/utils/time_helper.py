# app\utils\time_helper.py
import os
from datetime import datetime
from dotenv import load_dotenv, find_dotenv

def get_now():
    """Returnează data din .env dacă există, altfel datetime.now()"""
    #load_dotenv(find_dotenv(), override=True)
    
    env_time = os.getenv("APP_CURRENT_TIME")
    if env_time:
        try:
            return datetime.strptime(env_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print(f"⚠️ Format invalid in .env pentru APP_CURRENT_TIME. Folosim timpul real.")
    return datetime.now()