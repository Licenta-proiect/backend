# app\services\slot_alternativ.py

from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa
from app.schemas.user import SlotAlternativRequest
from typing import Set, List, Dict, Any
from ortools.sat.python import cp_model
import re

def format_row(row):
    return {
        "idURL": row.idURL,
        "teacherID": row.teacherID,
        "roomId": row.roomId,
        "topicLongName": row.topicLongName,
        "typeLongName": row.typeLongName,
        "weekDay": row.weekDay,
        "startHour": row.startHour,
        "duration": row.duration,
        "parity": row.parity,
        "otherInfo": row.otherInfo
    }

def verifica_existenta_materie(db: Session, subgrupa_id: int, materie: str, tip_activitate: str) -> bool:
    """
    Verifica in tabela 'orar' daca subgrupa are materia si tipul specificat.
    Filtrarea se face folosind prefixul 'g' in fata ID-ului subgrupei pentru idURL.
    """
    # Construim ID-ul cautat: g + ID (ex: "g44")
    target_id_url = f"g{subgrupa_id}"
    
    row_orar = db.query(Orar).filter(
        Orar.idURL == target_id_url,
        func.lower(Orar.topicLongName) == func.lower(materie),
        func.lower(Orar.typeLongName) == func.lower(tip_activitate)
    ).first()
    
    return row_orar is not None

def get_subgrupe_compatibile(db: Session, selected_subgrupa_id: int, materie: str, tip_activitate: str) -> Set[int]:
    """
    Returneaza un set de ID-uri de subgrupe la care studentul ar putea merge (aceeasi specializare/an).
    """
    # 1. Preluam datele de referinta ale grupei selectate
    subgrupa_ref = db.query(Subgrupa).filter(Subgrupa.id == selected_subgrupa_id).first()
    
    if not subgrupa_ref:
        return set()

    # 2. Cautam subgrupe potentiale (aceeasi facultate, specializare, an)
    potential_groups = db.query(Subgrupa).filter(
        Subgrupa.has_schedule == True,
        Subgrupa.faculty_id == subgrupa_ref.faculty_id,
        func.lower(Subgrupa.specializationShortName) == func.lower(subgrupa_ref.specializationShortName),
        Subgrupa.studyYear == subgrupa_ref.studyYear,
        Subgrupa.id != selected_subgrupa_id # Excludem grupa proprie
    ).all()

    # 3. Filtram doar acele grupe care au efectiv materia si tipul in orar
    valid_ids = set()
    for sg in potential_groups:
        if verifica_existenta_materie(db, sg.id, materie, tip_activitate):
            valid_ids.add(sg.id)
            
    return valid_ids

def get_data_for_optimization(db: Session, req: SlotAlternativRequest):
    '''Extrage două seturi de date: constrângerile grupului curent (când este ocupat 
    studentul) și opțiunile de sloturi de la grupele compatibile.'''
    # 1. Verificăm dacă grupa selectată are materia și tipul cerut
    if not verifica_existenta_materie(db, req.selected_group_id, req.selected_subject, req.selected_type):
        return {"error": "Grupa selectată nu are această materie sau tip de activitate în orar."}

    # 2. Extragem "intervalele ocupate" pentru grupa selectată (Constrângeri)
    # Acestea sunt orele la care studentul NU poate merge la o recuperare
    target_id_url = f"g{req.selected_group_id}"
    
    query_student = db.query(Orar).filter(Orar.idURL == target_id_url)
    
    # Dacă attends_course este False, eliminăm cursurile din lista de ocupare
    if not req.attends_course:
        query_student = query_student.filter(func.lower(Orar.typeLongName) != func.lower("curs"))
    
    student_busy_slots = query_student.all()

    # 3. Identificăm grupele compatibile (aceeași specializare, an, etc.)
    compatible_group_ids = get_subgrupe_compatibile(
        db, req.selected_group_id, req.selected_subject, req.selected_type
    )

    # 4. Extragem "sloturile candidate" de la celelalte grupe
    # Căutăm doar aparițiile materiei și tipului solicitat la grupele compatibile
    potential_slots = []
    if compatible_group_ids:
        # Construim lista de idURL-uri: ["g45", "g46", ...]
        compatible_id_urls = [f"g{gid}" for gid in compatible_group_ids]
        
        potential_slots = db.query(Orar).filter(
            Orar.idURL.in_(compatible_id_urls),
            func.lower(Orar.topicLongName) == func.lower(req.selected_subject),
            func.lower(Orar.typeLongName) == func.lower(req.selected_type)
        ).all()

    # 5. Formatăm datele pentru algoritm
    return {
        "student_constraints": [format_row(row) for row in student_busy_slots],
        "potential_alternatives": [format_row(row) for row in potential_slots]
    }

