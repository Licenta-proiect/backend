# app\routers\subgrupe.py
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Orar, Subgrupa, Profesor, Sala
from app.schemas.user import SlotAlternativRequest
from app.services.slot_alternativ import get_data_for_optimization, find_alternative_slots
from app.services.future_weeks import get_future_weeks_logic
from app.utils.time_helper import get_now

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
    
    now = get_now()

    # Determinăm semestrul curent și săptămânile care nu au trecut încă
    current_semester, future_weeks_list, current_status, last_lecture_date = get_future_weeks_logic(db)
    future_weeks_set = set(future_weeks_list)

    # Obținem datele brute de la serviciu
    data = get_data_for_optimization(db, req)
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    
    if "info" in data:
        return {
            "materie": req.selected_subject,
            "tip": req.selected_type,
            "total_optiuni": 0,
            "optiuni": [],
            "info_message": data["info"] # Mapăm către info_message pentru frontend
        }

    # Verificăm dacă am depășit fizic data de final a săptămânii 14
    is_after_last_week = last_lecture_date and now > last_lecture_date
    if is_after_last_week:
        # S-au terminat toate cele 14 săptămâni -> Afișăm statusul (Sesiune/Vacanță/etc.)
        raise HTTPException(
            status_code=400, 
            detail=f"Nu se pot căuta recuperări deoarece suntem în perioada de {current_status.lower()}."
        )
        
    try:
        # Rulăm algoritmul de detecție conflicte
        raw_alternatives = find_alternative_slots(data)

        # Extragem ID-urile unice pentru Subgrupe, Profesori și Săli
        subgrupa_ids = {int(alt["idURL"].replace('g', '')) for alt in raw_alternatives}
        profesor_ids = {alt["teacherID"] for alt in raw_alternatives if alt["teacherID"]}
        sala_ids = {alt["roomId"] for alt in raw_alternatives if alt["roomId"]}

        # Interogări Bulk (o singură interogare per tabelă)
        subgrupe_db = db.query(Subgrupa).filter(Subgrupa.id.in_(subgrupa_ids)).all()
        profesori_db = db.query(Profesor).filter(Profesor.id.in_(profesor_ids)).all()
        sali_db = db.query(Sala).filter(Sala.id.in_(sala_ids)).all()

        # Transformăm listele în dicționare pentru acces rapid după ID
        map_subgrupe = {s.id: s for s in subgrupe_db}
        map_profesori = {p.id: f"{p.lastName} {p.firstName}" for p in profesori_db}
        map_sali = {s.id: s.name for s in sali_db}

        # Procesare și filtrare săptămâni viitoare
        processed_results = []

        for alt in raw_alternatives:
            # Intersectăm săptămânile slotului cu cele care nu au trecut încă
            actual_future_weeks = sorted(list(set(alt["weeks"]) & future_weeks_set))
            
            # Dacă după filtrare nu mai rămâne nicio săptămână validă, sărim peste acest slot
            if not actual_future_weeks:
                continue

            # Calcul Timp
            s_hour = int(alt["startHour"])
            duration = int(alt["duration"])
            e_hour = s_hour + duration
            ora_start = f"{s_hour // 60:02d}:{s_hour % 60:02d}"
            ora_final = f"{e_hour // 60:02d}:{e_hour % 60:02d}"

            # Recuperare date din Mapele create anterior (Fără alte interogări DB aici)
            sg_id = int(alt["idURL"].replace('g', ''))
            sg_obj = map_subgrupe.get(sg_id)
            
            if sg_obj:
                nume_grupa = f"{sg_obj.specializationShortName} • an {sg_obj.studyYear} • {sg_obj.groupName}{sg_obj.subgroupIndex}"
            else:
                nume_grupa = f"Grupa {sg_id}"

            nume_profesor = map_profesori.get(alt["teacherID"], "Nespecificat")
            nume_sala = map_sali.get(alt["roomId"], "Nespecificat")

            # Mapare Zi
            day_idx = int(alt["day"])
            nume_zi = ZILE_RO.get(day_idx - 1, "Necunoscut")

            processed_results.append({
                "grupa": nume_grupa,
                "zi": nume_zi,
                "ora_start": ora_start,
                "ora_final": ora_final,
                "profesor": nume_profesor,
                "sala": nume_sala,
                "saptamani_lista": actual_future_weeks,
                "saptamani_grupate": group_consecutive_weeks(alt["weeks"])
            })
        
        info_msg = None
        if not processed_results:
            if not raw_alternatives:
                info_msg = f"Nu există rezultate pentru filtrele selectate."
            else:
                info_msg = f"Toate sloturile pentru '{req.selected_subject}' s-au desfășurat deja. Nu mai sunt activități viitoare."

        return {
            "materie": req.selected_subject,
            "tip": req.selected_type,
            "total_optiuni": len(processed_results),
            "optiuni": processed_results,
            "saptamana_curenta": min(future_weeks_list) if future_weeks_list else None,
            "info_message": info_msg
        }

    except HTTPException as http_exc:
        # Re-aruncăm eroarea 400 fără să fie prinsă de Exception-ul de mai jos
        raise http_exc

    except Exception as e:
        print(f"❌ Eroare: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Eroare internă: {str(e)}")