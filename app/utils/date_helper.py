# app\utils\date_helper.py
from sqlalchemy.orm import Session
from app.models.models import AcademicCalendar
from datetime import datetime, timedelta

def get_calendar_date(db: Session, week: int, day_idx: int, semester: int) -> str:
    """
    Returns the calendar date (DD.MM.YYYY).
    Handles simple intervals (2025.09.29-2025.10.05) 
    and fragmented ones (2025.12.22-2025.12.24;2026.01.08-2026.01.11).
    """
    cal_entry = db.query(AcademicCalendar).filter(
        AcademicCalendar.week_number == week,
        AcademicCalendar.semester == semester
    ).first()

    if not cal_entry or not cal_entry.period:
        return "Fără calendar"

    target_date = None

    try:
        segments = cal_entry.period.split(';')
        
        # Try to find the date within the available segments
        for seg in segments:
            parts = seg.split('-')
            if len(parts) != 2: continue
            
            start_dt = datetime.strptime(parts[0].strip(), "%Y.%m.%d")
            end_dt = datetime.strptime(parts[1].strip(), "%Y.%m.%d")
            
            # Determine on which day of the week the current segment starts (0=Mon, 6=Sun)
            # Convert it to 1=Mon, ..., 7=Sun to match day_idx
            seg_start_weekday = start_dt.weekday() + 1
            
            # Calculate the distance (offset) needed to reach the desired day
            offset = day_idx - seg_start_weekday
            potential_date = start_dt + timedelta(days=offset)
            
            # Check if the resulting date falls within this segment
            if start_dt <= potential_date <= end_dt:
                target_date = potential_date
                break # Found the correct segment

        # If a date was found, verify if its day of the week matches day_idx
        if target_date:
            actual_weekday = target_date.weekday() + 1
            if actual_weekday == day_idx:
                return target_date.strftime("%d.%m.%Y")
        
        return "Zi nelucrătoare/Vacanță"

    except Exception as e:
        print(f"date_helper error: {e}")
        return "Eroare format"