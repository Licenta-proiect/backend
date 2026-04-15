# app\routers\subgroups.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Schedule, Subgroup, Professor, Room
from app.schemas.user import AlternativeSlotRequest
from app.services.reservation import get_reservations_by_subgroups
from app.services.alternative_slot import get_data_for_optimization, find_alternative_slots
from app.services.future_weeks import get_future_weeks_logic
from app.utils.time_helper import get_now
from app.utils.maintenance import verify_system_available

# Initialize router
router = APIRouter(
    prefix="/subgroups", 
    tags=["Subgroups"],
    dependencies=[Depends(verify_system_available)]
)

# Mapping for the index returned by date.weekday() (0=Monday ... 6=Sunday)
DAYS_RO = {
    0: "Luni", 1: "Marți", 2: "Miercuri", 3: "Joi",
    4: "Vineri", 5: "Sâmbătă", 6: "Duminică"
}

def group_consecutive_weeks(weeks):
    """
    Transforms [1, 2, 3, 5, 7, 8] into "1-3, 5, 7-8"
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

@router.get("/subjects")
async def get_subgroup_subjects(subgroup_id: int, db: Session = Depends(get_db)):
    """
    Returns the unique list of subjects for a specific subgroup.
    """
    # 1. Check if the subgroup exists in the database
    subgroup = db.query(Subgroup).filter(Subgroup.id == subgroup_id).first()
    if not subgroup:
        raise HTTPException(
            status_code=404, 
            detail="Subgrupa nu a fost găsită în baza de date."
        )

    # 2. Build the idURL identifier (e.g.: gID)
    group_id_url = f"g{subgroup_id}"

    # 3. Extract subjects (topic_long_name) from the Schedule table
    # Use .distinct() to avoid duplicates
    subjects_query = db.query(
        Schedule.topic_long_name, 
        Schedule.topic_short_name
    ).filter(
        Schedule.id_url == group_id_url,
        Schedule.topic_long_name.isnot(None),
        Schedule.topic_long_name != "",
        Schedule.type_short_name.isnot(None),
        Schedule.type_short_name != ""
    ).distinct().all()

    # 4. Convert result to a list of strings and sort alphabetically
    # Use m[0] because the query returns a list of tuples
    subjects_list = sorted(
        [
            {
                "longName": m.topic_long_name,
                "shortName": m.topic_short_name
            } 
            for m in subjects_query if m.topic_long_name
        ],
        key=lambda x: x["longName"]
    )

    return {
        "subgroup_id": subgroup_id,
        "subjects": subjects_list
    }

@router.post("/search-alternatives")
async def search_alternative_slots(
    req: AlternativeSlotRequest, 
    db: Session = Depends(get_db)
):
    """
    Searches for alternative slots for a specific subject, 
    checking student availability based on their group's schedule.
    """
    
    now = get_now()

    # Determine current semester and weeks that haven't passed yet
    current_semester, future_weeks_list, current_status, last_lecture_date = get_future_weeks_logic(db)
    future_weeks_set = set(future_weeks_list)

    # Obtain raw data from the service
    data = get_data_for_optimization(db, req)
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    
    if "info" in data:
        return {
            "subject": req.selected_subject,
            "type": req.selected_type,
            "total_options": 0,
            "options": [],
            "info_message": data["info"] # Map to info_message for frontend
        }

    # Check if we have physically passed the end date of week 14
    is_after_last_week = last_lecture_date and now > last_lecture_date
    if is_after_last_week:
        # All 14 weeks have ended -> Show status (Session/Vacation/etc.)
        raise HTTPException(
            status_code=400, 
            detail=f"Nu se pot căuta recuperări deoarece suntem în perioada de {current_status.lower()}."
        )
        
    try:
        # Run conflict detection algorithm
        raw_alternatives = find_alternative_slots(data, future_weeks_list)

        # Extract unique IDs for Subgroups, Professors, and Rooms
        subgroup_ids = {int(alt["idURL"].replace('g', '')) for alt in raw_alternatives}
        professor_ids = {alt["teacherID"] for alt in raw_alternatives if alt["teacherID"]}
        room_ids = {alt["roomId"] for alt in raw_alternatives if alt["roomId"]}

        # Bulk Queries (one query per table)
        subgroups_db = db.query(Subgroup).filter(Subgroup.id.in_(subgroup_ids)).all()
        professors_db = db.query(Professor).filter(Professor.id.in_(professor_ids)).all()
        rooms_db = db.query(Room).filter(Room.id.in_(room_ids)).all()

        # Transform lists into dictionaries for fast access by ID
        subgroups_map = {s.id: s for s in subgroups_db}
        professors_map = {p.id: f"{p.last_name} {p.first_name}" for p in professors_db}
        rooms_map = {r.id: r.name for r in rooms_db}

        # Process and filter future weeks
        processed_results = []

        for alt in raw_alternatives:
            # Intersect slot weeks with those that haven't passed yet
            actual_future_weeks = sorted(list(set(alt["weeks"]) & future_weeks_set))
            
            # If no valid weeks remain after filtering, skip this slot
            if not actual_future_weeks:
                continue

            # Time Calculation
            s_hour = int(alt["startHour"])
            duration = int(alt["duration"])
            e_hour = s_hour + duration
            start_time = f"{s_hour // 60:02d}:{s_hour % 60:02d}"
            end_time = f"{e_hour // 60:02d}:{e_hour % 60:02d}"

            # Retrieve data from previously created maps (No extra DB queries here)
            sg_id = int(alt["idURL"].replace('g', ''))
            sg_obj = subgroups_map.get(sg_id)
            
            if sg_obj:
                group_name = f"{sg_obj.specialization_short_name} • an {sg_obj.study_year} • {sg_obj.group_name}{sg_obj.subgroup_index}"
            else:
                group_name = f"Grupa {sg_id}"

            professor_name = professors_map.get(alt["teacherID"], "Nespecificat")
            room_name = rooms_map.get(alt["roomId"], "Nespecificat")

            # Day Mapping
            day_idx = int(alt["day"])
            day_name = DAYS_RO.get(day_idx - 1, "Necunoscut")

            processed_results.append({
                "group": group_name,
                "day": day_name,
                "start_time": start_time,
                "end_time": end_time,
                "professor": professor_name,
                "room": room_name,
                "weeks_list": actual_future_weeks,
                "weeks_grouped": group_consecutive_weeks(actual_future_weeks)
            })
        
        info_msg = None
        if not processed_results:
            if not raw_alternatives:
                info_msg = f"Nu există rezultate pentru filtrele selectate."
            else:
                info_msg = f"Toate sloturile pentru '{req.selected_subject}' s-au desfășurat deja. Nu mai sunt activități viitoare."

        return {
            "subject": req.selected_subject,
            "type": req.selected_type,
            "total_options": len(processed_results),
            "options": processed_results,
            "current_week": min(future_weeks_list) if future_weeks_list else None,
            "info_message": info_msg
        }

    except HTTPException as http_exc:
        # Re-raise 400 error without it being caught by the Exception block below
        raise http_exc

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Eroare internă: {str(e)}")
    
@router.get("/reservations")
def get_all_subgroup_reservations(db: Session = Depends(get_db)):
    """
    Returns the list of all make-up classes (reservations) in the system, 
    grouped by subgroup ID.
    """
    return get_reservations_by_subgroups(db)