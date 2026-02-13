# app\routers\data.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Subgrupa, Profesor, Sala

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
    ).order_by(Subgrupa.groupName.asc(), Subgrupa.subgroupIndex.asc()).all()
    
    return [
        {
            "id": g.id,
            "nume": g.groupName, 
            "subgroupIndex": g.subgroupIndex if g.subgroupIndex else '',
            "studyYear": g.studyYear,
            "specializationShortName": g.specializationShortName
        } for g in grupe
    ]