# app\services\free_slot.py
from datetime import datetime
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from app.models.models import Schedule, Subgroup, Professor, Room, Reservation
from app.schemas.user import FreeSlotRequest
from app.utils.time_helper import get_now
from typing import List
import hashlib
from ortools.sat.python import cp_model

from app.services.future_weeks import get_future_weeks_logic
from app.utils.date_helper import get_calendar_date
from .alternative_slot import format_row, parse_weeks_from_info

def format_reservation_to_schedule(res: Reservation, tag: str):
    """
    Transforms a Reservation object into a dictionary compatible with format_row,
    to be processed uniformly by the solver.
    """
    return {
        "idURL": tag,
        "weekDay": res.day_of_week,
        "startHour": res.start_time_minutes,
        "duration": res.duration,
        "parity": 0,  # Ad-hoc reservations are specific to a single week
        "otherInfo": f"S{res.week_number}" 
    }

def get_professor_id_by_email(db: Session, email: str):
    '''Identifies the professor in the database using the email address.'''
    professor = db.query(Professor).filter(Professor.email_address == email).first()
    
    if not professor:
        return None
    
    return professor.id

def get_max_week_for_groups(db: Session, group_ids: List[int], current_semester: int) -> int:
    """
    Determines the maximum week (10 or 14) based on the selected groups.
    - Returns 10 if ALL selected groups are in their terminal year during Semester 2.
    """
    if current_semester == 1:
        return 14

    groups = db.query(Subgroup).filter(Subgroup.id.in_(group_ids)).all()
    if not groups:
        return 14

    all_terminal = True
    
    for g in groups:
        is_this_group_terminal = False

        # License (type "1"): Terminal year (max_year) but at least year 3
        if g.type == "1":
            if g.study_year == 4:
                is_this_group_terminal = True

        # Master or others: Just needs to be the max year
        else:
            if g.study_year == 2:
                is_this_group_terminal = True

        if not is_this_group_terminal:
            all_terminal = False
            break 
            
    return 10 if all_terminal else 14

def validate_group_configuration(group_ids: List[int], activity_type: str):
    """
    Validates if the number of selected groups is allowed for the activity type.
    """
    a_type = activity_type.lower()
    num_groups = len(group_ids)

    if a_type in ["laborator", "proiect"] and num_groups > 1:
        return {
            "info": f"Pentru activități de tip {activity_type}, se poate selecta o singură grupă."
        }
    
    if a_type == "seminar" and num_groups > 2:
        return {
            "info": "Pentru activități de tip seminar, se pot selecta maxim 2 grupe."
        }
    
    return None

def check_subject_existence(db: Session, professor_id: int, group_ids: List[int], subject: str, activity_type: str) -> bool:
    """
    Checks if the subject exists in the schedule for both professor and groups.
    """
    type_lower = activity_type.lower()
    
    # 1. Subject must exist in the professor's schedule
    prof_record = db.query(Schedule).filter(
        Schedule.id_url == f"p{professor_id}",
        Schedule.teacher_id == professor_id,
        func.lower(Schedule.topic_long_name) == func.lower(subject),
        func.lower(Schedule.type_long_name) == func.lower(activity_type)
    ).all()

    if not prof_record:
        return False

    # 2. Validation for each group
    for gid in group_ids:
        group_tag = f"g{gid}"
        found_for_group = False
        
        if "curs" in type_lower:
            for anchor in prof_record:
                match_query = db.query(Schedule).filter(
                    Schedule.id_url == group_tag,
                    Schedule.teacher_id == professor_id,
                    Schedule.week_day == anchor.week_day,
                    Schedule.start_hour == anchor.start_hour,
                    Schedule.duration == anchor.duration,
                    Schedule.room_id == anchor.room_id,
                    func.lower(Schedule.type_long_name) == type_lower
                ).first()

                if match_query:
                    found_for_group = True
                    break
            
            if not found_for_group:
                return False
        else:
            # Lab/Sem/Project: Exact match
            group_has_exact_topic = db.query(Schedule).filter(
                Schedule.id_url == group_tag,
                Schedule.teacher_id == professor_id,
                func.lower(Schedule.topic_long_name) == func.lower(subject),
                func.lower(Schedule.type_long_name) == type_lower
            ).first()
            
            if not group_has_exact_topic:
                return False

    return True

