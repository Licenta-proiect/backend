# app\services\backup.py
import os
import subprocess
from datetime import datetime, timezone
from app.utils.config import settings

def execute_db_backup():
    """Generează un fișier .sql cu starea actuală a bazei de date."""
    db_uri = settings.DATABASE_URL
    backup_dir = settings.BACKUP_PATH
    
    # Calea către executabilul pg_dump
    pg_dump_path = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"

    if not os.path.exists(pg_dump_path):
        print(f"❌ pg_dump nu a fost găsit! Verifică calea: {pg_dump_path}")
        return None

    # Creăm folderul dacă nu există
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    # Generăm numele fișierului folosind timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(backup_dir, f"backup_{timestamp}.sql")

    try:
        # Executăm pg_dump
        # -F c (format custom, comprimat)
        # -f (output file)

        subprocess.run(
            [pg_dump_path, db_uri, "-F", "c", "-f", filename],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"✅ Backup creat cu succes: {filename}")
        return filename
    except subprocess.CalledProcessError as e:
        print(f"❌ Eroare la backup: {e.stderr}")
        return None