# app\services\scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from app.db.session import SessionLocal
from app.models.models import SystemStatus
from app.services.backup import run_backup_process
from app.services.sync_logger import run_sync_with_logging
from app.services.scraper import populate as populate_base
from app.services.schedule_scraper import populate as populate_orar
import asyncio

async def simulate_long_sync():
    """Simulează un proces de sincronizare care durează 5 minute."""
    print("Test: Sincronizare simulată pornită (5 minute)...")
    await asyncio.sleep(60) 
    print("Test: Sincronizare simulată finalizată.")

# Global scheduler instance initialized to run in the background
# This allows the FastAPI server to handle requests while tasks run independently
scheduler = BackgroundScheduler()

async def sync_base_and_schedule_logic():
    """Executes base data population followed by schedule population sequentially."""
    await populate_base()
    await populate_orar()

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

def scheduled_sync_job():
    """
    Background job triggered by the scheduler for automated synchronization.
    Verifies system status and executes the sync within an event loop.
    """
    db = SessionLocal()
    try:
        status = db.query(SystemStatus).first()
        if status and status.auto_sync_enabled:
            print(f"Starting scheduled synchronization ({status.sync_interval})...")
            
            # Since run_sync_with_logging is an async function, we must run it
            # within a dedicated event loop for this background thread.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    run_sync_with_logging(
                        sync_base_and_schedule_logic, 
                        "Base + Schedule", 
                        "Automatic"
                    )
                )
            finally:
                loop.close()
        else:
            print("INFO: Scheduled synchronization skipped. Feature is disabled in settings.")
    except Exception as e:
        print(f"ERROR: Failed to execute scheduled sync job: {str(e)}")
    finally:
        db.close()