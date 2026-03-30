# app\routers\data.py
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Subgroup, Professor, Room, Schedule
from app.schemas.user import WeeksRequest
from app.services.future_weeks import get_future_weeks_logic
from app.services.free_slot import get_max_week_for_groups

router = APIRouter(prefix="/data", tags=["Data"])

@router.get("/professors")
async def get_active_professors(db: Session = Depends(get_db)):
    """
    Returns professors who have their schedule downloaded (has_schedule=True).
    """
    professors = db.query(Professor).filter(
        Professor.has_schedule == True
    ).order_by(Professor.last_name.asc(), Professor.first_name.asc()).all()
    
    return [
        {
            "id": p.id,
            "lastName": p.last_name,
            "firstName": p.first_name,
            "emailAddress": p.email_address,
            "positionShortName": p.position_short_name,
            "phdShortName": p.phd_short_name,
            "otherTitle": p.other_title
        } for p in professors
    ]

@router.get("/rooms")
async def get_active_rooms(db: Session = Depends(get_db)):
    """
    Returns rooms that have their schedule downloaded (has_schedule=True).
    """
    rooms = db.query(Room).filter(
        Room.has_schedule == True
    ).order_by(Room.name.asc()).all()
    
    return [
        {
            "id": s.id,
            "name": s.name,
            "shortName": s.short_name,
            "buildingName": s.building_name
        } for s in rooms
    ]

@router.get("/groups")
async def get_active_groups(db: Session = Depends(get_db)):
    """
    Returns groups that have their schedule downloaded (has_schedule=True).
    """
    groups = db.query(Subgroup).filter(
        Subgroup.has_schedule == True
    ).order_by(Subgroup.specialization_short_name, Subgroup.group_name.asc(), Subgroup.subgroup_index.asc()).all()
    
    return [
        {
            "id": g.id,
            "name": g.group_name, 
            "subgroupIndex": g.subgroup_index if g.subgroup_index else '',
            "studyYear": g.study_year,
            "specializationShortName": g.specialization_short_name
        } for g in groups
    ]

@router.get("/groups-hierarchical")
async def get_groups_hierarchical(db: Session = Depends(get_db)):
    """
    Returns subgroups grouped hierarchically: Specialization -> Study Year -> Group/Subgroup.
    Ideal for complex selectors (TreeSelect) in the Admin dashboard.
    """
    # 1. Fetch all subgroups that have a schedule, ordered for easier processing
    groups = db.query(Subgroup).filter(
        Subgroup.has_schedule == True
    ).order_by(
        Subgroup.specialization_short_name, 
        Subgroup.study_year, 
        Subgroup.group_name.asc(), 
        Subgroup.subgroup_index.asc()
    ).all()

    hierarchical_data = {}

    # 2. Build the nested dictionary structure
    for g in groups:
        spec = g.specialization_short_name
        year = g.study_year
        
        # Initialize Specialization if it doesn't exist
        if spec not in hierarchical_data:
            hierarchical_data[spec] = {}
            
        # Initialize Year within the Specialization
        if year not in hierarchical_data[spec]:
            hierarchical_data[spec][year] = []
            
        # Add the subgroup to the corresponding list
        hierarchical_data[spec][year].append({
            "value": g.id,
            "label": f"{g.specialization_short_name} an {g.study_year} {g.group_name}{g.subgroup_index if g.subgroup_index else ''}"
        })

    # 3. Transform the dictionary into a list structure (Array of Objects) for the Frontend
    result = []
    for spec_name, years in hierarchical_data.items():
        spec_node = {
            "label": spec_name,
            "value": spec_name,  # Unique key for the tree node
            "children": []
        }
        for year_name, subgroups in years.items():
            year_node = {
                "label": year_name,
                "value": f"{spec_name} {year_name}",
                "children": subgroups
            }
            spec_node["children"].append(year_node)
        result.append(spec_node)

    return result

@router.get("/activity-type")
async def get_activity_types(db: Session = Depends(get_db)):
    """
    Returns unique activity types (Lecture, Lab, Seminar, etc.)
    extracted directly from the type_long_name column of the Schedule table.
    """
    # Extract distinct values from the type_long_name column
    query = db.query(Schedule.type_long_name).distinct().all()
    
    # Convert list of tuples to list of strings, removing None values (if any)
    types = sorted([t[0] for t in query if t[0]])
    
    return types

@router.get("/weeks")
async def get_future_weeks(db: Session = Depends(get_db)):
    """
    Returns the current semester, remaining lecture weeks, and current status.
    """
    current_semester, active_weeks, current_status, last_lecture_date = get_future_weeks_logic(db)
    
    return {
        "current_semester": current_semester,
        "active_weeks": active_weeks,
        "current_status": current_status
    }

@router.post("/valid-weeks")
async def get_valid_weeks(req: WeeksRequest, db: Session = Depends(get_db)):
    '''
    Returns valid weeks for groups, taking into account the year of study.
    '''
    # Extract the list from the received JSON object
    group_ids = req.group_ids
    
    # Determine the semester and general lecture weeks from the calendar
    current_semester, active_weeks, _, _ = get_future_weeks_logic(db)
    
    # Determine the upper limit for the selected groups (10 or 14)
    max_week_limit = get_max_week_for_groups(db, group_ids, current_semester)
    
    # Filter active weeks that exceed the group limit
    filtered_weeks = [w for w in active_weeks if w <= max_week_limit]
    
    return {
        "active_weeks": filtered_weeks,
        "max_week_limit": max_week_limit
    }

@router.get("/professor-activity-types")
async def get_professor_activity_types(
    email: str, 
    subject: str, 
    db: Session = Depends(get_db)
):
    """
    Returns activity types (Lecture, Lab, etc.) that a professor
    has in their schedule for a specific subject.
    """
    # Find the professor by email to get their ID
    professor = db.query(Professor).filter(Professor.email_address == email).first()
    if not professor:
        return []

    # Construct the search string for id_url (format p + id)
    prof_url_id = f"p{professor.id}"

    # Search in Schedule for distinct types
    # Check where id_url matches professor id and subject matches
    query = db.query(Schedule.type_long_name).distinct().filter(
        Schedule.id_url == prof_url_id,
        func.lower(Schedule.topic_long_name) == func.lower(subject)
    ).all()

    # Clean the results
    types = sorted([t[0] for t in query if t[0]])

    return types

@router.get("/group-activity-types")
async def get_group_activity_types(
    group_id: int, 
    subject: str, 
    db: Session = Depends(get_db)
):
    """
    Returns unique activity types (Lecture, Lab, etc.) excluding 'Curs' 
    that a specific subgroup has in its schedule.
    """
    # Verify if the subgroup exists
    group = db.query(Subgroup).filter(Subgroup.id == group_id).first()
    if not group:
        return []

    # Construct the search string for id_url (format g + id)
    group_url_id = f"g{group.id}"

    # Query the Schedule table for distinct activity types
    # Case-insensitive match for the subject name
    query = db.query(Schedule.type_long_name).distinct().filter(
        Schedule.id_url == group_url_id,
        func.lower(Schedule.topic_long_name) == func.lower(subject),
        func.lower(Schedule.type_long_name) != "curs"
    ).all()

    # Extract strings from tuples and sort them
    activity_types = sorted([t[0] for t in query if t[0]])

    return activity_types