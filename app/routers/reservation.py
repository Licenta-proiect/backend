# app\routers\reservation.py
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.user import AdminCancelEventRequest, AdminEventConfirmationRequest, SlotReservationRequest, FreeSlotRequest, ReservationCancellationRequest
from app.models.models import User
from app.services.auth import get_current_user
from app.services.reservation import cancel_admin_event, create_admin_event_reservation, create_slot_reservation, cancel_reservation
from app.services.free_slot import get_schedule_and_reservation_data, find_free_slots_cp_sat, group_slots_for_ui
from app.services.future_weeks import get_future_weeks_logic
from app.services.admin_search import find_admin_free_slots
from app.schemas.user import AdminEventRequest
from app.models.models import UserRole
from app.utils.time_helper import get_now

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

@router.post("/search-admin-event")
def search_admin_event_slots(
    req: AdminEventRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint dedicated to the administrator to find free slots over a date range.
    Checks for hybrid overlaps (Schedule + Reservations).
    """
    
    # 1. Security: Only administrators can use this hybrid search
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Acces interzis. Doar administratorii pot planifica evenimente."
        )
    
    # --- TIME CHECK ---
    now = get_now()
    today = now.date()

    # Case 1: The entire range ends strictly before today
    if req.end_date < today:
        raise HTTPException(
            status_code=400, 
            detail="Nu se pot căuta sloturi libere pentru o perioadă care a trecut deja."
        )
    
    # Case 2: The range ends today (same-day reservations are not allowed)
    # This covers cases where both start and end are today, or just the end is today.
    if req.end_date == today:
        raise HTTPException(
            status_code=400,
            detail="Nu se pot face rezervări în aceeași zi."
        )

    # Case 3: The range starts in the past or today but ends in the future
    # We adjust the start date to tomorrow (today + 1 day) since today is not allowed
    if req.start_date <= today:
        req.start_date = today + timedelta(days=1)

    # 2. Calling the range search service
    try:
        results = find_admin_free_slots(db, req)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Eroare internă la procesarea solverului.")

    # 3. If no slots are found, return an object with an empty list and info
    if not results:
        return {
            "info": "Nu s-au găsit sloturi disponibile pentru criteriile selectate în acest interval.", 
            "days": []
        }

    # 4. Return structured results by days
    return {
        "search_context": {
            "subject": req.subject,
            "duration": req.duration,
            "rooms": req.room_ids,
            "professors": req.professor_ids,
            "subgroups": req.subgroup_ids
        },
        "days": results
    }

@router.post("/confirm-admin-event")
def confirm_admin_event(
    req: AdminEventConfirmationRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    The route for the administrator who acknowledges and saves the event.
    """
    # Security: Only administrators can use this hybrid search
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403, 
            detail="Doar administratorii pot rezerva evenimente."
        )

    result = create_admin_event_reservation(db, req)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result

@router.post("/cancel-admin-event")
def cancel_admin_event_route(
    req: AdminCancelEventRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint for administrators to cancel any event.
    """
    # Security check: Must be ADMIN
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403, 
            detail="Acces interzis. Doar administratorii pot anula evenimente administrative."
        )

    # Call service
    result = cancel_admin_event(db, req.reservation_id, req.reason)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result