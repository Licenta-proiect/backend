# app\services\slot_alternativ.py

from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.models import Schedule, Subgroup 
from app.schemas.user import AlternativeSlotRequest
from typing import Set, List, Dict, Any
import re

def format_row(row):
    return {
        "id": row.id,
        "idURL": row.id_url,          
        "teacherID": row.teacher_id,   
        "roomId": row.room_id,         
        "topicLongName": row.topic_long_name, 
        "typeLongName": row.type_long_name,   
        "weekDay": row.week_day,       
        "startHour": row.start_hour,   
        "duration": row.duration,
        "parity": row.parity,
        "otherInfo": row.other_info    
    }

def check_subject_existence(db: Session, subgroup_id: int, subject: str, activity_type: str) -> bool:
    """
    Checks the 'schedule' table to see if the subgroup has the specified subject and activity type.
    Filtering is done using the 'g' prefix before the subgroup ID for idURL.
    """
    # Build the target ID: g + ID (e.g., "g44")
    target_id_url = f"g{subgroup_id}"
    
    schedule_row = db.query(Schedule).filter(
        Schedule.id_url == target_id_url,
        func.lower(Schedule.topic_long_name) == func.lower(subject),
        func.lower(Schedule.type_long_name) == func.lower(activity_type)
    ).first()
    
    return schedule_row is not None

def get_compatible_subgroups(db: Session, selected_subgroup_id: int, subject: str, activity_type: str) -> Set[int]:
    """
    Returns a set of subgroup IDs that the student could potentially attend (same specialization/year).
    """
    # 1. Retrieve reference data for the selected group
    subgroup_ref = db.query(Subgroup).filter(Subgroup.id == selected_subgroup_id).first()
    
    if not subgroup_ref:
        return set()

    # 2. Search for potential subgroups (same faculty, specialization, year)
    potential_groups = db.query(Subgroup).filter(
        Subgroup.has_schedule == True,
        Subgroup.faculty_id == subgroup_ref.faculty_id,
        func.lower(Subgroup.specialization_short_name) == func.lower(subgroup_ref.specialization_short_name),
        Subgroup.study_year == subgroup_ref.study_year,
        Subgroup.id != selected_subgroup_id # Exclude the user's own group
    ).all()

    # 3. Filter only those groups that actually have the subject and type in their schedule
    valid_ids = set()
    for sg in potential_groups:
        if check_subject_existence(db, sg.id, subject, activity_type):
            valid_ids.add(sg.id)
            
    return valid_ids

def get_data_for_optimization(db: Session, req: AlternativeSlotRequest):
    '''
    Extracts two sets of data: the current group's constraints (when the student is busy) 
    and slot options from compatible groups.
    '''
    # 1. Verify if the selected group has the requested subject and type
    if not check_subject_existence(db, req.selected_group_id, req.selected_subject, req.selected_type):
        return {"info": "Grupa selectată nu are această materie sau tip de activitate în orar."}

    # 2. Extract "busy intervals" for the selected group (Constraints)
    # These are the hours when the student CANNOT attend a makeup session
    target_id_url = f"g{req.selected_group_id}"
    
    student_query = db.query(Schedule).filter(Schedule.id_url == target_id_url)
    
    # If attends_course is False, remove courses from the busy list
    if not req.attends_course:
        student_query = student_query.filter(func.lower(Schedule.type_long_name) != func.lower("course"))
    
    student_busy_slots = student_query.all()

    # 3. Identify compatible groups (same specialization, year, etc.)
    compatible_group_ids = get_compatible_subgroups(
        db, req.selected_group_id, req.selected_subject, req.selected_type
    )

    # If no other subgroup has this subject
    if not compatible_group_ids:
        return {
            "info": f"Există o singură grupă în anul de studiu și specializarea selectată. "
            "Prin urmare, nu există alternative pentru recuperare."
        }

    # 4. Extract "candidate slots" from other groups
    # Search only for occurrences of the requested subject and type in compatible groups
    potential_slots = []
    if compatible_group_ids:
        # Build the list of idURLs: ["g45", "g46", ...]
        compatible_id_urls = [f"g{gid}" for gid in compatible_group_ids]
        
        potential_slots = db.query(Schedule).filter(
            Schedule.id_url.in_(compatible_id_urls),
            func.lower(Schedule.topic_long_name) == func.lower(req.selected_subject),
            func.lower(Schedule.type_long_name) == func.lower(req.selected_type)
        ).all()

    # 5. Format data for the algorithm
    return {
        "student_constraints": [format_row(row) for row in student_busy_slots],
        "potential_alternatives": [format_row(row) for row in potential_slots]
    }

