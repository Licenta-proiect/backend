# app\services\reservation.py
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.models.models import Reservation, Room, Subgroup, Professor, Schedule
from app.schemas.user import AdminEventConfirmationRequest, SlotReservationRequest, ReservationCancellationRequest
from app.services.admin_search import groups_from_specialization
from app.services.free_slot import check_subject_existence
from app.utils.time_helper import get_now

def create_slot_reservation(db: Session, req: SlotReservationRequest):
    """
    Creates a reservation in the database after checking for conflicts.
    Includes validation against the official schedule and existing ad-hoc reservations.
    """
    try:
        # TIME CHECK (Prevent past reservations)
        now = get_now()
        today_date = now.date()

        # Current time converted to minutes from start of day for comparison
        current_time_minutes = now.hour * 60 + now.minute
        start_time_minutes = req.start_hour * 60

        # Check if date is in the past
        if req.reservation_date < today_date:
            return {"error": "Nu se pot face rezervări pentru zile care au trecut."}
        
        # Check if it's today but the start time has already passed
        if req.reservation_date == today_date and start_time_minutes < current_time_minutes:
            return {"error": "Nu se pot face rezervări pentru un interval orar care a început deja."}

        # Identify the professor (using email from request)
        professor = db.query(Professor).filter(Professor.email_address == req.email).first()
        if not professor:
            return {"error": "Profesorul nu a fost găsit în baza de date."}

        # Validate subject existence using the helper from slot_liber.py
        if not check_subject_existence(db, professor.id, req.group_ids, req.subject, req.activity_type):
            return {"error": "Materia sau tipul de activitate nu a fost găsit în orarul profesorului sau al grupelor."}

        # Final Subject Name Logic (Merged Course)
        final_subject_name = req.subject
        type_lower = req.activity_type.lower()
        
        if "curs" in type_lower:
            # Find professor "Anchors" (schedule slots matching the selected subject)
            prof_anchors = db.query(Schedule).filter(
                Schedule.id_url == f"p{professor.id}",
                Schedule.teacher_id == professor.id,
                func.lower(Schedule.topic_long_name) == func.lower(req.subject),
                func.lower(Schedule.type_long_name) == type_lower
            ).all()

            if prof_anchors:
                all_names = set()
                # For each anchor, check which subjects the selected groups have in those slots
                for anchor in prof_anchors:
                    slot_subjects = db.query(Schedule.topic_long_name).filter(
                        Schedule.id_url.in_([f"g{gid}" for gid in req.group_ids]),
                        Schedule.teacher_id == professor.id,
                        Schedule.week_day == anchor.week_day,
                        Schedule.start_hour == anchor.start_hour,
                        Schedule.duration == anchor.duration,
                        Schedule.room_id == anchor.room_id,
                        func.lower(Schedule.type_long_name) == type_lower
                    ).all()
                    
                    for s in slot_subjects:
                        if s[0]: all_names.add(s[0])
                
                # If multiple subjects are found (even with different names), join them
                if all_names:
                    final_subject_name = " / ".join(sorted(list(all_names)))

        # CONFLICT CHECK (Room, Professor, Groups)
        start_minutes = req.start_hour * 60 
        duration_minutes = req.duration * 60
        end_minutes = start_minutes + duration_minutes

        # Query for any existing reservation that overlaps with the requested interval
        conflict_query = db.query(Reservation).filter(
            Reservation.day_of_week == req.day,
            Reservation.week_number == req.week,
            func.lower(Reservation.status) == "reserved",
            Reservation.start_time_minutes < end_minutes,
            (Reservation.start_time_minutes + Reservation.duration) > start_minutes
        )

        # Apply entity filters: Room OR Professor OR Any of the Groups
        conflict = conflict_query.filter(
            or_(
                Reservation.room_id == req.room_id,
                Reservation.professor_id == professor.id,
                Reservation.subgroups.any(Subgroup.id.in_(req.group_ids))
            )
        ).first()

        if conflict:
            if conflict.room_id == req.room_id:
                msg = "Sala este deja ocupată în acest interval."
            elif conflict.professor_id == professor.id:
                msg = "Aveți deja o altă rezervare în acest interval."
            else:
                msg = "Una dintre grupele selectate are deja o rezervare în acest interval."
            return {"error": msg}
        
        # Identify subgroups
        subgroups_obj = db.query(Subgroup).filter(Subgroup.id.in_(req.group_ids)).all()
        if len(subgroups_obj) != len(req.group_ids):
            return {"error": "Una sau mai multe subgrupe selectate sunt invalide."}
        
        # Create Reservation object
        new_reservation = Reservation(
            professor_id=professor.id,
            room_id=req.room_id,
            subject=final_subject_name,
            type=req.activity_type,
            start_time_minutes=start_minutes,
            duration=duration_minutes,
            day_of_week=req.day,
            week_number=req.week,
            calendar_date=req.reservation_date,
            required_capacity=req.number_of_people,
            status="reserved",
            subgroups=subgroups_obj
        )

        db.add(new_reservation)
        db.commit()
        return {"success": "Rezervarea a fost confirmată cu succes."}
    
    except Exception as e:
        db.rollback()
        return {"error": f"Eroare la salvare: {str(e)}"}
    