def get_schedule_and_reservation_data(db: Session, req: FreeSlotRequest, current_semester: int):
    '''Extracts data from schedule AND reservations for professor, subgroups, and rooms.'''
    validation = validate_group_configuration(req.group_ids, req.activity_type)
    if validation:
        return validation
    
    prof_id = get_professor_id_by_email(db, req.email)
    if not prof_id:
        return {"info": f"Profesorul cu email-ul {req.email} nu a fost găsit."}

    if not check_subject_existence(db, prof_id, req.group_ids, req.subject, req.activity_type):
        return {"info": "Materia sau tipul de activitate nu a fost găsit în orarul profesorului sau al grupelor."}

    max_week_limit = get_max_week_for_groups(db, req.group_ids, current_semester)

    # COLLECT DATA FROM OFFICIAL SCHEDULE
    prof_tags = [f"p{prof_id}"]
    group_tags = [f"g{gid}" for gid in req.group_ids]
    room_tags = [f"s{rid}" for rid in req.room_ids]
    all_tags = prof_tags + group_tags + room_tags

    query_schedule = db.query(Schedule).filter(Schedule.id_url.in_(all_tags))

    if req.day is not None:
        query_schedule = query_schedule.filter(Schedule.week_day == req.day)
    
    schedule_data = query_schedule.all()

    # COLLECT AD-HOC RESERVATIONS
    query_reservations = db.query(Reservation).filter(Reservation.status == "reserved")

    if req.day is not None:
        query_reservations = query_reservations.filter(Reservation.day_of_week == req.day)

    all_reservations = query_reservations.all()

    # FORMATTING FOR SOLVER
    prof_blocks = [format_row(r) for r in schedule_data if r.id_url in prof_tags]
    group_blocks = [format_row(r) for r in schedule_data if r.id_url in group_tags]
    room_blocks = [format_row(r) for r in schedule_data if r.id_url in room_tags]

    for res in all_reservations:
        if res.professor_id == prof_id:
            prof_blocks.append(format_reservation_to_schedule(res, f"p{prof_id}"))
        
        if res.room_id in req.room_ids:
            room_blocks.append(format_reservation_to_schedule(res, f"s{res.room_id}"))
        
        res_group_ids = [g.id for g in res.subgroups]
        for gid in req.group_ids:
            if gid in res_group_ids:
                group_blocks.append(format_reservation_to_schedule(res, f"g{gid}"))
                break

    # Filter ROOMS by Capacity
    if req.number_of_people:
        valid_rooms = db.query(Room.id).filter(
            Room.id.in_(req.room_ids),
            (Room.capacity >= req.number_of_people) | (Room.capacity == 0)
        ).all()
        
        valid_room_ids = [r[0] for r in valid_rooms]
        
        if not valid_room_ids:
            return {"error": f"Nicio sală selectată nu are capacitatea minimă de {req.number_of_people} locuri."}
        
        room_blocks = [b for b in room_blocks if int(b['idURL'][1:]) in valid_room_ids]

    return {
        "professor": prof_blocks,
        "subgroups": group_blocks,
        "rooms": room_blocks,
        "max_week_limit": max_week_limit
    }

def find_free_slots_cp_sat(db: Session, constraints: dict, room_ids: List[int], duration_minutes: int, target_day: int, active_weeks: List[int]):
    START_DAY, END_DAY = 8 * 60, 21 * 60
    free_schedule = {w: {d: [] for d in range(1, 7)} for w in active_weeks}
    
    solver_cache = {}

    for week in active_weeks:
        days_to_check = [target_day] if target_day is not None else range(1, 7)
        
        for day in days_to_check:
            # 1. Create a signature for cache
            current_blocks_raw = []
            for category in ['professor', 'subgroups', 'rooms']:
                for c in constraints[category]:
                    if c['weekDay'] == day:
                        weeks_allowed = parse_weeks_from_info(c['otherInfo'], c['parity'])
                        if week in weeks_allowed:
                            current_blocks_raw.append(f"{c['idURL']}_{c['startHour']}_{c['duration']}")
            
            current_blocks_raw.sort()
            signature = hashlib.md5(f"{day}_{''.join(current_blocks_raw)}_{room_ids}".encode()).hexdigest()

            if signature in solver_cache:
                free_schedule[week][day] = solver_cache[signature]
                continue

            # 2. Run Solver
            day_results = []
            for rid in room_ids:
                model = cp_model.CpModel()
                start_var = model.NewIntVar(START_DAY, END_DAY - duration_minutes, 'start')
                end_var = model.NewIntVar(START_DAY + duration_minutes, END_DAY, 'end')
                model.Add(end_var == start_var + duration_minutes)

                block_list = []
                for category in ['professor', 'subgroups', 'rooms']:
                    for c in constraints[category]:
                        if c['weekDay'] == day:
                            if category == 'rooms' and c['idURL'] != f"s{rid}":
                                continue
                            weeks_allowed = parse_weeks_from_info(c['otherInfo'], c['parity'])
                            if week in weeks_allowed:
                                block_list.append(c)

                # Non-Overlap constraints
                for block in block_list:
                    b_start = int(block['startHour'])
                    b_end = b_start + int(block['duration'])
                    o1, o2 = model.NewBoolVar('o1'), model.NewBoolVar('o2')
                    model.Add(end_var <= b_start).OnlyEnforceIf(o1)
                    model.Add(start_var >= b_end).OnlyEnforceIf(o2)
                    model.AddBoolOr([o1, o2])

                solver = cp_model.CpSolver()
                current_search_start = START_DAY
                while current_search_start <= (END_DAY - duration_minutes):
                    model.Add(start_var >= current_search_start)
                    status = solver.Solve(model)
                    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                        f_start, f_end = solver.Value(start_var), solver.Value(end_var)
                        day_results.append({
                            "start": f_start,
                            "end": f_end,
                            "room_id": rid
                        })
                        current_search_start = f_start + 60
                    else: break

            solver_cache[signature] = day_results
            free_schedule[week][day] = day_results

    return free_schedule

