# app\services\admin_search.py
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import Schedule, Subgroup, Room, Reservation, AcademicCalendar
from app.schemas.user import AdminEventRequest
from ortools.sat.python import cp_model
from .alternative_slot import format_row, parse_weeks_from_info
from .free_slot import format_reservation_to_schedule
from app.utils.time_helper import get_now

def get_academic_context(db: Session, target_date: date):
    """
    Checks if a specific date falls within a lecture week (1-14).
    """
    all_cal = db.query(AcademicCalendar).filter(AcademicCalendar.week_number <= 14).all()
    
    for entry in all_cal:
        segments = entry.period.split(';')
        for seg in segments:
            parts = seg.split('-')
            if len(parts) != 2: continue
            start_dt = datetime.strptime(parts[0].strip(), "%Y.%m.%d").date()
            end_dt = datetime.strptime(parts[1].strip(), "%Y.%m.%d").date()
            
            if start_dt <= target_date <= end_dt:
                return entry.semester, entry.week_number
                
    return None, None

def get_admin_constraints(db: Session, req: AdminEventRequest):
    """
    Collects constraints from Schedule (if in semester) and Reservations.
    Uses format_reservation_to_schedule for data normalization.
    """
    semester, week_no = get_academic_context(db, req.reservation_date)
    is_during_semester = semester is not None
    day_idx = req.reservation_date.isoweekday()

    # 1. Map Specialization-Year strings to Subgroup IDs (FIXED: use extend)
    all_subgroup_ids = []
    for item in req.specialization_years:
        try:
            # Consistent with frontend SPEC-YEAR
            spec, year = item.split(";")
            groups = db.query(Subgroup.id).filter(
                func.lower(Subgroup.specialization_short_name) == func.lower(spec),
                Subgroup.study_year == int(year)
            ).all()
            all_subgroup_ids.extend([g[0] for g in groups])
        except ValueError: continue

    prof_tags = [f"p{pid}" for pid in req.professor_ids]
    group_tags = [f"g{gid}" for gid in all_subgroup_ids]
    room_tags = [f"s{rid}" for rid in req.room_ids]
    
    prof_blocks = []
    group_blocks = []
    room_blocks = []

    # 2. LOAD FROM SCHEDULE
    if is_during_semester:
        all_tags = prof_tags + group_tags + room_tags
        schedule_data = db.query(Schedule).filter(
            Schedule.id_url.in_(all_tags),
            Schedule.week_day == day_idx
        ).all()
        
        for r in schedule_data:
            weeks_allowed = parse_weeks_from_info(r.other_info, r.parity)
            if week_no in weeks_allowed:
                row = format_row(r)
                if r.id_url in prof_tags: prof_blocks.append(row)
                elif r.id_url in group_tags: group_blocks.append(row)
                elif r.id_url in room_tags: room_blocks.append(row)

    # 3. LOAD FROM RESERVATIONS
    reservations = db.query(Reservation).filter(
        Reservation.calendar_date == req.reservation_date,
        Reservation.status == "reserved"
    ).all()

    for res in reservations:
        if res.room_id in req.room_ids:
            room_blocks.append(format_reservation_to_schedule(res, f"s{res.room_id}"))
        
        if res.professor_id in req.professor_ids:
            prof_blocks.append(format_reservation_to_schedule(res, f"p{res.professor_id}"))
        
        res_subgroup_ids = [sg.id for sg in res.subgroups]
        for gid in all_subgroup_ids:
            if gid in res_subgroup_ids:
                group_blocks.append(format_reservation_to_schedule(res, f"g{gid}"))
                break

    return {
        "professor": prof_blocks,
        "subgroups": group_blocks,
        "rooms": room_blocks
    }

def find_admin_free_slots(db: Session, req: AdminEventRequest):
    """
    Main entry point for the Admin CP-SAT Solver.
    """
    now = get_now()
    today = now.date()
    if req.reservation_date < today:
        return []

    constraints = get_admin_constraints(db, req)
    
    START_DAY, END_DAY = 8 * 60, 21 * 60
    duration_min = req.duration * 60
    
    results = []
    
    for rid in req.room_ids:
        # Capacity check
        room_obj = db.query(Room).filter(Room.id == rid).first()
        if req.number_of_people > 0 and room_obj and room_obj.capacity < req.number_of_people:
            continue

        model = cp_model.CpModel()
        start_var = model.NewIntVar(START_DAY, END_DAY - duration_min, 'start')
        end_var = model.NewIntVar(START_DAY + duration_min, END_DAY, 'end')
        model.Add(end_var == start_var + duration_min)

        # Merge blocks: This specific room + all selected professors + all selected subgroups
        relevant_blocks = constraints['professor'] + constraints['subgroups'] + \
                          [b for b in constraints['rooms'] if b['idURL'] == f"s{rid}"]

        for block in relevant_blocks:
            b_start = int(block['startHour'])
            b_end = b_start + int(block['duration'])
            
            o1 = model.NewBoolVar('o1')
            o2 = model.NewBoolVar('o2')
            model.Add(end_var <= b_start).OnlyEnforceIf(o1)
            model.Add(start_var >= b_end).OnlyEnforceIf(o2)
            model.AddBoolOr([o1, o2])

        solver = cp_model.CpSolver()
        current_search_start = START_DAY
        
        while current_search_start <= (END_DAY - duration_min):
            model.Add(start_var >= current_search_start)
            status = solver.Solve(model)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                f_start = solver.Value(start_var)
                results.append({
                    "room_id": rid,
                    "room_name": room_obj.name,
                    "start_time": f_start // 60,
                    "end_time": (f_start + duration_min) // 60,
                    "date": req.reservation_date.strftime("%Y-%m-%d")
                })
                current_search_start = f_start + 60 # Step forward
            else:
                break
                
    return results

if __name__ == "__main__":
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        req = AdminEventRequest(
            subject="Test Admin Event",
            room_ids=[66], 
            specialization_years=["C;2"], 
            professor_ids=[68], 
            reservation_date=date(2026, 6, 3), 
            duration=2,
            number_of_people=20,
            activity_type="event"
        )

        print(f"🚀 Testing Admin Search for date: {req.reservation_date}")
        results = find_admin_free_slots(db, req)

        if not results:
            print("📭 No free slots found for the given criteria.")
        else:
            print(f"✅ Found {len(results)} potential slots:")
            for slot in results:
                print(f"   📍 Room: {slot['room_name']} | Time: {slot['start_time']}:00 - {slot['end_time']}:00")

    except Exception as e:
        print(f"❌ Error during test: {e}")
    finally:
        db.close()