def cancel_reservation(db: Session, req: ReservationCancellationRequest):
    """
    Cancels a valid reservation. Cannot cancel past reservations or same-day reservations.
    """
    reservation = db.query(Reservation).filter(Reservation.id == req.reservation_id).first()
    
    if not reservation:
        return {"error": "Rezervarea nu a fost găsită."}
    
    if reservation.status.lower() != "reserved":
        return {"error": f"Această rezervare este anulată deja."}

    now = get_now()
    today_date = now.date()

    # 1. Check if reservation is in the past
    if reservation.calendar_date < today_date:
        return {"error": "Nu se pot anula rezervări din zilele trecute."}
    
    # 2. Check if reservation is today
    if reservation.calendar_date == today_date:
        return {"error": "Anularea unei rezervări nu se poate face în aceeași zi cu evenimentul."}

    # Verify if reservation belongs to the professor
    professor = db.query(Professor).filter(Professor.email_address == req.email).first()
    if not professor or reservation.professor_id != professor.id:
        return {"error": "Nu aveți dreptul să anulați această rezervare."}

    try:
        reservation.status = "cancelled"
        reservation.cancellation_reason = req.reason
        db.commit()
        return {"success": "Rezervarea a fost anulată cu succes."}
    except Exception as e:
        db.rollback()
        return {"error": f"Eroare la anulare: {str(e)}"}

def create_admin_event_reservation(db: Session, req: AdminEventConfirmationRequest):
    """
    Creates an admin event reservation with full conflict validation.
    """
    try:
        # 1. TIME CHECK (Prevent past reservations)
        now = get_now()
        if req.reservation_date < now.date():
            return {"error": "Nu se pot face rezervări pentru zile care au trecut."}

        start_minutes = req.start_hour * 60
        duration_minutes = req.duration * 60
        end_minutes = start_minutes + duration_minutes

        if req.reservation_date == now.date() and start_minutes < (now.hour * 60 + now.minute):
            return {"error": "Nu se pot face rezervări pentru un interval orar care a început deja."}

        # 2. RESOLVE SUBGROUPS (Convert "C;1" to objects)
        all_subgroup_ids = groups_from_specialization(db, req.subgroup_ids)
        subgroups_objects = db.query(Subgroup).filter(Subgroup.id.in_(all_subgroup_ids)).all()

        # 3. CONFLICT CHECK (Hybrid logic: Room, Multiple Professors, Multiple Subgroups)
        # Query for existing overlapping reservations
        conflict = db.query(Reservation).filter(
            Reservation.calendar_date == req.reservation_date,
            func.lower(Reservation.status) == "reserved",
            Reservation.start_time_minutes < end_minutes,
            (Reservation.start_time_minutes + Reservation.duration) > start_minutes
        ).filter(
            or_(
                # Room overlap
                Reservation.room_id == req.room_id,
                # Any of the participating professors (as main OR additional)
                Reservation.professor_id.in_(req.professor_ids),
                Reservation.additional_professors.any(Professor.id.in_(req.professor_ids)),
                # Any of the subgroups
                Reservation.subgroups.any(Subgroup.id.in_(all_subgroup_ids))
            )
        ).first()

        if conflict:
            if conflict.room_id == req.room_id:
                msg = f"Sala este deja ocupată"
            else:
                msg = f"Conflict detectat cu rezervarea existentă: {conflict.subject}"
            return {"error": msg}

        # 4. CAPACITY CHECK (Optional but recommended)
        room_obj = db.query(Room).filter(Room.id == req.room_id).first()
        if room_obj and req.number_of_people > room_obj.capacity:
            return {"error": f"Capacitatea sălii ({room_obj.capacity}) este mai mică decât numărul de persoane ({req.number_of_people})."}

        # 5. CREATE RESERVATION
        new_reservation = Reservation(
            room_id=req.room_id,
            subject=req.subject,
            type=req.activity_type,
            start_time_minutes=start_minutes,
            duration=duration_minutes,
            day_of_week=req.reservation_date.isoweekday(),
            week_number=None,
            calendar_date=req.reservation_date,
            required_capacity=req.number_of_people,
            status="reserved",
            subgroups=subgroups_objects
        )

        # Add participating professors to the junction table
        if req.professor_ids:
            professors_obj = db.query(Professor).filter(Professor.id.in_(req.professor_ids)).all()
            new_reservation.additional_professors = professors_obj

        db.add(new_reservation)
        db.commit()
        db.refresh(new_reservation)
        
        return {
            "status": "success", 
            "reservation_id": new_reservation.id,
            "message": "Evenimentul a fost programat și verificat cu succes."
        }

    except Exception as e:
        db.rollback()
        return {"error": f"Internal Server Error: {str(e)}"}

