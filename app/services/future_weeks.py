# app\services\future_weeks.py
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.models import CalendarUniversitar

def get_future_weeks_logic(db: Session):
    """
    Determină semestrul curent (Sem 2 începe DOAR după ce toate evenimentele din Sem 1 se termină)
    și returnează o listă cu numerele săptămânilor de curs (1-14) care nu s-au încheiat încă.
    """
    now = datetime(2026, 1, 10, 23, 0, 0)
    
    # 1. Preluăm TOATE datele din calendar (inclusiv sesiuni, vacanțe, cu saptamana > 14)
    all_entries = db.query(CalendarUniversitar).all()
    
    current_semester = 2 # Presupunem implicit Semestrul 2
    sem_1_is_active = False
    
    # 2. Determinăm Semestrul Curent
    # Dacă orice activitate din Sem 1 (curs, sesiune, restanțe) se termină în viitor, suntem încă în Sem 1
    for entry in all_entries:
        if entry.semestru == 1:
            parts = entry.perioada.replace(';', '-').split('-')
            last_date_str = parts[-1].strip()
            try:
                end_date = datetime.strptime(last_date_str, "%Y.%m.%d")
                end_date_limit = end_date.replace(hour=23, minute=59, second=59)
                
                if end_date_limit >= now:
                    sem_1_is_active = True
                    break  # Am găsit o dată viitoare în Sem 1, oprim căutarea
            except ValueError:
                continue

    if sem_1_is_active:
        current_semester = 1

    # 3. Colectăm săptămânile de curs viitoare DOAR pentru semestrul determinat
    active_weeks = []
    
    for entry in all_entries:
        # Ne interesează doar săptămânile de curs (1-14) din semestrul curent
        if entry.semestru == current_semester and entry.saptamana <= 14:
            parts = entry.perioada.replace(';', '-').split('-')
            last_date_str = parts[-1].strip()
            try:
                end_date = datetime.strptime(last_date_str, "%Y.%m.%d")
                end_date_limit = end_date.replace(hour=23, minute=59, second=59)
                
                # Săptămâna e validă doar dacă nu s-a terminat duminică la 23:59
                if end_date_limit >= now:
                    active_weeks.append(entry.saptamana)
            except ValueError:
                continue

    # Returnăm semestrul și săptămânile de curs rămase sortate
    return current_semester, sorted(active_weeks)