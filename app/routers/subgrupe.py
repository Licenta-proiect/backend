# app\routers\subgrupe.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Orar, Subgrupa
from app.schemas.user import SlotAlternativRequest
from app.services.slot_alternativ import get_data_for_optimization, find_alternative_slots

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

@router.post("/cauta-alternative")
async def cauta_sloturi_alternative(
    req: SlotAlternativRequest, 
    db: Session = Depends(get_db)
):
    """
    Căută sloturi alternative pentru o materie specifică, 
    verificând disponibilitatea studentului în funcție de orarul grupei sale.
    """
    try:
        # 1. Extragem datele necesare (constrângerile studentului și alternativele potențiale)
        data = get_data_for_optimization(db, req)

        # 2. Verificăm dacă serviciul a returnat o eroare (ex: grupa nu are materia)
        if "error" in data:
            raise HTTPException(
                status_code=400, 
                detail=data["error"]
            )

        # 3. Aplicăm algoritmul de verificare a coliziunilor orare
        alternatives = find_alternative_slots(data)

        # 4. Returnăm lista sortată cronologic (sortarea este deja făcută în serviciu)
        return {
            "selected_subject": req.selected_subject,
            "selected_type": req.selected_type,
            "count": len(alternatives),
            "alternatives": alternatives
        }

    except Exception as e:
        # Logare eroare pentru debugging
        print(f"Eroare API cauta-alternative: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail="A apărut o eroare internă la procesarea algoritmului de orar."
        )