# app\services\admin_search.py
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import Schedule, Subgroup, Professor, Room, Reservation, AcademicCalendar
from app.schemas.user import AdminEventRequest
from typing import List, Dict, Any
from ortools.sat.python import cp_model
from .future_weeks import get_future_weeks_logic
from .alternative_slot import format_row
from .alternative_slot import parse_weeks_from_info

def get_academic_context(db: Session, target_date: date):
    """
    Checks if a specific date falls within a lecture week (1-14).
    Returns (semester, week_number) if found, otherwise (None, None).
    """
    # Search in AcademicCalendar for an entry where the date is within the period
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
    Collects constraints from Schedule (only if in semester) and Reservations.
    """
    semester, week_no = get_academic_context(db, req.reservation_date)
    is_during_semester = semester is not None
    day_idx = req.reservation_date.isoweekday() # 1=Mon, 7=Sun

    # 1. Identify Subgroups from "Spec-Year" strings
    subgroup_ids = []
    for item in req.specialization_years:
        try:
            spec, year = item.split("-")
            groups = db.query(Subgroup).filter(
                Subgroup.specialization_short_name == spec,
                Subgroup.study_year == int(year)
            ).all()
            subgroup_ids.extend([g.id for g in groups])
        except ValueError: continue

    # 2. Build Tags
    prof_tags = [f"p{pid}" for pid in req.professor_ids]
    group_tags = [f"g{gid}" for gid in subgroup_ids]
    room_tags = [f"s{rid}" for rid in req.room_ids]
    
    prof_blocks = []
    group_blocks = []
    room_blocks = []

    # 3. LOAD FROM SCHEDULE (Only if date is within a semester week)
    if is_during_semester:
        all_tags = prof_tags + group_tags + room_tags
        schedule_data = db.query(Schedule).filter(
            Schedule.id_url.in_(all_tags),
            Schedule.week_day == day_idx
        ).all()
        
        # We only keep schedule blocks that apply to this specific week (parity/other_info)
        # Using a logic similar to parse_weeks_from_info internally
        for r in schedule_data:
            weeks_allowed = parse_weeks_from_info(r.other_info, r.parity)
            if week_no in weeks_allowed:
                row = format_row(r)
                if r.id_url in prof_tags: prof_blocks.append(row)
                elif r.id_url in group_tags: group_blocks.append(row)
                elif r.id_url in room_tags: room_blocks.append(row)

    # 4. LOAD FROM RESERVATIONS (Always, regardless of semester)
    # Filter by date and status
    reservations = db.query(Reservation).filter(
        Reservation.calendar_date == req.reservation_date,
        Reservation.status == "reserved"
    ).all()

    for res in reservations:
        # Check Room overlaps
        if res.room_id in req.room_ids:
            room_blocks.append({
                "idURL": f"s{res.room_id}",
                "startHour": res.start_time_minutes,
                "duration": res.duration,
                "weekDay": day_idx
            })
        
        # Check Professor overlaps
        if res.professor_id in req.professor_ids:
            prof_blocks.append({"idURL": f"p{res.professor_id}", "startHour": res.start_time_minutes, "duration": res.duration, "weekDay": day_idx})
        
        # Check Subgroup overlaps
        res_group_ids = [g.id for g in res.subgroups]
        for gid in subgroup_ids:
            if gid in res_group_ids:
                group_blocks.append({"idURL": f"g{gid}", "startHour": res.start_time_minutes, "duration": res.duration, "weekDay": day_idx})
                break

    return {
        "professor": prof_blocks,
        "subgroups": group_blocks,
        "rooms": room_blocks,
        "is_semester": is_during_semester
    }

def find_admin_free_slots(db: Session, req: AdminEventRequest):
    """
    Solver entry point for Admin search.
    """
    constraints = get_admin_constraints(db, req)
    
    # Standard solver parameters
    START_DAY, END_DAY = 8 * 60, 21 * 60
    duration_min = req.duration * 60
    day_idx = req.reservation_date.isoweekday()
    
    results = []
    
    for rid in req.room_ids:
        # Filter rooms by capacity if provided
        room_obj = db.query(Room).filter(Room.id == rid).first()
        if req.number_of_people > 0 and room_obj and room_obj.capacity < req.number_of_people:
            continue

        model = cp_model.CpModel()
        start_var = model.NewIntVar(START_DAY, END_DAY - duration_min, 'start')
        end_var = model.NewIntVar(START_DAY + duration_min, END_DAY, 'end')
        model.Add(end_var == start_var + duration_min)

        # Merge all constraints for this specific room
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
                    "room_name": room_obj.name if room_obj else f"Sala {rid}",
                    "start_time": f_start // 60,
                    "end_time": (f_start + duration_min) // 60,
                    "date": req.reservation_date.strftime("%Y-%m-%d")
                })
                current_search_start = f_start + 60 # Step of 1 hour
            else:
                break
                
    return results