def parse_weeks_from_info(other_info, parity):
    """
    Determines active weeks (1-14). 
    RULES: 
    1. If week hints (s, S, sapt, week) exist in text, extract everything.
    2. Supports ranges like: "1-10", "S1-S10", "Week 1 - Week 10".
    3. Ignores numbers followed by 'h' (durations).
    """
    all_weeks = set(range(1, 15))
    extracted_from_text = set()

    if other_info:
        # 1. Remove durations like "2.5h", "2h", "1.5 h" from text to avoid polluting the search
        # Use regex to delete any number followed by 'h'
        text = re.sub(r'\d+(\.\d+)?\s*h', '', other_info.lower())
        
        # 2. Extract complex ranges: look for (optional prefix + digit) - (optional prefix + digit)
        # Regex: (optional prefix) (digit1) hyphen (optional prefix) (digit2)
        range_matches = re.findall(r'(?:s(?:apt)?\.?\s*)?(\d+)\s*-\s*(?:s(?:apt)?\.?\s*)?(\d+)', text)
        
        for start, end in range_matches:
            s, e = int(start), int(end)
            if 1 <= s <= 14 and 1 <= e <= 14:
                # Correct order if reversed (e.g., 10-1)
                low, high = min(s, e), max(s, e)
                extracted_from_text.update(range(low, min(high + 1, 15)))

        # 3. Extract individual weeks (not caught in ranges or standalone)
        individual_with_prefix = re.findall(r'(?:s(?:apt)?\.?\s*|\+\s*|\b)(\d+)(?!\s*h)', text)
        for val in individual_with_prefix:
            v = int(val)
            if 1 <= v <= 14:
                extracted_from_text.add(v)

        # 4. Handling the special case where the weeks are listed after the comma or +
        # If the text already contains keywords of the week, we look for isolated numbers
        if any(kw in text for kw in ["sapt", "s.", "s "]):
            # We are looking for numbers that are not durations (they don't have h stuck to them)
            # but they are in enumeration context
            isolated_nums = re.findall(r'(?<!\d)(\d+)(?!\s*h)', text)
            for val in isolated_nums:
                v = int(val)
                if 1 <= v <= 14:
                    # We check whether it is the start time/duration (eg: 18-20)
                    # A week in a valid context usually has small values ​​1-14
                    extracted_from_text.add(v)

    # DECISION LOGIC
    if extracted_from_text:
        # If weeks were found in text, return ONLY those (ignore parity)
        return extracted_from_text

    # FALLBACK: If text provided nothing, use parity
    if parity == 1: # Odd
        return {w for w in all_weeks if w % 2 != 0}
    elif parity == 2: # Even
        return {w for w in all_weeks if w % 2 == 0}
    
    # If nothing else, return the whole semester
    return all_weeks

def find_alternative_slots(data):
    results = []
    student_days_map = {i: [] for i in range(1, 7)}
    
    for i, slot in enumerate(data["student_constraints"]):
        day = int(slot["weekDay"])
        if day in student_days_map:
            student_days_map[day].append({
                "start": int(slot["startHour"]),
                "end": int(slot["startHour"]) + int(slot["duration"]),
                "weeks": parse_weeks_from_info(slot["otherInfo"], slot["parity"])
            })

    for alt in data["potential_alternatives"]:
        weeks_alt = parse_weeks_from_info(alt["otherInfo"], alt["parity"])
        d_alt = int(alt["weekDay"])
        s_alt = int(alt["startHour"])
        e_alt = s_alt + int(alt["duration"])
        
        relevant_student_slots = student_days_map.get(d_alt, [])
        valid_weeks_for_this_alt = []

        for w in sorted(list(weeks_alt)):
            has_conflict = False
            for s_slot in relevant_student_slots:
                if w in s_slot["weeks"]:
                    # Classic interval intersection check:
                    # (StartA < EndB) AND (EndA > StartB)
                    if s_alt < s_slot["end"] and e_alt > s_slot["start"]:
                        has_conflict = True
                        break
            
            if not has_conflict:
                valid_weeks_for_this_alt.append(w)

        if valid_weeks_for_this_alt:
            results.append({
                "idURL": alt["idURL"],
                "day": d_alt,
                "startHour": s_alt,
                "formattedTime": f"{s_alt//60:02d}:{s_alt%60:02d}",
                "duration": alt["duration"],
                "teacherID": alt["teacherID"],
                "roomId": alt["roomId"],
                "weeks": valid_weeks_for_this_alt,
                "topic": alt["topicLongName"],
                "type": alt["typeLongName"]
            })

    sorted_results = sorted(results, key=lambda x: (x["day"], x["startHour"]))
    
    return sorted_results

if __name__ == "__main__":
    from app.db.session import SessionLocal
    import json

    # Simulated request data from frontend via Pydantic schema
    test_request = AlternativeSlotRequest(
        selectedGroupId=49,
        selectedSubject="Recunoaşterea formelor",
        selectedType="laborator",
        attendsCourse=False
    )

    db_session = SessionLocal()
    try:
        print(f"--- Starting testing for Group {test_request.selected_group_id} ---")
        data = get_data_for_optimization(db_session, test_request)
        
        if "error" in data:
            print(f"❌ Error: {data['error']}")
        elif "info" in data:
            print(f"ℹ️ Info: {data['info']}")
        else:
            alternatives = find_alternative_slots(data)
            print(f"Found {len(alternatives)} compatible slots:")
            for res in alternatives:
                print(f"Group: {res['idURL']} | Day: {res['day']} | Time: {res['formattedTime']} | Weeks: {res['weeks']}")
                
    except Exception as e:
        print(f"❌ Unexpected error during testing: {e}")
    finally:
        db_session.close()