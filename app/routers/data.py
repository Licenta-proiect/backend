# app\routers\data.py
from typing import List

from fastapi import APIRouter, Body, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Subgrupa, Profesor, Sala, Orar
from app.services.future_weeks import get_future_weeks_logic
from app.services.slot_liber import get_max_week_for_groups

router = APIRouter(prefix="/data", tags=["Data"])

@router.get("/profesori")
async def get_active_profesori(db: Session = Depends(get_db)):
    """
    Returnează profesorii care au orarul descărcat (has_schedule=True).
    """
    profesori = db.query(Profesor).filter(
        Profesor.has_schedule == True
    ).order_by(Profesor.lastName.asc(), Profesor.firstName.asc()).all()
    
    return [
        {
            "id": p.id,
            "lastName": p.lastName,
            "firstName": p.firstName,
            "emailAddress": p.emailAddress,
            "positionShortName": p.positionShortName,
            "phdShortName": p.phdShortName,
            "otherTitle": p.otherTitle
        } for p in profesori
    ]

@router.get("/sali")
async def get_active_sali(db: Session = Depends(get_db)):
    """
    Returnează sălile care au orarul descărcat (has_schedule=True).
    """
    sali = db.query(Sala).filter(
        Sala.has_schedule == True
    ).order_by(Sala.name.asc()).all()
    
    return [
        {
            "id": s.id,
            "nume": s.name,
            "shortName": s.shortName,
            "buildingName": s.buildingName
        } for s in sali
    ]

@router.get("/grupe")
async def get_active_grupe(db: Session = Depends(get_db)):
    """
    Returnează grupele care au orarul descărcat (has_schedule=True).
    """
    grupe = db.query(Subgrupa).filter(
        Subgrupa.has_schedule == True
    ).order_by(Subgrupa.specializationShortName, Subgrupa.groupName.asc(), Subgrupa.subgroupIndex.asc()).all()
    
    return [
        {
            "id": g.id,
            "nume": g.groupName, 
            "subgroupIndex": g.subgroupIndex if g.subgroupIndex else '',
            "studyYear": g.studyYear,
            "specializationShortName": g.specializationShortName
        } for g in grupe
    ]

@router.get("/tip-activitate")
async def get_tipuri_activitate(db: Session = Depends(get_db)):
    """
    Returnează tipurile unice de activitate (Curs, Laborator, Seminar, etc.)
    extrase direct din coloana typeLongName a tabelului Orar.
    """
    # Extragem valorile distincte din coloana typeLongName
    query = db.query(Orar.typeLongName).distinct().all()
    
    # Convertim lista de tuple în listă de string-uri, eliminând valorile None (dacă există)
    tipuri = sorted([t[0] for t in query if t[0]])
    
    return tipuri

@router.get("/weeks")
async def get_future_weeks(db: Session = Depends(get_db)):
    """
    Returnează semestrul curent, săptămânile de curs rămase și statusul actual.
    """
    current_semester, active_weeks, current_status, last_lecture_date = get_future_weeks_logic(db)
    
    return {
        "current_semester": current_semester,
        "active_weeks": active_weeks,
        "current_status": current_status
    }

@router.post("/weeks-valide")
async def get_valid_weeks(grupe_ids: List[int] = Body(..., embed=True), db: Session = Depends(get_db)):
    '''
    Returnează săptămânile valide pentru grupe, ținând cont de anul de studiu.
    '''
    
    # Determinăm semestrul și săptămânile de curs generale din calendar
    current_semester, active_weeks, _, _ = get_future_weeks_logic(db)
    
    # Determinăm limita superioară pentru grupele selectate (10 sau 14)
    max_week_limit = get_max_week_for_groups(db, grupe_ids, current_semester)
    
    # Filtrăm săptămânile active care depășesc limita grupei
    filtered_weeks = [w for w in active_weeks if w <= max_week_limit]
    
    return {
        "active_weeks": filtered_weeks,
        "max_week_limit": max_week_limit
    }

@router.get("/tipuri-activitate-profesor")
async def get_tipuri_activitate_profesor(
    email: str, 
    materie: str, 
    db: Session = Depends(get_db)
):
    """
    Returnează tipurile de activitate (Curs, Laborator, etc.) pe care un profesor
    le are în orar pentru o anumită materie.
    """
    # Găsim profesorul după email pentru a-i afla ID-ul
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    if not profesor:
        return []

    # Construim string-ul de căutare pentru idUrl (formatul p + id)
    prof_url_id = f"p{profesor.id}"

    # Căutăm în Orar tipurile distincte
    # Verificăm unde idUrl conține id-ul profesorului și materia corespunde
    query = db.query(Orar.typeLongName).distinct().filter(
        Orar.idURL == prof_url_id,
        func.lower(Orar.topicLongName) == func.lower(materie)
    ).all()

    # Curățăm rezultatele
    tipuri = sorted([t[0] for t in query if t[0]])

    return tipuri