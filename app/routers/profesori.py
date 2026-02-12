# app\routers\profesori.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Profesor, Orar

# Inițializezi router-ul
router = APIRouter(prefix="/profesor", tags=["Profesori"])

@router.get("/materii")
async def get_profesor_materii(email: str, db: Session = Depends(get_db)):
    """
    Verifică profesorul după email și returnează ID-ul acestuia 
    împreună cu lista unică de materii predate.
    """
    # 1. Căutăm profesorul în tabelul 'profesori' folosind emailAddress
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    
    if not profesor:
        raise HTTPException(
            status_code=404, 
            detail="Profesorul cu acest email nu a fost găsit în baza de date."
        )

    # 2. Luăm materiile unice (set) din tabelul orar folosind ID-ul profesorului
    # Folosim .distinct() pentru a ne asigura că nu avem duplicate
    materii_query = db.query(Orar.topicLongName).filter(
        Orar.teacherID == profesor.id
    ).distinct().all()

    # Query-ul returnează o listă de tuple, ex: [("Programare",), ("Bazate de date",)]
    # Convertim într-o listă simplă de string-uri
    set_materii = [m[0] for m in materii_query if m[0]]

    return {
        "id": profesor.id,
        "nume": f"{profesor.firstName} {profesor.lastName}",
        "materii": set_materii
    }