# app\services\slot_alternativ.py

from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa
from app.schemas.user import SlotAlternativRequest
from typing import Set
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

    # Dacă nu există nicio altă subgrupă care să aibă această materie
    if not compatible_group_ids:
        return {
            "error": f"Există o singură grupă în anul de studiu și specializarea selectată. "
            "Prin urmare, nu există alternative pentru recuperare."
        }

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
    Determina saptamanile active (1-14). 
    REGULA: 
    1. Daca exista indicii de saptamani (s, S, sapt) in text, extragem tot.
    2. Suporta intervale de tip: "1-10", "S1-S10", "Sapt 1 - Sapt 10".
    3. Ignoram cifrele urmate de 'h' (durate).
    """
    all_weeks = set(range(1, 15))
    extracted_from_text = set()

    if other_info:
        # 1. Eliminăm duratele de tip "2.5h", "2h", "1.5 h" din text pentru a nu polua căutarea
        # Folosim regex pentru a șterge orice număr (zecimal sau nu) urmat de 'h'
        text = re.sub(r'\d+(\.\d+)?\s*h', '', other_info.lower())
        
        # 1. Extragem intervale complexe: cautam (prefix optional + cifra) - (prefix optional + cifra)
        # Regex: (prefix opțional) (cifra1) cratima (prefix opțional) (cifra2)
        # Grupurile (\d+) sunt cele care ne intereseaza
        range_matches = re.findall(r'(?:s(?:apt)?\.?\s*)?(\d+)\s*-\s*(?:s(?:apt)?\.?\s*)?(\d+)', text)
        
        for start, end in range_matches:
            s, e = int(start), int(end)
            if 1 <= s <= 14 and 1 <= e <= 14:
                # Daca ordinea e inversa (ex: 10-1), corectam pentru range
                low, high = min(s, e), max(s, e)
                extracted_from_text.update(range(low, min(high + 1, 15)))

        # 2. Extragem saptamani individuale (care nu au fost prinse in intervale sau sunt punctuale)
        # Folosim prefixe sau context de enumerare (+, virgula)
        # (?!\s*h) asigura ca nu luam "1h"
        individual_with_prefix = re.findall(r'(?:s(?:apt)?\.?\s*|\+\s*|\b)(\d+)(?!\s*h)', text)
        for val in individual_with_prefix:
            v = int(val)
            if 1 <= v <= 14:
                extracted_from_text.add(v)

        # 3. Tratarea cazului special unde saptamanile sunt enumerate dupa virgula sau +
        # Daca textul contine deja cuvinte cheie de saptamana, cautam cifre izolate
        if any(kw in text for kw in ["sapt", "s.", "s "]):
            # Cautam cifre care nu sunt durate (nu au h lipit de ele)
            # dar sunt in context de enumerare
            isolated_nums = re.findall(r'(?<!\d)(\d+)(?!\s*h)', text)
            for val in isolated_nums:
                v = int(val)
                if 1 <= v <= 14:
                    # Verificam daca nu cumva e ora de start/durata (ex: 18-20)
                    # O saptamana intr-un context valid are de obicei valori mici 1-14
                    extracted_from_text.add(v)

    # LOGICA DE DECIZIE
    if extracted_from_text:
        # Daca am gasit saptamani in text, returnam DOAR acele saptamani (ignore parity)
        return extracted_from_text

    # FALLBACK: Daca textul nu ne-a oferit nimic, folosim paritatea
    if parity == 1: # Impare
        return {w for w in all_weeks if w % 2 != 0}
    elif parity == 2: # Pare
        return {w for w in all_weeks if w % 2 == 0}
    
    # Daca nu avem nimic, tot semestrul
    return all_weeks

def find_alternative_slots(data):
    results = []
    student_days_map = {i: [] for i in range(1, 7)}
    
    for i, slot in enumerate(data["student_constraints"]):
        day = int(slot["weekDay"])
        if day in student_days_map:
            student_days_map[day].append({
                "start": int(slot["startHour"]),
                "end": int(slot["startHour"]) + int(slot["duration"]),
                "weeks": parse_weeks_from_info(slot["otherInfo"], slot["parity"])
            })

    for alt in data["potential_alternatives"]:
        weeks_alt = parse_weeks_from_info(alt["otherInfo"], alt["parity"])
        d_alt = int(alt["weekDay"])
        s_alt = int(alt["startHour"])
        e_alt = s_alt + int(alt["duration"])
        
        relevant_student_slots = student_days_map.get(d_alt, [])
        valid_weeks_for_this_alt = []

        for w in sorted(list(weeks_alt)):
            has_conflict = False
            for s_slot in relevant_student_slots:
                if w in s_slot["weeks"]:
                    # Verificare clasica de intersectie intervale:
                    # (StartA < EndB) AND (EndA > StartB)
                    if s_alt < s_slot["end"] and e_alt > s_slot["start"]:
                        has_conflict = True
                        break
            
            if not has_conflict:
                valid_weeks_for_this_alt.append(w)

        if valid_weeks_for_this_alt:
            results.append({
                "idURL": alt["idURL"],
                "day": d_alt,
                "startHour": s_alt,
                "formattedTime": f"{s_alt//60:02d}:{s_alt%60:02d}",
                "duration": alt["duration"],
                "teacherID": alt["teacherID"],
                "roomId": alt["roomId"],
                "weeks": valid_weeks_for_this_alt,
                "topic": alt["topicLongName"],
                "type": alt["typeLongName"]
            })

    sorted_results = sorted(results, key=lambda x: (x["day"], x["startHour"]))
    
    return sorted_results

if __name__ == "__main__":
    from app.db.session import SessionLocal
    import json

    # Datele primite de la frontend simulate prin schema Pydantic
    # Nota: Folosim field-urile Python (snake_case) sau aliases daca avem Config setat
    test_request = SlotAlternativRequest(
        selectedGroupId=49,
        selectedSubject="Recunoaşterea formelor",
        selectedType="laborator",
        attendsCourse=False
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