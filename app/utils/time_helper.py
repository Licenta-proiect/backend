# app\utils\time_helper.py
import os
from datetime import datetime
from dotenv import load_dotenv, find_dotenv

def get_now():
    """Returns the date from .env if it exists, otherwise returns datetime.now()"""
    #load_dotenv(find_dotenv(), override=True)
    
    env_time = os.getenv("APP_CURRENT_TIME")
    if env_time:
        try:
            return datetime.strptime(env_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print(f"Invalid format in .env for APP_CURRENT_TIME. Using real-time instead.")
    return datetime.now()