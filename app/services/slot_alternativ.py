# app\services\slot_alternativ.py

from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa
from typing import Set

def verifica_existenta_materie(db: Session, subgrupa_id: int, materie: str, tip_activitate: str) -> bool:
    """
    Verifica in tabela 'orar' daca subgrupa are materia si tipul specificat.
    Filtrarea se face folosind prefixul 'g' in fata ID-ului subgrupei pentru idURL.
    """
    # Construim ID-ul cautat: g + ID (ex: "g44")
    target_id_url = f"g{subgrupa_id}"
    
    row_orar = db.query(Orar).filter(
        Orar.idURL == target_id_url,
        Orar.topicLongName == materie,
        Orar.typeLongName == tip_activitate
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
        Subgrupa.specializationShortName == subgrupa_ref.specializationShortName,
        Subgrupa.studyYear == subgrupa_ref.studyYear,
        Subgrupa.id != selected_subgrupa_id # Excludem grupa proprie
    ).all()

    # 3. Filtram doar acele grupe care au efectiv materia si tipul in orar
    valid_ids = set()
    for sg in potential_groups:
        if verifica_existenta_materie(db, sg.id, materie, tip_activitate):
            valid_ids.add(sg.id)
            
    return valid_ids

