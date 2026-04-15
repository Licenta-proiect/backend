# app\utils\maintenance.py
from fastapi import HTTPException, status
from app.db.session import SessionLocal
from app.models.models import SystemStatus

def verify_system_available():
    db = SessionLocal()
    try:
        status_obj = db.query(SystemStatus).first()
        if status_obj and status_obj.is_updating:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Sistemul este în curs de actualizare. Vă rugăm să reveniți în câteva minute."
            )
    finally:
        db.close()