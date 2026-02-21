# app\routers\subgrupe.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Orar, Subgrupa
from app.schemas.user import SlotAlternativRequest
from app.services.slot_alternativ import get_data_for_optimization, find_alternative_slots

# Inițializezi router-ul
router = APIRouter(prefix="/subgrupe", tags=["Subgrupe"])

# Mapare pentru indexul returnat de date.weekday() (0=Luni ... 6=Duminică)
ZILE_RO = {
    0: "Luni", 1: "Marți", 2: "Miercuri", 3: "Joi",
    4: "Vineri", 5: "Sâmbătă", 6: "Duminică"
}

def group_consecutive_weeks(weeks):
    """
    Transformă [1, 2, 3, 5, 7, 8] în "1-3, 5, 7-8"
    """
    if not weeks:
        return ""
    weeks = sorted(list(weeks))
    ranges = []
    start = weeks[0]
    for i in range(1, len(weeks) + 1):
        if i == len(weeks) or weeks[i] != weeks[i-1] + 1:
            end = weeks[i-1]
            if start == end:
                ranges.append(f"{start}")
            else:
                ranges.append(f"{start}-{end}")
            if i < len(weeks):
                start = weeks[i]
    return ", ".join(ranges)

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
        # 1. Obținem datele de optimizare
        data = get_data_for_optimization(db, req)
        if "error" in data:
            raise HTTPException(status_code=400, detail=data["error"])

        # 2. Rulăm algoritmul (fără calendar, doar pe săptămâni 1-14)
        raw_alternatives = find_alternative_slots(data)

        processed_results = []

        for alt in raw_alternatives:
            # Determinăm numele zilei (day e 1-Luni, 2-Marți...)
            day_idx = int(alt["day"])
            nume_zi = ZILE_RO.get(day_idx - 1, "Necunoscut")

            # Pregătim detaliile pe săptămâni
            weeks_list = sorted(alt["weeks"])
            
            # Creăm obiectul îmbogățit
            enriched_alt = {
                "idURL": alt["idURL"],
                "zi": nume_zi,
                "ora": alt["formattedTime"],
                "sala": alt["roomId"],
                "profesor_id": alt["teacherID"],
                "saptamani_lista": weeks_list,
                "saptamani_grupate": group_consecutive_weeks(weeks_list)
            }
            processed_results.append(enriched_alt)

        return {
            "materie": req.selected_subject,
            "tip": req.selected_type,
            "total_optiuni": len(processed_results),
            "optiuni": processed_results
        }

    except Exception as e:
        print(f"❌ Eroare: {str(e)}")
        raise HTTPException(status_code=500, detail="Eroare la procesarea alternativelor.")