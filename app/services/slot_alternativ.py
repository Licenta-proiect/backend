# app\services\slot_alternativ.py

from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa
from typing import Set

def verifica_existenta_materie(db: Session, subgrupa_id: int, materie: str, tip_activitate: str) -> bool:
    """
    Verifică în tabela 'orar' dacă subgrupa are materia și tipul specificat.
    """
    # Construim ID-ul URL formatat (care în scraper-ul tău pare să conțină ID-ul grupei)
    # Dacă în DB idURL este stocat direct ca ID-ul subgrupei, folosim egalitate.
    rand_orar = db.query(Orar).filter(
        Orar.idURL == str(subgrupa_id), # Presupunând că idURL mapat este ID-ul subgrupei
        Orar.topicLongName == materie,
        Orar.typeLongName == tip_activitate
    ).first()
    
    return rand_orar is not None

def get_subgrupe_compatibile(db: Session, selected_subgrupa_id: int, materie: str, tip_activitate: str) -> Set[int]:
    """
    Returnează un set de ID-uri de subgrupe la care studentul ar putea merge (aceeași specializare/an).
    """
    # 1. Preluăm datele de referință ale grupei selectate
    subgrupa_ref = db.query(Subgrupa).filter(Subgrupa.id == selected_subgrupa_id).first()
    
    if not subgrupa_ref:
        return set()

    # 2. Căutăm subgrupe potențiale (aceeași facultate, specializare, an)
    potentiale = db.query(Subgrupa).filter(
        Subgrupa.has_schedule == True,
        Subgrupa.faculty_id == subgrupa_ref.faculty_id,
        Subgrupa.specializationShortName == subgrupa_ref.specializationShortName,
        Subgrupa.studyYear == subgrupa_ref.studyYear,
        Subgrupa.id != selected_subgrupa_id # Excludem grupa proprie
    ).all()

    # 3. Filtrăm doar acele grupe care au efectiv materia și tipul în orar
    id_uri_valide = set()
    for sg in potentiale:
        if verifica_existenta_materie(db, sg.id, materie, tip_activitate):
            id_uri_valide.add(sg.id)
            
    return id_uri_valide