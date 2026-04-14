# app\services\backup.py
import os
import subprocess
from datetime import datetime, timezone
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from app.utils.config import settings
from app.db.session import SessionLocal
from app.models.models import DatabaseBackup

def get_drive_service():
    """Builds the Google Drive service using the Admin's Refresh Token."""
    # Define the scope required to write/manage files
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    # Create the credentials object using data from .env
    creds = Credentials(
        token=None,  # Access token will be automatically generated on refresh
        refresh_token=settings.GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES
    )

    # If the access token is missing or expired, perform a refresh
    if not creds.valid:
        creds.refresh(Request())
    
    return build('drive', 'v3', credentials=creds)

def upload_to_drive(file_path, filename):
    """Uploads the file to Google Drive using the Admin's storage quota."""
    try:
        service = get_drive_service()

        file_metadata = {
            'name': filename,
            'parents': [settings.BACKUP_FOLDER_ID]
        }
        
        media = MediaFileUpload(
            file_path, 
            mimetype='application/octet-stream', 
            resumable=True
        )
        
        # Create the file directly in the admin's account
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        file_id = file.get('id')
        print(f"File uploaded successfully to Admin Drive. ID: {file_id}")
        return file_id

    except Exception as e:
        print(f"Drive upload error: {e}")
        return None

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
    
def run_backup_process():
    """Complete workflow: Dump -> Upload to Drive -> Log to DB -> Local Cleanup."""
    local_file = execute_db_backup() # Your existing pg_dump function
    if not local_file:
        return

    filename = os.path.basename(local_file)
    drive_id = upload_to_drive(local_file, filename)

    if drive_id:
        # Log entry into the database
        db = SessionLocal()
        try:
            file_size = os.path.getsize(local_file)
            new_log = DatabaseBackup(
                filename=filename,
                drive_file_id=drive_id,
                size_bytes=file_size,
                created_at=datetime.now(timezone.utc)
            )
            db.add(new_log)
            db.commit()
            print("Backup successfully logged to database.")
        except Exception as e:
            print(f"DB Logging error: {e}")
        finally:
            db.close()
        
        # Remove local file to save server space
        os.remove(local_file)
        print("Local backup file deleted.")