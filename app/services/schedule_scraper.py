# app\services\schedule_scraper.py
import random
import httpx
import asyncio
from app.services.scraper import clean_val
from sqlalchemy import distinct, text
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.models import Schedule, Professor, Room, Subgroup, Faculty

# Base URL configuration for the 3 types of entities
BASE_URLS = {
    "group": "https://orar.usv.ro/orar/vizualizare//orar-grupe.php?mod=grupa&ID={id}&json",
    "prof": "https://orar.usv.ro/orar/vizualizare/data/orarSPG.php?mod=prof&ID={id}&json",
    "room": "https://orar.usv.ro/orar/vizualizare/data/orarSPG.php?mod=sala&ID={id}&json"
}

async def fetch_json(client, url):
    """
    Performs an asynchronous GET request to the USV server.
    Includes a generous 20s timeout because the schedule server can be slow.
    """
    try:
        response = await client.get(url, timeout=20.0)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error at {url}: {e}")
    return None

async def process_and_save(db: Session, data, source_tag):
    """
    Processes the JSON response. Skips empty schedules of type [[{}], {}]
    or schedules that do not contain valid events.
    """
    # 1. Basic structure check [[...], {...}]
    if not data or not isinstance(data, list) or len(data) < 2:
        print(f"Invalid or incomplete JSON data for {source_tag}")
        return

    events = data[0]
    group_mapping = data[1]

    # 2. Check if the events list is empty or contains only an empty/invalid object
    if not events or not isinstance(events, list):
        print(f"ℹEmpty schedule (no events) for {source_tag}")
        return

    # Check if the first element is a valid object (avoiding [[{}], {}])
    # A valid schedule must have at least one object with an 'id' other than None/0
    valid_events = [ev for ev in events if isinstance(ev, dict) and ev.get("id") and int(ev.get("id")) != 0]
    
    if not valid_events:
        print(f"Skipped {source_tag}: No valid hours found (possible empty schedule [[{{}}], {{}}])")
        return

    # 3. Process only validated events
    for ev in valid_events:
        try:
            ev_id = int(ev["id"])
            
            # Extract IDs with fallback
            t_id_str = ev.get("teacherID", "0")
            r_id_str = ev.get("roomId", "0")
            
            t_id = int(t_id_str) if t_id_str and t_id_str != "0" else None
            r_id = int(r_id_str) if r_id_str and r_id_str != "0" else None

            # Group mapping
            info_list = group_mapping.get(str(ev_id), ["Unspecified"]) if isinstance(group_mapping, dict) else ["Unspecified"]
            group_name = "; ".join(info_list)

            # Update professor data (if exists in local DB)
            if t_id:
                prof = db.query(Professor).filter(Professor.id == t_id).first()
                if prof:
                    prof.position_short_name = clean_val(ev.get("positionShortName"))
                    prof.phd_short_name = clean_val(ev.get("phdShortName"))
                    prof.other_title = clean_val(ev.get("otherTitle"))

            # Merge into Schedule table
            db.merge(Schedule(
                id=ev_id,
                id_url=source_tag,
                type_short_name=clean_val(ev.get("typeShortName")),
                teacher_id=t_id,
                room_id=r_id,
                topic_long_name=clean_val(ev.get("topicLongName")),
                topic_short_name=clean_val(ev.get("topicShortName")),
                week_day=int(ev.get("weekDay", 0)),
                start_hour=clean_val(ev.get("startHour")),
                duration=int(ev.get("duration", 0)),
                parity=1 if ev.get("parity") == "i" else (2 if ev.get("parity") == "p" else 0),
                other_info=clean_val(ev.get("otherInfo")),
                type_long_name=clean_val(ev.get("typeLongName")),
                is_didactic=int(ev.get("isDidactic", 1)),
                group_info=group_name
            ))
        except Exception as e:
            print(f"Error processing an event from {source_tag}: {str(e)}")
            continue