def get_teacher_reservations(db: Session, email: str):
    """
    Retrieves all reservations for a professor and calculates status (reserved/cancelled/completed).
    """
    professor = db.query(Professor).filter(Professor.email_address == email).first()
    if not professor:
        return []

    reservations = db.query(Reservation).filter(Reservation.professor_id == professor.id).all()
    
    now = get_now()
    today_date = now.date()
    current_time_minutes = now.hour * 60 + now.minute

    result = []
    for r in reservations:
        status_final = r.status 

        # Dynamic status logic
        if r.status.lower() == "reserved":
            if r.calendar_date < today_date:
                status_final = "completed"
            elif r.calendar_date == today_date:
                end_minutes = r.start_time_minutes + r.duration
                if current_time_minutes > end_minutes:
                    status_final = "completed"

        group_names = [f"{g.specialization_short_name} an {g.study_year} {g.group_name}{g.subgroup_index}" for g in r.subgroups]

        result.append({
            "id": r.id,
            "subject": r.subject,
            "type": r.type,
            "room": r.room.name if r.room else "N/A",
            "groups": group_names,
            "week": r.week_number,
            "day": r.day_of_week,
            "date": r.calendar_date,
            "start_hour": r.start_time_minutes // 60,
            "duration": r.duration // 60,
            "status": status_final,
            "cancellation_reason": r.cancellation_reason if r.status == "cancelled" else None
        })
    
    return sorted(result, key=lambda x: x['date'], reverse=True)

def get_all_reservations_admin(db: Session):
    """
    Returns all reservations in the system for the admin panel.
    """
    reservations = db.query(Reservation).all()
    
    now = get_now()
    today_date = now.date()
    current_time_minutes = now.hour * 60 + now.minute

    result = []
    for r in reservations:
        status_final = r.status 

        if r.status.lower() == "reserved":
            if r.calendar_date < today_date:
                status_final = "completed"
            elif r.calendar_date == today_date:
                end_minutes = r.start_time_minutes + r.duration
                if current_time_minutes > end_minutes:
                    status_final = "completed"

        group_names = [f"{g.specialization_short_name} an {g.study_year} {g.group_name}{g.subgroup_index}" for g in r.subgroups]

        prof_name = "N/A"
        prof_email = "N/A"
        
        if r.main_professor:
            name_parts = [
                r.main_professor.position_short_name,
                r.main_professor.phd_short_name, 
                r.main_professor.last_name,
                r.main_professor.first_name
            ]

            prof_name = " ".join(part for part in name_parts if part)
            prof_email = r.main_professor.email_address
            
        result.append({
            "id": r.id,
            "professor": prof_name,
            "professor_email": prof_email,
            "subject": r.subject,
            "type": r.type,
            "room": r.room.name if r.room else "N/A",
            "groups": group_names,
            "date": r.calendar_date,
            "start_hour": r.start_time_minutes // 60,
            "duration": r.duration // 60,
            "status": status_final,
            "cancellation_reason": r.cancellation_reason if r.status == "cancelled" else None,
            "week_number": r.week_number
        })
    
    return sorted(result, key=lambda x: x['date'], reverse=True)

