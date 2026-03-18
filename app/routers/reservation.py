# app\routers\reservation.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.user import SlotReservationRequest, FreeSlotRequest, ReservationCancellationRequest
from app.models.models import User
from app.services.auth import get_current_user
from app.services.reservation import create_slot_reservation, cancel_reservation
from app.services.free_slot import get_schedule_and_reservation_data, find_free_slots_cp_sat, group_slots_for_ui
from app.services.future_weeks import get_future_weeks_logic

router = APIRouter(prefix="/reservations", tags=["Reservations"])

@router.post("/search-free")
def search_free_slots(req: FreeSlotRequest, db: Session = Depends(get_db)):
    """
    Returns free time intervals for a subject, a set of groups, and rooms,
    checking both the official schedule and existing ad-hoc reservations.
    """
    # Obtain current academic context (semester, remaining weeks)
    current_semester, active_weeks, _, _ = get_future_weeks_logic(db)

    # Extract blocking data (Official Schedule + Ad-hoc Reservations)
    data_result = get_schedule_and_reservation_data(db, req, current_semester)
    
    if "error" in data_result:
        raise HTTPException(status_code=400, detail=data_result["error"])
    if "info" in data_result:
        return {"info": data_result["info"], "slots": {}}

    # Filter target weeks (only future and academically valid ones)
    max_w = data_result.get("max_week_limit", 14)
    target_weeks = req.weeks if req.weeks else active_weeks
    
    filtered_weeks = [
        w for w in target_weeks 
        if w <= max_w and w in active_weeks
    ]

    if not filtered_weeks:
        return {"info": "Nicio săptămână selectată nu este validă sau viitoare.", "slots": {}}

    # Run the CP-SAT Solver
    duration_min = req.duration * 60 # Convert received hours to minutes
    
    free_slots_raw = find_free_slots_cp_sat(
        db=db,
        constraints=data_result,
        room_ids=req.room_ids,
        duration_minutes=duration_min,
        target_day=req.day,
        active_weeks=filtered_weeks
    )

    # Format for UI (grouping by weeks and days)
    ui_report = group_slots_for_ui(db, free_slots_raw, current_semester)

    return {
        "search_context": {
            "email": req.email,
            "subject": req.subject,
            "activityType": req.activity_type,
            "groupIds": req.group_ids,
            "duration": req.duration,
            "numberOfPeople": req.number_of_people or 0
        },
        "active_weeks": filtered_weeks,
        "slots": ui_report
    }

@router.post("/confirm-reservation")
def reserve_free_slot(
    req: SlotReservationRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Verify if user is logged in
):
    """
    Saves the user's chosen reservation in the database.
    Verifies if the email in the request matches the logged-in user's email.
    """

    # Ensure the logged-in professor is creating a 
    # reservation for their own email, not someone else's.
    if current_user.email != req.email:
        raise HTTPException(
            status_code=403, 
            detail="Nu aveți permisiunea de a crea o rezervare pentru alt profesor."
        )

    result = create_slot_reservation(db, req)
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result

@router.post("/cancel-reservation")
def cancel_existing_reservation(
    req: ReservationCancellationRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Cancels an existing reservation.
    Verifies if the logged-in user is the owner of the reservation.
    """
    
    # Verify identity (token must match the email in the request)
    if current_user.email != req.email:
        raise HTTPException(
            status_code=403, 
            detail="Puteți anula doar propriile rezervări."
        )

    # Call the cancellation service
    result = cancel_reservation(db, req)
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result