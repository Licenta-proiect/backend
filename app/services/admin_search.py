# app\services\admin_search.py
from datetime import datetime, date, timedelta
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

def get_admin_constraints_for_day(db: Session, req: AdminEventRequest, target_date: date):
    """
    Collects constraints from Schedule (if in semester) and Reservations.
    Takes into account both main professors and additional professors in junction tables.
    """
    semester, week_no = get_academic_context(db, target_date)
    is_during_semester = semester is not None
    day_idx = target_date.isoweekday()

    # 1. Map Specialization-Year strings to Subgroup IDs (FIXED: use extend)
    parsed_items = []
    spec_names = []

    for item in req.specialization_years:
        try:
            spec, year = item.split(";")
            spec = spec.strip()
            parsed_items.append((spec.lower(), int(year)))
            spec_names.append(spec.lower())
        except (ValueError, IndexError):
            continue

    all_subgroup_ids = []
    if parsed_items:
        candidate_groups = db.query(Subgroup.id, Subgroup.specialization_short_name, Subgroup.study_year).filter(
            func.lower(Subgroup.specialization_short_name).in_(spec_names)
        ).all()
        
        for g_id, g_spec, g_year in candidate_groups:
            if (g_spec.lower(), g_year) in parsed_items:
                all_subgroup_ids.append(g_id)

    prof_tags = [f"p{pid}" for pid in req.professor_ids]
    group_tags = [f"g{gid}" for gid in all_subgroup_ids]
    room_tags = [f"s{rid}" for rid in req.room_ids]
    
    prof_blocks, group_blocks, room_blocks = [], [], []

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
        Reservation.calendar_date == target_date,
        Reservation.status == "reserved"
    ).all()

    for res in reservations:
        # A. Check Room overlaps
        if res.room_id in req.room_ids:
            room_blocks.append(format_reservation_to_schedule(res, f"s{res.room_id}"))
        
        # B. Check Professor overlaps
        # Check if any professor we are interested in is either the owner OR an additional participant
        additional_prof_ids = [p.id for p in res.additional_professors]
        for pid in req.professor_ids:
            if res.professor_id == pid or pid in additional_prof_ids:
                prof_blocks.append(format_reservation_to_schedule(res, f"p{pid}"))
        
        # C. Check Subgroup overlaps
        res_subgroup_ids = [sg.id for sg in res.subgroups]
        for gid in all_subgroup_ids:
            if gid in res_subgroup_ids:
                group_blocks.append(format_reservation_to_schedule(res, f"g{gid}"))
                break # Avoid duplicate blocks for the same group in one reservation

    return {
        "professor": prof_blocks,
        "subgroups": group_blocks,
        "rooms": room_blocks
    }

def find_admin_free_slots(db: Session, req: AdminEventRequest):
    """
    Main entry point. Iterates through each day in the range [start_date, end_date].
    Returns a list of days, each containing a list of free slots.
    """
    now = get_now()
    today = now.date()

    delta = req.end_date - req.start_date
    days_to_check = [req.start_date + timedelta(days=i) for i in range(delta.days + 1) 
                     if (req.start_date + timedelta(days=i)) > today]

    rooms_data = db.query(Room).filter(Room.id.in_(req.room_ids)).all()
    rooms_dict = {r.id: r for r in rooms_data}

    final_report = []
    START_DAY, END_DAY = 8 * 60, 21 * 60
    duration_min = req.duration * 60

    for target_date in days_to_check:
        constraints = get_admin_constraints_for_day(db, req, target_date)
        day_options = []

        for rid in req.room_ids:
            room_obj = rooms_dict.get(rid)
            if req.number_of_people > 0 and room_obj and room_obj.capacity < req.number_of_people:
                continue

            current_search_start = START_DAY
            
            while current_search_start <= (END_DAY - duration_min):
                model = cp_model.CpModel()
                
                start_var = model.NewIntVar(current_search_start, END_DAY - duration_min, 'start')
                end_var = model.NewIntVar(current_search_start + duration_min, END_DAY, 'end')
                model.Add(end_var == start_var + duration_min)

                relevant_blocks = constraints['professor'] + constraints['subgroups'] + \
                                  [b for b in constraints['rooms'] if b['idURL'] == f"s{rid}"]

                for block in relevant_blocks:
                    b_start = int(block['startHour'])
                    b_end = b_start + int(block['duration'])
                    
                    o1, o2 = model.NewBoolVar('o1'), model.NewBoolVar('o2')
                    model.Add(end_var <= b_start).OnlyEnforceIf(o1)
                    model.Add(start_var >= b_end).OnlyEnforceIf(o2)
                    model.AddBoolOr([o1, o2])

                model.Minimize(start_var)

                solver = cp_model.CpSolver()
                status = solver.Solve(model)

                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    f_start = solver.Value(start_var)
                    day_options.append({
                        "room_id": rid,
                        "room_name": room_obj.name,
                        "start_time": f_start // 60,
                        "end_time": (f_start + duration_min) // 60
                    })
                    current_search_start = f_start + 60 
                else:
                    break

        if day_options:
            day_options.sort(key=lambda x: (x['start_time']))
            final_report.append({
                "date": target_date.strftime("%Y-%m-%d"),
                "options": day_options
            })

    return final_report

if __name__ == "__main__":
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        req = AdminEventRequest(
            subject="Test Admin Event",
            room_ids=[66], 
            specialization_years=["C;1"], 
            professor_ids=[68], 
            start_date=date(2026, 6, 1), 
            end_date=date(2026, 6, 3),
            duration=2,
            number_of_people=20,
            activity_type="event"
        )

        print(f"🚀 Testing Admin Range Search: {req.start_date} to {req.end_date}")
        results = find_admin_free_slots(db, req)

        if results == []:
            print("nimic")

        for day in results:
            print(f"\n📅({day['date']}):")
            for slot in day['options']:
                print(f"   📍 Room: {slot['room_name']} | {slot['start_time']}:00 - {slot['end_time']}:00")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()