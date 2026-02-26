# app\services\future_weeks.py
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.models import CalendarUniversitar

def get_future_weeks_logic(db: Session):
    """
    Determină semestrul curent (Sem 2 începe DOAR după ce toate evenimentele din Sem 1 se termină)
    și returnează o listă cu numerele săptămânilor de curs (1-14) care nu s-au încheiat încă.
    """
    now = datetime(2026, 12, 1, 23, 0, 0)
    
    #  Preluăm TOATE datele din calendar (inclusiv sesiuni, vacanțe, cu saptamana > 14)
    all_entries = db.query(CalendarUniversitar).all()
    
    current_semester = 2 # Presupunem implicit Semestrul 2
    sem_1_is_active = False
    current_status = "Vacanță" # Status default
    
    #  Determinăm semestrul și verificăm în ce activitate suntem ACUM
    for entry in all_entries:
        parts = entry.perioada.replace(';', '-').split('-')
        last_date_str = parts[-1].strip()
        first_date_str = parts[0].strip()
        
        try:
            start_date = datetime.strptime(first_date_str, "%Y.%m.%d")
            end_date = datetime.strptime(last_date_str, "%Y.%m.%d")
            end_date_limit = end_date.replace(hour=23, minute=59, second=59)
            
            # Verificăm dacă suntem în intervalul acestei înregistrări chiar ACUM
            if start_date <= now <= end_date_limit:
                # Extragem tipul activității din observații (înainte de primul ;)
                if entry.observatii:
                    current_status = entry.observatii.split(';')[0].strip()

            if entry.semestru == 1 and end_date_limit >= now:
                sem_1_is_active = True
        except ValueError:
            continue

    if sem_1_is_active:
        current_semester = 1

    #  Colectăm săptămânile de curs viitoare DOAR pentru semestrul determinat
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
    return current_semester, sorted(active_weeks), current_status