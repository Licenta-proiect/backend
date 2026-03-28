# app\services\alternative_slot.py

from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.models.models import Schedule 
from app.schemas.user import AlternativeSlotRequest
from typing import Dict
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

def get_compatible_subgroups(db: Session, selected_subgroup_id: int, subject: str) -> Dict[int, str]:
    """
    Identifies peer groups sharing the same lecture and returns a dictionary 
    containing the group ID and the subject name as it appears in each group's schedule.
    """
    group_tag = f"g{selected_subgroup_id}"

    # 1. Find the lecture slot of the reference group
    course_slots = db.query(Schedule).filter(
        Schedule.id_url == group_tag,
        func.lower(Schedule.topic_long_name) == func.lower(subject),
        func.lower(Schedule.type_long_name).like('%curs%')
    ).all()

    if not course_slots:
        return {}

    # Dictionary: {subgroup_id: specific_subject_name}
    peer_data = {}

    for slot in course_slots:
        # 2. Search for all lecture entries in the same time interval/room/professor
        # Extract both id_url and topic_long_name for each group found
        peers = db.query(Schedule.id_url, Schedule.topic_long_name).filter(
            Schedule.id_url.like('g%'),
            Schedule.week_day == slot.week_day,
            Schedule.start_hour == slot.start_hour,
            Schedule.room_id == slot.room_id,
            Schedule.teacher_id == slot.teacher_id,
            func.lower(Schedule.type_long_name).like('%curs%')
        ).distinct().all()
        
        for p_id_url, p_topic in peers:
            try:
                gid = int(p_id_url[1:])
                if gid != selected_subgroup_id:
                    # Save the exact subject name for this specific group
                    peer_data[gid] = p_topic
            except (ValueError, IndexError):
                continue

    return peer_data

def get_data_for_optimization(db: Session, req: AlternativeSlotRequest):
    '''
    Extracts two sets of data: the current group's constraints (when the student is busy) 
    and slot options from compatible groups.
    '''

    # Extract "busy intervals" for the selected group (Constraints)
    # These are the hours when the student CANNOT attend a makeup session
    target_id_url = f"g{req.selected_group_id}"
    
    student_query = db.query(Schedule).filter(Schedule.id_url == target_id_url)
    
    # If attends_course is False, remove courses from the busy list
    if not req.attends_course:
        student_query = student_query.filter(func.lower(Schedule.type_long_name) != func.lower("curs"))
    
    student_busy_slots = student_query.all()

    # Identify compatible groups
    compatible_info = get_compatible_subgroups(db, req.selected_group_id, req.selected_subject)

    if not compatible_info:
        return {"info": "Nu s-au găsit grupe alternative compatibile."}

    # Optimized extraction of candidate slots using OR logic
    # We create a list of conditions: (GroupID AND specific SubjectName)
    group_filters = []
    for gid, specific_subject in compatible_info.items():
        # Search the schedule of that specific group for slots that:
        # - Belong to that group (id_url)
        # - Are of the requested type (Lab/Seminar/Project)
        # - MATCH THE SUBJECT NAME as it appears in that group's schedule
        group_filters.append(
            (Schedule.id_url == f"g{gid}") & 
            (func.lower(Schedule.topic_long_name) == func.lower(specific_subject.lower()))
        )

    # Fetch all relevant Lab/Sem slots for all compatible groups in one go
    potential_slots = db.query(Schedule).filter(
        func.lower(Schedule.type_long_name) == func.lower(req.selected_type),
        or_(*group_filters)
    ).all()

    if not potential_slots:
        return {
            "info": f"Materia a fost găsită la alte grupe, dar nu există sloturi de tip {req.selected_type} programate."
        }

    # Format data for the algorithm
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