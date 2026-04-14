# app/services/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from app.db.session import SessionLocal
from app.models.models import SystemStatus
from app.services.backup import run_backup_process

# Global scheduler instance initialized to run in the background
# This allows the FastAPI server to handle requests while tasks run independently
scheduler = BackgroundScheduler()

def scheduled_backup_job():
    """
    Background job that verifies system settings and initiates the backup.
    This function is called automatically by the scheduler based on the 
    cron expression defined in the database.
    """
    db = SessionLocal()
    try:
        # Retrieve system configuration (only one row exists in SystemStatus)
        status = db.query(SystemStatus).first()
        
        # Check if the backup feature is enabled by the administrator
        if status and status.backup_enabled:
            print("Starting scheduled backup...")
            
            # Execute the full backup workflow: 
            # 1. pg_dump (Local) 
            # 2. Upload to Google Drive (Admin Account)
            # 3. Log metadata to DB
            # 4. Local file cleanup
            run_backup_process()
        else:
            print("Scheduled backup skipped: Feature is disabled in settings.")
            
    except Exception as e:
        print(f"Error during scheduled backup job: {e}")
    finally:
        db.close()