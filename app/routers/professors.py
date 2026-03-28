# app\routers\professors.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Professor, Schedule, Subgroup, Room, User
from app.services.auth import get_current_user
from app.services.reservation import get_teacher_reservations

# Initialize the router
router = APIRouter(prefix="/professor", tags=["Professors"])

@router.get("/subjects")
async def get_professor_subjects(email: str, db: Session = Depends(get_db)):
    """
    Returns the unique list of subjects taught by the professor 
    only to subgroups from the FIESC faculty.
    """
    # 1. Identify the professor to get their ID
    professor = db.query(Professor).filter(Professor.email_address == email).first()
    
    if not professor:
        raise HTTPException(
            status_code=404, 
            detail="Profesorul cu acest email nu a fost găsit în baza de date."
        )

    # 2. Search the Schedule for all subjects (topic_long_name) associated with this professor,
    # but filter only rows belonging to groups (id_url starts with 'g')
    # This filtering ensures you only see courses taught to your faculty.
    subjects_query = db.query(Schedule.topic_long_name).filter(
        Schedule.teacher_id == professor.id,
        Schedule.id_url.like('g%'),
        Schedule.topic_long_name.isnot(None),
        Schedule.topic_long_name != "",  
        Schedule.type_short_name.isnot(None), 
        Schedule.type_short_name != ""
    ).distinct().all()

    # 3. Convert the result into a unique list of strings, sorted alphabetically
    subjects_set = sorted([m[0] for m in subjects_query if m[0]])

    return {
        "id": professor.id,
        "lastName": professor.last_name,
        "firstName": professor.first_name,
        "subjects": subjects_set
    }

@router.get("/groups")
async def get_professor_groups(email: str, db: Session = Depends(get_db)):
    """
    Identifies the groups taught by the professor, limited to the FIESC faculty.
    """
    # 1. Identify the professor to get their ID
    professor = db.query(Professor).filter(Professor.email_address == email).first()
    if not professor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # 2. Search the Schedule for all group-type id_urls ('g...') where this professor appears
    # teacher_id is saved on all event rows (including group rows)
    groups_ids_query = db.query(Schedule.id_url).filter(
        Schedule.teacher_id == professor.id,
        Schedule.id_url.like('g%')
    ).distinct().all()

    # 3. Extract numerical IDs from the 'gID' format
    ids_set = {int(row[0][1:]) for row in groups_ids_query if row[0] and len(row[0]) > 1}

    if not ids_set:
        return {
            "id": professor.id,
            "lastName": professor.last_name,
            "firstName": professor.first_name,
            "groups": []
        }

    # 4. Get details from Subgroup and order directly from the query by name (group_name) and index (subgroup_index)
    groups_details = db.query(Subgroup).filter(
        Subgroup.id.in_(list(ids_set))
    ).order_by(
        Subgroup.group_name.asc(), 
        Subgroup.subgroup_index.asc()
    ).all()

    # 5. Send list of objects {id, name}
    result = [
        {
            "id": g.id,
            "name": g.group_name, 
            "subgroupIndex": g.subgroup_index if g.subgroup_index else '',
            "studyYear": g.study_year,
            "specializationShortName": g.specialization_short_name
        } for g in groups_details
    ]

    return {
        "id": professor.id,
        "lastName": professor.last_name,
        "firstName": professor.first_name,
        "groups": result
    }

@router.get("/rooms")
async def get_professor_rooms(email: str, db: Session = Depends(get_db)):
    """
    Identifies the rooms where the professor teaches, limited to FIESC groups.
    """
    # 1. Identify the professor to get their internal ID
    professor = db.query(Professor).filter(Professor.email_address == email).first()
    if not professor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # 2. Search the Schedule for all distinct room_ids for this professor
    # Use id_url.like('g%') to ensure we only get rooms from synchronized group schedules
    rooms_ids_query = db.query(Schedule.room_id).filter(
        Schedule.teacher_id == professor.id,
        Schedule.id_url.like('g%')
    ).distinct().all()

    # 3. Extract real room IDs from the room_id column (filtering None values)
    ids_set = {row[0] for row in rooms_ids_query if row[0] is not None}

    if not ids_set:
        return {
            "id": professor.id,
            "lastName": professor.last_name,
            "firstName": professor.first_name,
            "rooms": []
        }

    # 4. Get details from the Room table and order them alphabetically by name
    rooms_details = db.query(Room).filter(
        Room.id.in_(list(ids_set))
    ).order_by(Room.name.asc()).all()

    # 5. Send list of objects according to the Room model
    result = [
        {
            "id": s.id,
            "name": s.name,
            "shortName": s.short_name,
            "buildingName": s.building_name
        } for s in rooms_details
    ]

    return {
        "id": professor.id,
        "lastName": professor.last_name,
        "firstName": professor.first_name,
        "rooms": result
    }

