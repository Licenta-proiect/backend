from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.user import SlotLiberRequest
from app.services.slot_liber import get_data, find_free_slots_cp_sat, group_slots_for_ui
from app.services.future_weeks import get_future_weeks_logic

router = APIRouter(prefix="/rezervari", tags=["Rezervări"])

@router.post("/cauta-libere")
def cauta_sloturi_libere(req: SlotLiberRequest, db: Session = Depends(get_db)):
    """
    Returnează intervalele libere pentru o materie, un set de grupe și săli,
    verificând atât orarul oficial cât și rezervările existente.
    """
    # Obținem contextul academic curent (semestru, săptămâni rămase)
    current_semester, active_weeks, _, _ = get_future_weeks_logic(db)

    # Extragem datele de blocaj (Orar + Rezervări)
    data_result = get_data(db, req, current_semester)
    
    if "error" in data_result:
        raise HTTPException(status_code=400, detail=data_result["error"])
    if "info" in data_result:
        return {"info": data_result["info"], "slots": {}}

    # Filtrăm săptămânile target (doar cele viitoare și valide academic)
    max_w = data_result.get("max_week_limit", 14)
    target_weeks = req.saptamani if req.saptamani else active_weeks
    
    filtered_weeks = [
        w for w in target_weeks 
        if w <= max_w and w in active_weeks
    ]

    if not filtered_weeks:
        return {"info": "Nicio săptămână selectată nu este validă sau viitoare.", "slots": {}}

    # Rulăm Solver-ul CP-SAT
    durata_min = req.durata * 60 # Convertim orele primite în minute
    
    free_slots_raw = find_free_slots_cp_sat(
        db=db,
        constraints=data_result,
        sali_ids=req.sali_ids,
        duration_minutes=durata_min,
        target_day=req.zi,
        active_weeks=filtered_weeks
    )

    # Formatăm pentru UI (grupare pe săptămâni și zile)
    ui_report = group_slots_for_ui(db, free_slots_raw, current_semester)

    return {
        "semester": current_semester,
        "active_weeks": filtered_weeks,
        "slots": ui_report
    }