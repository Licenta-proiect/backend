# app\services\backup.py
import os
import subprocess
from datetime import datetime
from app.utils.config import settings

def execute_db_backup():
    """Generates a .sql file with the current state of the database."""
    db_uri = settings.DATABASE_URL
    backup_dir = settings.BACKUP_PATH
    
    # Path to the pg_dump executable
    pg_dump_path = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"

    if not os.path.exists(pg_dump_path):
        print(f"pg_dump not found! Check path: {pg_dump_path}")
        return None

    # Create the directory if it doesn't exist
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    # Generate the filename using a timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(backup_dir, f"backup_{timestamp}.sql")

    try:
        # Execute pg_dump
        # -F c (custom format, compressed)
        # -f (output file)

        subprocess.run(
            [pg_dump_path, db_uri, "-F", "c", "-f", filename],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"Backup created successfully: {filename}")
        return filename
    except subprocess.CalledProcessError as e:
        print(f"Backup error: {e.stderr}")
        return None