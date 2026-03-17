# app\services\future_weeks.py
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.models import AcademicCalendar
from app.utils.time_helper import get_now

def get_future_weeks_logic(db: Session):
    """
    Determines the current semester (Sem 2 starts ONLY after all Sem 1 events end)
    and returns a list of lecture week numbers (1-14) that have not concluded yet.
    """
    now = get_now()
    
    # Retrieve ALL calendar entries (including sessions, vacations, with week_number > 14)
    all_entries = db.query(AcademicCalendar).all()
    
    current_semester = 2  # Assume Semester 2 by default
    sem_1_is_active = False
    current_status = "Vacation"  # Default status
    
    # Determine the current semester and check the current active activity
    for entry in all_entries:
        parts = entry.period.replace(';', '-').split('-')
        last_date_str = parts[-1].strip()
        first_date_str = parts[0].strip()
        
        try:
            start_date = datetime.strptime(first_date_str, "%Y.%m.%d")
            end_date = datetime.strptime(last_date_str, "%Y.%m.%d")
            end_date_limit = end_date.replace(hour=23, minute=59, second=59)
            
            # Check if we are currently within the range of this entry
            if start_date <= now <= end_date_limit:
                # Extract activity type from notes (before the first ;)
                if entry.notes:
                    current_status = entry.notes.split(';')[0].strip()

            if entry.semester == 1 and end_date_limit >= now:
                sem_1_is_active = True
        except ValueError:
            continue

    if sem_1_is_active:
        current_semester = 1

    # Collect future lecture weeks ONLY for the determined current semester
    last_lecture_date = None
    active_weeks = []
    
    for entry in all_entries:
        # We are only interested in lecture weeks (1-14) from the current semester
        if entry.semester == current_semester and entry.week_number <= 14:
            parts = entry.period.replace(';', '-').split('-')
            last_date_str = parts[-1].strip()
            try:
                end_date = datetime.strptime(last_date_str, "%Y.%m.%d")
                end_date_limit = end_date.replace(hour=23, minute=59, second=59)
                
                # Track the latest date of the 14th week
                if entry.week_number <= 14:
                    if last_lecture_date is None or end_date_limit > last_lecture_date:
                        last_lecture_date = end_date_limit

                # A week is valid only if it hasn't ended (Sunday at 23:59)
                if end_date_limit >= now:
                    active_weeks.append(entry.week_number)
            except ValueError:
                continue

    # Return the semester, sorted list of remaining lecture weeks, status, and the final lecture date
    return current_semester, sorted(active_weeks), current_status, last_lecture_date