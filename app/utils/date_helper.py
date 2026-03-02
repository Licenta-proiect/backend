# app\utils\date_helper.py
from sqlalchemy.orm import Session
from app.models.models import CalendarUniversitar
from datetime import datetime, timedelta

def get_calendar_date(db: Session, week: int, day_idx: int, semester: int) -> str:
    """
    Returnează data calendaristică (DD.MM.YYYY) calculată din intervalul 'perioada'.
    day_idx: 1 (Luni), 2 (Marți) ... 6 (Sâmbătă)
    """
    
    # Căutăm înregistrarea pentru săptămâna și semestrul respectiv
    # Folosim 'observatii' pentru a filtra (în loc de 'tip' sau 'type')
    cal_entry = db.query(CalendarUniversitar).filter(
        CalendarUniversitar.saptamana == week,
        CalendarUniversitar.semestru == semester
    ).first()

    if not cal_entry or not cal_entry.perioada:
        return "Data necunoscută"

    try:
        # 1. Extragem prima dată din interval (ex: "29.09.2025-05.10.2025" -> "29.09.2025")
        # Splităm după "-" și luăm prima parte
        start_date_str = cal_entry.perioada.split('-')[0].strip()
        
        # 2. Convertim string-ul în obiect datetime
        # Formatul presupus în DB: DD.MM.YYYY
        start_date = datetime.strptime(start_date_str, "%Y.%m.%d")
        
        # 3. Calculăm data pentru day_idx
        # Dacă start_date este Luni, și day_idx este 1 (Luni), adunăm 0 zile.
        # Dacă day_idx este 2 (Marți), adunăm 1 zi, etc.
        # offset = day_idx - 1
        target_date = start_date + timedelta(days=(day_idx - 1))
        
        return target_date.strftime("%d.%m.%Y")

    except Exception as e:
        print(f"Eroare procesare dată calendar: {e}")
        return "Format dată invalid"