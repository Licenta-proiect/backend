# app\services\scraper.py
import httpx
import asyncio
import bleach
import html
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.models import Faculty, Professor, Room, Subgroup, User, UserRole
from app.utils.config import settings

# Official USV URLs provided by you
URLS = {
    "faculties": "https://orar.usv.ro/orar/vizualizare/data/facultati.php?json",
    "staff": "https://orar.usv.ro/orar/vizualizare/data/cadre.php?json",
    "rooms": "https://orar.usv.ro/orar/vizualizare/data/sali.php?json",
    "subgroups": "https://orar.usv.ro/orar/vizualizare/data/subgrupe.php?json"
}
 
async def fetch_data(url):
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30.0)
        return response.json()

def clean_val(val):
    """
    Decodes HTML entities, removes HTML tags (XSS protection),
    and transforms empty strings into None for the DB.
    """
    if val is None: 
        return None
    
    # 1. Transform to string
    cleaned = str(val)
    
    # 2. Decode HTML entities (e.g., &icirc; -> î, &amp; -> &)
    cleaned = html.unescape(cleaned)
    
    # 3. Trim whitespace from start and end
    cleaned = cleaned.strip()
    
    if cleaned == "": 
        return None
    
    # 4. Remove any HTML tags (XSS Protection / Sanitization)
    # Tags=[] and strip=True removes everything between < >, not just the tags
    cleaned = bleach.clean(cleaned, tags=[], strip=True)
    
    # 5. Final check in case bleach left an empty string
    cleaned = cleaned.strip()
    return cleaned if cleaned != "" else None

async def populate():
    db: Session = SessionLocal()
    try:
        # 1. FACULTIES
        print("Downloading faculties...")
        faculties_json = await fetch_data(URLS["faculties"])
        for f in faculties_json:
            if f["id"] == "0": continue
            db.merge(Faculty(
                id=int(f["id"]),
                short_name=clean_val(f["shortName"]),
                long_name=clean_val(f["longName"])
            ))
        db.commit() # Commit so IDs are available for professor mapping

        # Create a dictionary for mapping: { "Long Faculty Name": ID }
        fac_map = {clean_val(f.long_name): f.id for f in db.query(Faculty).all()}

        # 2. ROOMS
        print("Downloading rooms...")
        rooms_json = await fetch_data(URLS["rooms"])
        for r in rooms_json:
            if r["id"] == "0": continue
            db.merge(Room(
                id=int(r["id"]),
                name=clean_val(r["name"]),
                short_name=clean_val(r["shortName"]),
                building_name=clean_val(r["buildingName"]),
                capacity=int(r["capacitate"] or 0),
                computers=int(r["computers"] or 0),
                has_schedule=False  
            ))

        # 3. PROFESSORS
        print("Downloading teaching staff...")
        staff_json = await fetch_data(URLS["staff"])
        for p in staff_json:
            p_id = int(p["id"])
            if p_id == 0: continue

            f_id = fac_map.get(clean_val(p.get("facultyName")))
            
            # Check if the professor already exists to update their fields
            existing_professor = db.query(Professor).filter(Professor.id == p_id).first()
            
            new_email = clean_val(p["emailAddress"])

            if existing_professor:
                existing_professor.last_name = clean_val(p["lastName"])
                existing_professor.first_name = clean_val(p["firstName"])
                
                # Check if the new email is valid (not null/empty)
                if new_email is not None:
                    # Check if it differs from what we already have
                    if existing_professor.email_address != new_email:
                        # Check if the professor has a user account created
                        # Search in 'users' table by the current email in 'professors' table
                        has_user_account = db.query(User).filter(User.email == existing_professor.email_address).first()
                        
                        if not has_user_account:
                            # If they DON'T have an account, we can safely update the email in the professors table
                            existing_professor.email_address = new_email
                            print(f"Updated email for professor ID {p_id}: {new_email}")
                        else:
                            # If they DO have an account, do not touch the email as it is managed by the user system
                            print(f"Ignored email update for ID {p_id} (Active account exists: {existing_professor.email_address})")
                                
                existing_professor.faculty_id = f_id
                existing_professor.department_name = clean_val(p["departmentName"])
                existing_professor.has_schedule = False
            else:
                # If they don't exist, create them
                db.add(Professor(
                    id=p_id,
                    last_name=clean_val(p["lastName"]),
                    first_name=clean_val(p["firstName"]),       
                    email_address=clean_val(new_email),
                    faculty_id=f_id,
                    department_name=clean_val(p["departmentName"]),
                    has_schedule=False
                ))

        # --- 4. SUBGROUPS with Foreign Key protection ---
        print("Downloading subgroups...")

        # Delete all existing records before population
        try:
            db.execute(text("DELETE FROM subgroups"))
            db.commit()
            print("Old data from 'subgroups' has been deleted.")
        except Exception as e:
            db.rollback()
            print(f"Attention: Could not wipe subgroups: {e}")

        subgroups_json = await fetch_data(URLS["subgroups"])
        
        # We take all valid faculty IDs that already exist in DB or were just imported above.
        # The safest method is to filter facultyId != 0
        
        for sg in subgroups_json:
            # Skip ID 0 of the subgroup OR if facultyId is 0
            if sg["id"] == "0" or sg["facultyId"] == "0" or sg["facultyId"] == 0: 
                continue
                
            db.add(Subgroup(
                id=int(sg["id"]),
                type=clean_val(sg["type"]),
                faculty_id=int(sg["facultyId"]),
                specialization_short_name=clean_val(sg["specializationShortName"]),
                study_year=int(sg["studyYear"]),
                group_name=clean_val(sg["groupName"]),
                subgroup_index=clean_val(sg["subgroupIndex"]),
                is_modular=int(sg["isModular"]),
                has_schedule=False  
            ))

        # --- 5. ADMIN (Smart administrator management) ---
        print(f"Checking administrator account: {settings.ADMIN_EMAIL}")

        existing_admin = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        
        if existing_admin:
            # If exists, update details (optional)
            existing_admin.last_name = settings.ADMIN_LAST_NAME
            existing_admin.first_name = settings.ADMIN_FIRST_NAME
            existing_admin.role = UserRole.ADMIN.value
            print("Administrator account updated.")
        else:
            # If it doesn't exist, create it from scratch
            admin_user = User(
                last_name=settings.ADMIN_LAST_NAME, 
                first_name=settings.ADMIN_FIRST_NAME, 
                email=settings.ADMIN_EMAIL,
                role=UserRole.ADMIN.value 
            )
            db.add(admin_user)
            print("Administrator account created.")

        db.commit()

        # --- RESET ID SEQUENCE ---
        # This command forces PostgreSQL to set the next ID 
        # to MAX(id) + 1, avoiding conflicts for future inserts.
        db.execute(text("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users))"))
        db.commit()

        print("Population completed successfully!")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(populate())