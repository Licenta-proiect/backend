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
    Algoritm CP-SAT care verifica disponibilitatea pentru FIECARE saptamana.
    Un slot este valid daca studentul este liber in saptamanile in care se tine ora.
    """
    results = []
    
    for alt in data["potential_alternatives"]:
        weeks_alt = parse_weeks_from_info(alt["otherInfo"], alt["parity"])
        d_alt = int(alt["weekDay"])
        s_alt = int(alt["startHour"])
        dur_alt = int(alt["duration"])
        e_alt = s_alt + dur_alt
        
        valid_weeks_for_this_alt = []

        # Rulam CP-SAT pentru fiecare saptamana in care grupa tinta are ora
        for w in sorted(list(weeks_alt)):
            model = cp_model.CpModel()
            
            # Intervalul orei la care studentul vrea sa mearga
            interval_alt = model.NewIntervalVar(
                model.NewConstant(s_alt), 
                model.NewConstant(dur_alt), 
                model.NewConstant(e_alt), 
                f"alt_w{w}"
            )

            conflict_intervals = []
            for i, slot in enumerate(data["student_constraints"]):
                # Verificam daca studentul are ora in ACEEASI ZI si in ACEASTA SAPTAMANA SPECIFICA
                if int(slot["weekDay"]) == d_alt:
                    w_student = parse_weeks_from_info(slot["otherInfo"], slot["parity"])
                    
                    if w in w_student:
                        s_s = int(slot["startHour"])
                        d_s = int(slot["duration"])
                        
                        name = f"student_w{w}_idx{i}_{s_s}"
                        conflict_intervals.append(
                            model.NewIntervalVar(
                                model.NewConstant(s_s), 
                                model.NewConstant(d_s), 
                                model.NewConstant(s_s + d_s), 
                                name
                            )
                        )

            if conflict_intervals:
                model.AddNoOverlap([interval_alt] + conflict_intervals)

            solver = cp_model.CpSolver()
            if solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                valid_weeks_for_this_alt.append(w)

        # Daca am gasit cel putin o saptamana libera, adaugam slotul in lista
        if valid_weeks_for_this_alt:
            results.append({
                "idURL": alt["idURL"],
                "day": d_alt,
                "startHour": s_alt,
                "formattedTime": f"{s_alt//60:02d}:{s_alt%60:02d}",
                "duration": dur_alt,
                "teacherID": alt["teacherID"],
                "roomId": alt["roomId"],
                "weeks": valid_weeks_for_this_alt, # Raportam doar saptamanile in care studentul poate merge
                "topic": alt["topicLongName"],
                "type": alt["typeLongName"]
            })

    return results

if __name__ == "__main__":
    from app.db.session import SessionLocal
    import json

    # Datele primite de la frontend simulate prin schema Pydantic
    # Nota: Folosim field-urile Python (snake_case) sau aliases daca avem Config setat
    test_request = SlotAlternativRequest(
        selectedGroupId=44,
        selectedSubject="Inteligenţă artificială",
        selectedType="laborator",
        attendsCourse=True
    )

    db_session = SessionLocal()
    try:
        print(f"--- Incepem testarea pentru Grupa {test_request.selected_group_id} ---")
        data = get_data_for_optimization(db_session, test_request)
        
        if "error" in data:
            print(f"❌ Eroare: {data['error']}")
        else:
            
            alternatives = find_alternative_slots(data)
            print(f"S-au gasit {len(alternatives)} sloturi compatibile:")
            for res in alternatives:
                print(f"Grupa: {res['idURL']} | Zi: {res['day']} | Ora: {res['formattedTime']} | Saptamani: {res['weeks']}")
                
    except Exception as e:
        print(f"❌ Eroare neasteptata la testare: {e}")
    finally:
        db_session.close()