# app\routers\data.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Orar, Subgrupa, Profesor, Sala

# Inițializezi router-ul
router = APIRouter(prefix="/data", tags=["Data"])

@router.get("/profesori")
async def get_active_profesori(db: Session = Depends(get_db)):
    """
    Returnează profesorii care apar în tabelul Orar (idURL de tip pID).
    """
    # 1. Extragem idURL-urile unice de tip profesor ('p%') din Orar
    prof_ids_query = db.query(Orar.idURL).filter(Orar.idURL.like('p%')).distinct().all()
    
    # 2. Convertim în set de ID-uri numerice (eliminăm 'p')
    prof_ids = {int(row[0][1:]) for row in prof_ids_query if row[0] and len(row[0]) > 1}
    
    if not prof_ids:
        return []

    # 3. Luăm detaliile din tabelul profesori și le ordonăm alfabetic
    profesori = db.query(Profesor).filter(
        Profesor.id.in_(list(prof_ids))
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
    Returnează sălile care apar în tabelul Orar (idURL de tip sID).
    """
    # 1. Extragem idURL-urile unice de tip sală ('s%') din Orar
    sali_ids_query = db.query(Orar.idURL).filter(Orar.idURL.like('s%')).distinct().all()
    
    # 2. Convertim în set de ID-uri numerice (eliminăm 's')
    sali_ids = {int(row[0][1:]) for row in sali_ids_query if row[0] and len(row[0]) > 1}
    
    if not sali_ids:
        return []

    # 3. Luăm detaliile din tabelul sali
    sali = db.query(Sala).filter(Sala.id.in_(list(sali_ids))).order_by(Sala.name.asc()).all()
    
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
    Returnează grupele care apar în tabelul Orar (idURL de tip gID).
    """
    # 1. Extragem idURL-urile unice de tip grupă ('g%') din Orar
    grupe_ids_query = db.query(Orar.idURL).filter(Orar.idURL.like('g%')).distinct().all()
    
    # 2. Convertim în set de ID-uri numerice (eliminăm 'g')
    grupe_ids = {int(row[0][1:]) for row in grupe_ids_query if row[0] and len(row[0]) > 1}
    
    if not grupe_ids:
        return []

    # 3. Luăm detaliile din tabelul subgrupe și ordonăm după groupName și index
    grupe = db.query(Subgrupa).filter(
        Subgrupa.id.in_(list(grupe_ids))
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