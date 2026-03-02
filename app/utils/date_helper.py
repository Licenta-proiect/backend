# app\utils\date_helper.py
from sqlalchemy.orm import Session
from app.models.models import CalendarUniversitar
from datetime import datetime, timedelta

def get_calendar_date(db: Session, week: int, day_idx: int, semester: int) -> str:
    """
    Returnează data calendaristică (DD.MM.YYYY).
    Gestionează intervale simple (29.09.2025-05.10.2025) 
    și fracționate (22.12.2025-24.12.2025;08.01.2026-11.01.2026).
    """
    cal_entry = db.query(CalendarUniversitar).filter(
        CalendarUniversitar.saptamana == week,
        CalendarUniversitar.semestru == semester
    ).first()

    if not cal_entry or not cal_entry.perioada:
        return "Fără calendar"

    target_date = None

    try:
        segments = cal_entry.perioada.split(';')
        
        # Încercăm să găsim data în segmentele disponibile
        for seg in segments:
            parts = seg.split('-')
            if len(parts) != 2: continue
            
            start_dt = datetime.strptime(parts[0].strip(), "%Y.%m.%d")
            end_dt = datetime.strptime(parts[1].strip(), "%Y.%m.%d")
            
            # Aflăm în ce zi a săptămânii începe segmentul curent (0=Luni, 6=Dum)
            # Îl convertim la 1=Luni, ..., 7=Dum pentru a se potrivi cu day_idx
            seg_start_weekday = start_dt.weekday() + 1
            
            # Calculăm distanța (offset-ul) necesar pentru a ajunge la ziua dorită
            offset = day_idx - seg_start_weekday
            potential_date = start_dt + timedelta(days=offset)
            
            # Verificăm dacă data rezultată se află în interiorul acestui segment
            if start_dt <= potential_date <= end_dt:
                target_date = potential_date
                break # Am găsit segmentul corect

        # Dacă am găsit o dată, verificăm dacă ziua ei de săptămână coincide cu day_idx
        if target_date:
            actual_weekday = target_date.weekday() + 1
            if actual_weekday == day_idx:
                return target_date.strftime("%d.%m.%Y")
        
        return "Zi nelucrătoare/Vacanță"

    except Exception as e:
        print(f"Eroare date_helper: {e}")
        return "Eroare format"