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
        return "Data necunoscută"

    try:
        # Splităm segmentele (în caz că există ';' pentru fracționare)
        segments = cal_entry.perioada.split(';')
        
        # Procesăm primul segment
        first_segment = segments[0].split('-')
        start_1 = datetime.strptime(first_segment[0].strip(), "%Y.%m.%d")
        end_1 = datetime.strptime(first_segment[1].strip(), "%Y.%m.%d")
        
        # Calculăm câte zile (indexuri) acoperă primul segment
        # .days returnează diferența; adunăm 1 pentru a include și ziua de final
        days_in_first_segment = (end_1 - start_1).days + 1

        if day_idx <= days_in_first_segment:
            # Ziua căutată este în primul segment
            target_date = start_1 + timedelta(days=(day_idx - 1))
        elif len(segments) > 1:
            # Ziua căutată este în al doilea segment
            second_segment = segments[1].split('-')
            start_2 = datetime.strptime(second_segment[0].strip(), "%Y.%m.%d")
            
            # Ajustăm indexul: dacă primul segment a avut 3 zile (L,M,Mi), 
            # ziua 4 (Joi) devine prima zi din segmentul 2.
            remaining_days = day_idx - days_in_first_segment
            target_date = start_2 + timedelta(days=(remaining_days - 1))
        else:
            # Cazul în care day_idx e mai mare decât intervalul (eroare de date în DB)
            target_date = start_1 + timedelta(days=(day_idx - 1))

        return target_date.strftime("%d.%m.%Y")

    except Exception as e:
        print(f"Eroare procesare dată calendar: {e}")
        return "Format dată invalid"