@router.get("/groups-by-subject")
async def get_groups_by_subject(
    email: str, 
    subject: str, 
    activity_type: str, 
    db: Session = Depends(get_db)
):
    """
    Identifies the groups a professor teaches a specific subject to.
    - If 'Course': Includes merged classes based on same time/room.
    - If others (Lab/Seminar): Returns exact groups assigned to that subject/type/prof.
    """
    # 1. Identify the professor
    professor = db.query(Professor).filter(Professor.email_address == email).first()
    if not professor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # 2. Obtain the "anchor" data set (groups that have the subject with the exact name)
    # Search group-type records ('g%')
    anchor_query = db.query(Schedule).filter(
        Schedule.teacher_id == professor.id,
        Schedule.id_url.like('g%'),
        func.lower(Schedule.topic_long_name) == func.lower(subject)
    )
    
    if activity_type:
        anchor_query = anchor_query.filter(func.lower(Schedule.type_long_name) == func.lower(activity_type))
        
    anchor_rows = anchor_query.all()
    
    # Initial group IDs and their short names for cross-checking
    ids_set = {int(row.id_url[1:]) for row in anchor_rows if row.id_url and len(row.id_url) > 1}
    
    # 3. Logic for MERGED COURSES (Based on time and space)
    if activity_type and "curs" in activity_type.lower() and anchor_rows:
        for row in anchor_rows:
            # Search for simultaneous events: same professor, same room, same time interval
            # Even if the subject has a slightly different name (e.g., "Special Mathematics" vs "Analysis")
            potential_merged = db.query(Schedule).filter(
                Schedule.teacher_id == professor.id,
                Schedule.id_url.like('g%'),
                Schedule.week_day == row.week_day,
                Schedule.start_hour == row.start_hour,
                Schedule.duration == row.duration,
                Schedule.room_id == row.room_id,
                Schedule.type_long_name == row.type_long_name # Also a Course
            ).all()

            for p in potential_merged:
                try:
                    p_id = int(p.id_url[1:])
                    # If we found another simultaneous course, add it automatically.
                    # Room + Time + Professor coincidence is proof of merging in the schedule.
                    if p_id not in ids_set: 
                        ids_set.add(p_id)
                except (ValueError, IndexError):
                    continue

    if not ids_set:
        return {
            "id": professor.id,
            "lastName": professor.last_name,
            "firstName": professor.first_name,
            "subject": subject,
            "groups": [],
            "selected_type": activity_type,
        }

    # 4. Get full details for all collected IDs
    groups_details = db.query(Subgroup).filter(
        Subgroup.id.in_(list(ids_set))
    ).order_by(
        Subgroup.group_name.asc(), 
        Subgroup.subgroup_index.asc()
    ).all()

    result = [
        {
            "id": g.id,
            "name": g.group_name, 
            "subgroupIndex": g.subgroup_index if g.subgroup_index else '',
            "studyYear": g.study_year,
            "specializationShortName": g.specialization_short_name
        } for g in groups_details
    ]

    return {
        "id": professor.id,
        "lastName": professor.last_name,
        "firstName": professor.first_name,
        "subject": subject,
        "selected_type": activity_type,
        "groups": result
    }

@router.get("/rooms-by-subject")
async def get_rooms_by_subject(
    email: str, 
    subject: str, 
    activity_type: str, 
    db: Session = Depends(get_db)
):
    """
    Identifies the rooms where a specific professor teaches a specific subject,
    filtered by activity type (Course, Lab, etc.).
    """
    # 1. Identify the professor by email
    professor = db.query(Professor).filter(Professor.email_address == email).first()
    if not professor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # 2. Search Schedule for all distinct room_ids where the professor teaches that subject
    # Use id_url.like('g%') to limit results to synchronized group schedules
    rooms_ids_query = db.query(Schedule.room_id).filter(
        Schedule.teacher_id == professor.id,
        Schedule.id_url.like('g%'),
        func.lower(Schedule.topic_long_name) == func.lower(subject),
        func.lower(Schedule.type_long_name) == func.lower(activity_type)
    ).distinct().all()

    # Extract numerical room IDs (filtering null values)
    primary_ids = {row[0] for row in rooms_ids_query if row[0] is not None}

    # 3. SUGGESTIONS Logic
    suggested_ids = set()

    if activity_type and "curs" in activity_type.lower():
        # Suggest all Amphitheaters (rooms containing 'Amf')
        amf_query = db.query(Room.id).filter(
            Room.has_schedule == True,
            Room.name.ilike('%amf%')
        ).all()
        suggested_ids.update({r[0] for r in amf_query})

    # 4. Fetch all room details
    all_target_ids = primary_ids.union(suggested_ids)
    
    if not all_target_ids:
        return {
            "id": professor.id,
            "lastName": professor.last_name,
            "firstName": professor.first_name,
            "subject": subject,
            "rooms": []
        }

    # 5. Get details from the Room table and order them alphabetically by name
    rooms_details = db.query(Room).filter(
        Room.id.in_(list(all_target_ids))
    ).order_by(Room.name.asc()).all()

    # 6. Format the result similar to the /rooms route
    result = [
        {
            "id": s.id,
            "name": s.name,
            "shortName": s.short_name,
            "buildingName": s.building_name
        } for s in rooms_details
    ]

    return {
        "id": professor.id,
        "lastName": professor.last_name,
        "firstName": professor.first_name,
        "subject": subject,
        "rooms": result
    }

@router.get("/reservations")
def list_professor_reservations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns the list of all reservations made by the logged-in professor,
    with statuses updated based on time.
    """
    return get_teacher_reservations(db, current_user.email)