def get_reservations_by_subgroups(db: Session):
    """
    Returns all reservations grouped by subgroup ID.
    """
    reservations = db.query(Reservation).join(Reservation.subgroups).all()
    
    now = get_now()
    today_date = now.date()
    current_time_minutes = now.hour * 60 + now.minute

    grouped_reservations = {}

    for r in reservations:
        status_final = r.status 
        if r.status.lower() == "reserved":
            if r.calendar_date < today_date:
                status_final = "completed"
            elif r.calendar_date == today_date:
                end_minutes = r.start_time_minutes + r.duration
                if current_time_minutes > end_minutes:
                    status_final = "completed"

        name_parts = [
                r.main_professor.position_short_name,
                r.main_professor.phd_short_name, 
                r.main_professor.last_name,
                r.main_professor.first_name
            ]

        prof_name = " ".join(part for part in name_parts if part)
        group_names_display = [f"{g.specialization_short_name} an {g.study_year} {g.group_name}{g.subgroup_index}" for g in r.subgroups]

        reservation_data = {
            "id": r.id,
            "professor": prof_name,
            "professor_email": r.main_professor.email_address if r.main_professor else "N/A",
            "subject": r.subject,
            "type": r.type,
            "room": r.room.name if r.room else "N/A",
            "participating_groups": group_names_display,
            "date": r.calendar_date.isoformat(),
            "start_hour": r.start_time_minutes // 60,
            "duration": r.duration // 60,
            "status": status_final,
            "cancellation_reason": r.cancellation_reason if r.status == "cancelled" else None
        }

        for g in r.subgroups:
            if g.id not in grouped_reservations:
                grouped_reservations[g.id] = []
            grouped_reservations[g.id].append(reservation_data)

    for gid in grouped_reservations:
        grouped_reservations[gid].sort(key=lambda x: x['date'], reverse=True)

    return grouped_reservations

if __name__ == "__main__":
    from app.db.session import SessionLocal
    from app.schemas.user import SlotReservationRequest
    from datetime import date

    # 1. Initialize session
    db = SessionLocal()

    try:
        print(f"--- 🧪 Starting Reservation Logic Tests ---")

        # TEST DATA (Adjusted based on solver output or desired data)
        test_email = "adina@eed.usv.ro"
        
        # Simulate a reservation request for Room C203 (ID 24) 
        # Tuesday (Day 2), Week 9, 18:00
        reservation_data = SlotReservationRequest(
            email=test_email,
            room_id=24,
            group_ids=[49, 50, 51],
            subject="Criptografie şi securitate informaţională",
            activity_type="Curs",
            day=2,
            week=9,
            start_hour=18,
            duration=2,
            reservation_date=date(2026, 4, 28), # Date from solver output
            number_of_people=50
        )

        # TEST 1: Create New Reservation
        print(f"\n[Test 1] Attempting to create a valid reservation...")
        result1 = create_slot_reservation(db, reservation_data)
        
        if "success" in result1:
            print(f"✅ Success: {result1['success']}")
        else:
            print(f"❌ Error: {result1['error']}")

        # TEST 2: Duplicate Attempt (Room/Professor Conflict)
        print(f"\n[Test 2] Attempting to create the same reservation (should trigger CONFLICT)...")
        result2 = create_slot_reservation(db, reservation_data)
        
        if "error" in result2:
            print(f"✅ Conflict Test Passed: System blocked overlap. Message: {result2['error']}")
        else:
            print(f"❌ Error: System allowed overlap! (BAD)")

        # TEST 3: Group Conflict (Different professor, same groups)
        print(f"\n[Test 3] Checking group conflict (different professor, same time/groups)...")
        # Change only the professor (email) and room, but keep groups and time
        reservation_busy_group = reservation_data.model_copy(update={
            "email": "alt.profesor@unitbv.ro", 
            "room_id": 25 # Different room
        })
        
        result3 = create_slot_reservation(db, reservation_busy_group)
        if "error" in result3:
            print(f"✅ Group Conflict Test Passed: {result3['error']}")
        else:
            print(f"❌ Error: Group was allowed to be in two places at once!")

    except Exception as e:
        print(f"💥 Unexpected error during testing: {e}")
    finally:
        # Optional: Delete test data to avoid polluting the DB
        # db.query(Reservation).filter(Reservation.subject == "Criptografie şi securitate informaţională").delete()
        # db.commit()
        db.close()
        print(f"\n--- 🏁 Tests Finished ---")