def parse_weeks_from_info(other_info, parity):
    """
    Determina saptamanile active (1-14) bazat pe paritate si textul otherInfo.
    """
    all_weeks = set(range(1, 15))
    
    # 1. Filtrare dupa paritate
    if parity == 1: # Saptamani Impare
        weeks = {w for w in all_weeks if w % 2 != 0}
    elif parity == 2: # Saptamani Pare
        weeks = {w for w in all_weeks if w % 2 == 0}
    else: # Saptamanal (parity 0 sau null)
        weeks = set(all_weeks)

    # 2. Logica simplificata pentru otherInfo (Regex pentru intervale de tip 1-10 sau 8-14)
    if other_info:
        # Cautam pattern-uri de tip "1-10", "1-9", "8-14"
        match = re.search(r'Sapt\.?\s*(\d+)\s*-\s*(\d+)', other_info, re.IGNORECASE)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            interval_weeks = set(range(start, min(end + 1, 15)))
            weeks = weeks.intersection(interval_weeks)
        
        # Cautam specificari de tip "Sapt. 1,3,5"
        elif "Sapt." in other_info:
            specific_weeks = re.findall(r'\b(\d+)\b', other_info)
            if specific_weeks:
                interval_weeks = {int(w) for w in specific_weeks if int(w) <= 14}
                weeks = weeks.intersection(interval_weeks)

    return weeks

def find_alternative_slots(data):
    """
    Gaseste sloturi alternative verificand coliziunile la intervale de 60 de minute.
    """
    # Nota: CP-SAT nu este strict necesar pentru o verificare de coliziune simpla, 
    # dar structura permite extinderea catre constrangeri complexe ulterior.
    
    # --- 1. Maparea constrangerilor studentului ---
    # (saptamana, zi, ora_minut) -> True
    student_blocked = {} 

    for slot in data["student_constraints"]:
        weeks = parse_weeks_from_info(slot["otherInfo"], slot["parity"])
        day = slot["weekDay"]
        start = int(slot["startHour"])
        duration = int(slot["duration"])
        
        for w in weeks:
            # Incrementam din 60 in 60 de minute
            for h in range(start, start + duration, 60): 
                student_blocked[(w, day, h)] = True

    # --- 2. Analiza alternativelor ---
    results = []
    
    for alt in data["potential_alternatives"]:
        weeks = parse_weeks_from_info(alt["otherInfo"], alt["parity"])
        day = alt["weekDay"]
        start = int(alt["startHour"])
        duration = int(alt["duration"])
        
        is_feasible = True

        # Verificam suprapunerea pentru fiecare interval de 60 min din alternativa
        for w in weeks:
            for h in range(start, start + duration, 60):
                if (w, day, h) in student_blocked:
                    is_feasible = False
                    break
            if not is_feasible: 
                break
        
        if is_feasible:
            results.append({
                "idURL": alt["idURL"],
                "day": day,
                "startHour": start,
                "formattedTime": f"{start//60:02d}:{start%60:02d}",
                "duration": duration,
                "teacherID": alt["teacherID"],
                "roomId": alt["roomId"],
                "weeks": sorted(list(weeks)),
                "topic": alt["topicLongName"],
                "type": alt["typeLongName"]
            })

    return results

if __name__ == "__main__":
    from app.db.session import SessionLocal
    import json

    # Datele primite de la frontend simulate prin schema Pydantic
    # Nota: Folosim field-urile Python (snake_case) sau aliases daca avem Config setat
    test_data = SlotAlternativRequest(
        selectedGroupId=44,
        selectedSubject="Proiectarea Aplicatiilor WEB",
        selectedType="laborator",
        attendsCourse=True
    )

    db_session = SessionLocal()
    try:
        alternatives = find_alternative_slots(test_data)
        print(f"S-au gasit {len(alternatives)} sloturi compatibile:")
        for res in alternatives:
            print(f"Grupa: {res['idURL']} | Zi: {res['day']} | Ora: {res['formattedTime']} | Saptamani: {res['weeks']}")
            
    except Exception as e:
        print(f"❌ Eroare neasteptata la testare: {e}")
    finally:
        db_session.close()
