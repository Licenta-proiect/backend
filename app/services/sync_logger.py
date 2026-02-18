# app\services\sync_logger.py
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.models import IstoricSincronizare
from app.db.session import SessionLocal

def cleanup_old_sync_logs(db: Session, days_to_keep: int = 90):
    """
    Șterge înregistrările din IstoricSincronizare mai vechi de un număr de zile.
    """
    threshold_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    
    deleted_count = db.query(IstoricSincronizare).filter(
        IstoricSincronizare.data_start < threshold_date
    ).delete()
    
    db.commit()
    return deleted_count

async def run_sync_with_logging(func, tip_sincronizare: str, tip_declansare: str = "Manual"):
    """
    Execută o funcție de sincronizare și salvează rezultatul în IstoricSincronizare.
    """
    db: Session = SessionLocal()
    # 1. Creăm înregistrarea de start
    istoric = IstoricSincronizare(
        tip_sincronizare=tip_sincronizare,
        tip_declansare=tip_declansare,
        data_start=datetime.now(timezone.utc),
        status="În curs"
    )
    db.add(istoric)
    db.commit()
    db.refresh(istoric)

    try:
        # 2. Executăm funcția de scraping (trebuie să fie asincronă)
        await func() 
        
        # 3. Marcăm succesul
        istoric.status = "Succes"
    except Exception as e:
        # 4. Marcăm eroarea
        istoric.status = "Eroare"
        istoric.mesaj_eroare = str(e)
    finally:
        istoric.data_final = datetime.now(timezone.utc)
        db.commit()
        
        # --- AUTO-CLEANUP ---
        # După fiecare sync reușit, ștergem ce e mai vechi de 30 de zile
        cleanup_old_sync_logs(db, 30)
        
        db.close()