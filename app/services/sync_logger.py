# app\services\sync_logger.py
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.models import SyncHistory, SystemStatus
from app.db.session import SessionLocal
from app.services.scraper import clean_val

def cleanup_old_sync_logs(db: Session, days_to_keep: int = 150):
    """
    Deletes log entries older than a specific number of days.
    Default set to 150 days to keep the database clean.
    """
    threshold_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    
    deleted_count = db.query(SyncHistory).filter(
        SyncHistory.start_date < threshold_date
    ).delete()
    
    db.commit()
    return deleted_count

async def run_sync_with_logging(func, sync_type: str, trigger_type: str = "Manual"):
    """
    Executes the synchronization and logs the process.
    """
    db: Session = SessionLocal()

    # Enable Maintenance Mode
    status_obj = db.query(SystemStatus).first()
    if status_obj:
        status_obj.is_updating = True
        db.commit()
    
    # Create the start entry
    history = SyncHistory(
        sync_type=clean_val(sync_type),
        trigger_type=clean_val(trigger_type),
        start_date=datetime.now(timezone.utc),
        status="In progress"
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    try:
        # Execute the scraping function
        await func() 
        
        # Mark as success
        history.status = "Success"
    except Exception as e:
        # Mark as error and save the message
        history.status = "Error"
        history.error_message = str(e)
    finally:
        # Disable Maintenance Mode
        if status_obj:
            status_obj.is_updating = False
            status_obj.last_sync = datetime.now(timezone.utc)

        # Finalize the current log
        history.end_date = datetime.now(timezone.utc)
        db.commit()
                
        db.close()