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
        
        # Segment 1
        first_part = segments[0].split('-')
        start_1 = datetime.strptime(first_part[0].strip(), "%Y.%m.%d")
        end_1 = datetime.strptime(first_part[1].strip(), "%Y.%m.%d")
        
        # VERIFICARE: În ce zi a săptămânii pică start_1?
        # Dacă start_1.weekday() este 0, e Luni. Dacă e 1, e Marți, etc.
        db_start_weekday = start_1.weekday() + 1 # Convertim la formatul tău 1-7
        
        # Calculăm distanța reală față de începutul segmentului
        # Dacă day_idx e Joi(4) și segmentul începe Luni(1), offset-ul e 3 zile.
        # Dacă segmentul începe direct de Marți(2), offset-ul e doar 2 zile.
        offset = day_idx - db_start_weekday
        
        # Verificăm dacă day_idx se află în primul segment
        if offset >= 0 and (start_1 + timedelta(days=offset)) <= end_1:
            target_date = start_1 + timedelta(days=offset)
        
        elif len(segments) > 1:
            # Trecem la segmentul 2 (ex: după vacanța de Crăciun)
            second_part = segments[1].split('-')
            start_2 = datetime.strptime(second_part[0].strip(), "%Y.%m.%d")
            
            # Aflăm în ce zi a săptămânii începe al doilea segment
            db_start_2_weekday = start_2.weekday() + 1
            offset_2 = day_idx - db_start_2_weekday
            target_date = start_2 + timedelta(days=offset_2)
        else:
            # Fallback dacă ceva nu se aliniază
            target_date = start_1 + timedelta(days=(day_idx - 1))

        return target_date.strftime("%d.%m.%Y")

    except Exception as e:
        return "Eroare format"