def group_slots_for_ui(db: Session, free_slots_raw: dict, current_semester: int):
    """
    Transforms solver output into UI structure.
    """
    day_map = {1: "Luni", 2: "Marți", 3: "Miercuri", 4: "Joi", 5: "Vineri", 6: "Sâmbătă"}
    grouped = {}
    
    now = get_now()
    today_date = now.date()

    for week, days in free_slots_raw.items():
        week_data = []
        for day_idx, slots in days.items():
            if not slots:
                continue

            date_str = get_calendar_date(db, week, day_idx, current_semester)
            
            try:
                slot_date = datetime.strptime(date_str, "%d.%m.%Y").date()
                if slot_date <= today_date:
                    continue
            except (ValueError, TypeError):
                continue

            day_slots = []
            for s in slots:
                day_slots.append({
                    "room_id": s['room_id'],
                    "start_time": s['start'] // 60, 
                    "end_time": s['end'] // 60,   
                })
            
            if day_slots:
                week_data.append({
                    "day_index": day_idx,
                    "day_name": day_map.get(day_idx),
                    "date": slot_date.strftime("%Y-%m-%d"),
                    "options": day_slots
                })
        
        if week_data:
            grouped[week] = week_data
            
    return grouped

if __name__ == "__main__":
    from app.db.session import SessionLocal
    from app.schemas.user import FreeSlotRequest
    import time

    # 1. Simulate the Request object
    test_req = FreeSlotRequest(
        email="adina@eed.usv.ro",
        subject="Criptografie şi securitate informaţională",
        group_ids=[49, 50, 51],
        room_ids=[66, 24, 30],
        duration=2,  # 2 hours
        activity_type="Curs",
        number_of_people=0,
        day=2,   
        weeks=[9]
    )

    # 2. Open DB session
    db_session = SessionLocal()
    
    try:
        print(f"--- 🚀 Starting CP-SAT Test ---")
        start_time = time.time()

        # 1. Determine active weeks using calendar logic
        current_semester, active_weeks, current_status, _ = get_future_weeks_logic(db_session)
        print(f"📅 Status: {current_status} | Semester: {current_semester}")
        print(f"🗓️ Remaining course weeks: {active_weeks}")

        # 2. Extract structured data
        data_result = get_schedule_and_reservation_data(db_session, test_req, current_semester)
        
        if "error" in data_result or "info" in data_result:
            print(f"❌ Message: {data_result.get('error') or data_result.get('info')}")
        else:
            # Calculate the limit ONLY if data was extracted successfully
            max_w = data_result.get("max_week_limit", 14)
            target_weeks = test_req.weeks if test_req.weeks else active_weeks
            
            filtered_active_weeks = [
                w for w in target_weeks 
                if w <= max_w and w in active_weeks
            ]
            
            if not filtered_active_weeks:
                print(f"⚠️ None of the selected weeks ({test_req.weeks}) are academically valid or in the future.")
            else:
                print(f"✅ Data extracted. Calculating for: {filtered_active_weeks}")

                duration_min = test_req.duration * 60 if test_req.duration else 120
                
                # Run the solver ONLY on the filtered weeks
                free_slots_report = find_free_slots_cp_sat(
                    db=db_session, 
                    constraints=data_result, 
                    room_ids=test_req.room_ids, 
                    duration_minutes=duration_min,
                    target_day=test_req.day,
                    active_weeks=filtered_active_weeks 
                ) 
                
                ui_report = group_slots_for_ui(db_session, free_slots_report, current_semester)

                if not ui_report:
                    print("📭 No free slots found.")
                else:
                    for week, days_list in ui_report.items():
                        print(f"\n--- 📦 WEEK CARD {week} ---")
                        for day_info in days_list:
                            print(f"  📍 {day_info['day_name']} ({day_info['date']}):")
                            for opt in day_info['options']:
                                print(f"    🏢 Room ID: {opt['room_id']} | 🕒 Interval: {opt['start_time']}:00 - {opt['end_time']}:00")

        print(f"\n⏱️ Execution time: {time.time()-start_time:.2f}s")
    finally:
        db_session.close()