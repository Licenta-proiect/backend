# app\routers\subgrupe.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Orar, Subgrupa

# Inițializezi router-ul
router = APIRouter(prefix="/subgrupe", tags=["Subgrupe"])

@router.get("/materii")
async def get_materii_subgrupa(id_subgrupa: int, db: Session = Depends(get_db)):
    """
    Returnează lista unică de materii pentru o anumită subgrupă.
    """
    # 1. Verificăm dacă subgrupa există în baza de date
    subgrupa = db.query(Subgrupa).filter(Subgrupa.id == id_subgrupa).first()
    if not subgrupa:
        raise HTTPException(
            status_code=404, 
            detail="Subgrupa nu a fost găsită în baza de date."
        )

    # 2. Construim identificatorul idURL (ex: gID)
    id_url_grup = f"g{id_subgrupa}"

    # 3. Extragem materiile (topicLongName) din tabelul Orar
    # Folosim .distinct() pentru a evita duplicatele
    materii_query = db.query(Orar.topicLongName).filter(
        Orar.idURL == id_url_grup
    ).distinct().all()

    # 4. Convertim rezultatul într-o listă de string-uri și o ordonăm alfabetic
    # Luăm m[0] deoarece query-ul returnează o listă de tuple
    set_materii = sorted([m[0] for m in materii_query if m[0]])

    return {
        "id_subgrupa": id_subgrupa,
        "materii": set_materii
    }