async def populate():
    """
    Main control function that iterates sequentially:
    1. Downloads schedule only for selected groups (FIESC).
    2. Extracts unique professor IDs from the group schedules and downloads their schedules.
    3. Extracts unique room IDs from the already downloaded schedules (groups + professors) and downloads their schedules.
    """
    db: Session = SessionLocal()

    try:
        db.execute(text("DELETE FROM schedule"))
        db.commit()
        print("Old data from 'schedule' has been deleted.")
    except Exception as e:
        db.rollback()
        print(f"Attention: Could not wipe schedule: {e}")

    fiesc_faculty = db.query(Faculty).filter(Faculty.short_name == "FIESC").first()
    if not fiesc_faculty:
        print("Error: FIESC faculty not found in DB!")
        return
    
    FIESC_FACULTY_ID = fiesc_faculty.id

    subgroups = db.query(Subgroup).filter(
        Subgroup.is_modular == 0,
        Subgroup.faculty_id == FIESC_FACULTY_ID
    ).all()

    total_groups = len(subgroups)
    print(f"Starting controlled import for {total_groups} groups...")

    async with httpx.AsyncClient() as client:
        # --- PHASE 1: GROUPS ONLY ---
        print(f"--- Phase 1: GROUPS ({total_groups} entities) ---")
        for idx, entity in enumerate(subgroups, 1):
            source_tag = f"g{entity.id}"
            url = BASE_URLS["group"].format(id=entity.id)
            
            print(f"[{idx}/{total_groups}] Downloading group schedule: {source_tag}")
            data = await fetch_json(client, url)
            if data:
                await process_and_save(db, data, source_tag)
                entity.has_schedule = True
                db.commit()
            await asyncio.sleep(random.uniform(6.0, 7.0))

        # --- PHASE 2: UNIQUE PROFESSORS ---
        prof_ids_query = db.query(distinct(Schedule.teacher_id)).filter(
            Schedule.id_url.like('g%'),
            Schedule.teacher_id.isnot(None)
        ).all()
        prof_ids = [row[0] for row in prof_ids_query]
        professor_entities = db.query(Professor).filter(Professor.id.in_(prof_ids)).all()
        
        total_profs = len(professor_entities)
        print(f"--- Phase 2: DETECTED PROFESSORS ({total_profs} entities) ---")
        for idx, entity in enumerate(professor_entities, 1):
            source_tag = f"p{entity.id}"
            url = BASE_URLS["prof"].format(id=entity.id)
            
            print(f"[{idx}/{total_profs}] Downloading professor schedule: {source_tag}")
            data = await fetch_json(client, url)
            if data:
                await process_and_save(db, data, source_tag)
                entity.has_schedule = True
                db.commit()
            await asyncio.sleep(random.uniform(6.0, 7.0))

        # --- PHASE 3: UNIQUE ROOMS ---
        room_ids_query = db.query(distinct(Schedule.room_id)).filter(
            Schedule.room_id.isnot(None)
        ).all()
        room_ids = [row[0] for row in room_ids_query]
        room_entities = db.query(Room).filter(Room.id.in_(room_ids)).all()

        total_rooms = len(room_entities)
        print(f"--- Phase 3: DETECTED ROOMS ({total_rooms} entities) ---")
        for idx, entity in enumerate(room_entities, 1):
            source_tag = f"s{entity.id}"
            url = BASE_URLS["room"].format(id=entity.id)
            
            print(f"⏳ [{idx}/{total_rooms}] Downloading room schedule: {source_tag}")
            data = await fetch_json(client, url)
            if data:
                await process_and_save(db, data, source_tag)
                entity.has_schedule = True
                db.commit()
            await asyncio.sleep(random.uniform(6.0, 7.0))

    print("\nDatabase has been successfully populated!")
    db.close()

if __name__ == "__main__":
    asyncio.run(populate())