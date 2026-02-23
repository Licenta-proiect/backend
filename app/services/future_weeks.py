# app\services\future_weeks.py
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.models import CalendarUniversitar

def get_future_weeks_logic(db: Session):
    """
    Determină semestrul curent și returnează o listă cu numerele 
    săptămânilor care nu s-au încheiat încă.
    """
    now = datetime.now()
    # Preluăm tot calendarul ordonat (presupunem că saptamanile de curs sunt 1-14)
    entries = db.query(CalendarUniversitar).filter(CalendarUniversitar.saptamana <= 14).all()
    
    sem1_weeks = []
    sem2_weeks = []
    
    # Determinăm semestrul: dacă există vreo săptămână din Sem 1 care se termină în viitor,
    # înseamnă că suntem încă în Sem 1 sau în vacanța dintre ele.
    current_semester = 2 # Default la 2
    
    for entry in entries:
        # Parsăm intervalele. "perioada" poate fi "data1-data2" sau "data1-data2;data3-data4"
        parts = entry.perioada.replace(';', '-').split('-')
        # Luăm ultima dată din șir (cea mai îndepărtată în viitor pentru acea săptămână)
        last_date_str = parts[-1].strip()
        try:
            end_date = datetime.strptime(last_date_str, "%Y.%m.%d")
            
            # Verificăm dacă săptămâna este în viitor (nu s-a terminat duminica la ora 23:59)
            is_future = end_date.replace(hour=23, minute=59, second=59) >= now
            
            if entry.semestru == 1:
                if is_future:
                    sem1_weeks.append(entry.saptamana)
                    current_semester = 1 # Dacă găsim săptămâni din Sem 1 în viitor, suntem în Sem 1
            else:
                if is_future:
                    sem2_weeks.append(entry.saptamana)
        except ValueError:
            continue

    # Returnăm semestrul detectat și lista de săptămâni rămase pentru acel semestru
    active_weeks = sem1_weeks if current_semester == 1 else sem2_weeks
    return current_semester, active_weeks