# app\services\sync_logger.py
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.models import IstoricSincronizare
from app.db.session import SessionLocal

def cleanup_old_sync_logs(db: Session, days_to_keep: int = 150):
    """
    Șterge înregistrările mai vechi de un număr de zile.
    Default setat la 150 de zile pentru a păstra baza de date curată.
    """
    threshold_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    
    deleted_count = db.query(IstoricSincronizare).filter(
        IstoricSincronizare.data_start < threshold_date
    ).delete()
    
    db.commit()
    return deleted_count

async def run_sync_with_logging(func, tip_sincronizare: str, tip_declansare: str = "Manual"):
    """
    Execută sincronizarea, loghează procesul și curăță istoria veche.
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
        # 2. Executăm funcția de scraping
        await func() 
        
        # 3. Marcăm succesul
        istoric.status = "Succes"
    except Exception as e:
        # 4. Marcăm eroarea și salvăm mesajul
        istoric.status = "Eroare"
        istoric.mesaj_eroare = str(e)
    finally:
        # 5. Finalizăm log-ul curent
        istoric.data_final = datetime.now(timezone.utc)
        db.commit()
        
        # --- AUTO-CLEANUP ---
        # Curățăm logurile mai vechi de 150 de zile la fiecare rulare
        try:
            cleanup_old_sync_logs(db, 150)
        except Exception as e:
            print(f"⚠️ Eroare la curățarea istoricului: {e}")
        
        db.close()