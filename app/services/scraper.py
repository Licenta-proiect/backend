# app\services\scraper.py
import httpx
import asyncio
import bleach
import html
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.models import Facultate, Profesor, Sala, Subgrupa, User, UserRole

# URL-urile oficiale USV furnizate de tine
URLS = {
    "facultati": "https://orar.usv.ro/orar/vizualizare/data/facultati.php?json",
    "cadre": "https://orar.usv.ro/orar/vizualizare/data/cadre.php?json",
    "sali": "https://orar.usv.ro/orar/vizualizare/data/sali.php?json",
    "subgrupe": "https://orar.usv.ro/orar/vizualizare/data/subgrupe.php?json"
}

async def fetch_data(url):
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30.0)
        return response.json()

def clean_val(val):
    """
    Decodează entitățile HTML, elimină tag-urile HTML (XSS) 
    și transformă string-urile goale în None pentru DB.
    """
    if val is None: 
        return None
    
    # 1. Transformă în string
    cleaned = str(val)
    
    # 2. Decodează entitățile HTML (ex: &icirc; -> î, &amp; -> &)
    cleaned = html.unescape(cleaned)
    
    # 3. Elimină spațiile de la început și final
    cleaned = cleaned.strip()
    
    if cleaned == "": 
        return None
    
    # 4. Elimină orice tag-uri HTML (Protectie XSS / Sanitizare)
    # Tags=[] și strip=True elimină tot ce e între < >, nu doar tag-ul
    cleaned = bleach.clean(cleaned, tags=[], strip=True)
    
    # 5. O ultimă verificare în cazul în care bleach a lăsat un string gol
    cleaned = cleaned.strip()
    return cleaned if cleaned != "" else None

async def populate():
    db: Session = SessionLocal()
    try:
        # 1. FACULTĂȚI
        print("📥 Descărcăm facultăți...")
        facultati_json = await fetch_data(URLS["facultati"])
        for f in facultati_json:
            if f["id"] == "0": continue
            db.merge(Facultate(
                id=int(f["id"]),
                shortName=clean_val(f["shortName"]),
                longName=clean_val(f["longName"])
            ))
        db.commit() # Commit pentru a avea ID-urile disponibile pentru maparea profesorilor

        # Creăm un dicționar pentru mapare: { "Nume Lung Facultate": ID }
        fac_map = {clean_val(f.longName): f.id for f in db.query(Facultate).all()}

        # 2. SĂLI
        print("📥 Descărcăm săli...")
        sali_json = await fetch_data(URLS["sali"])
        for s in sali_json:
            if s["id"] == "0": continue
            db.merge(Sala(
                id=int(s["id"]),
                name=clean_val(s["name"]),
                shortName=clean_val(s["shortName"]),
                buildingName=clean_val(s["buildingName"]),
                capacitate=int(s["capacitate"] or 0),
                computers=int(s["computers"] or 0)
            ))

        # 3. PROFESORI
        print("📥 Descărcăm cadre didactice...")
        cadre_json = await fetch_data(URLS["cadre"])
        for p in cadre_json:
            p_id = int(p["id"])
            if p_id == 0: continue

            f_id = fac_map.get(clean_val(p.get("facultyName")))
            
            # Verificăm dacă profesorul există deja pentru a-i actualiza câmpurile
            profesor_existent = db.query(Profesor).filter(Profesor.id == p_id).first()
            
            new_email = clean_val(p["emailAddress"])

            if profesor_existent:
                profesor_existent.lastName = clean_val(p["lastName"])
                profesor_existent.firstName = clean_val(p["firstName"])
                
                # Doar dacă email-ul din orar este diferit de cel din DB, facem set-ul care declanșează sync-ul
                if profesor_existent.emailAddress != new_email:
                    profesor_existent.emailAddress = new_email
                    
                profesor_existent.faculty_id = f_id
                profesor_existent.departmentName = clean_val(p["departmentName"])
            else:
                # Dacă nu există, îl creăm
                db.add(Profesor(
                    id=p_id,
                    lastName=clean_val(p["lastName"]),
                    firstName=clean_val(p["firstName"]),       
                    emailAddress=new_email,
                    faculty_id=f_id,
                    departmentName=clean_val(p["departmentName"])
                ))

        # --- 4. SUBGRUPE cu protecție la Foreign Key ---
        print("📥 Descărcăm subgrupe...")
        subgrupe_json = await fetch_data(URLS["subgrupe"])
        
        # Luăm toate ID-urile de facultăți valide care există deja în DB
        # sau pe care tocmai le-am importat mai sus. 
        # Cea mai sigură metodă e să filtrăm facultyId != 0
        
        for sg in subgrupe_json:
            # Sărim peste ID-ul 0 al subgrupei SAU dacă facultyId este 0
            if sg["id"] == "0" or sg["facultyId"] == "0" or sg["facultyId"] == 0: 
                continue
                
            db.merge(Subgrupa(
                id=int(sg["id"]),
                type=clean_val(sg["type"]),
                faculty_id=int(sg["facultyId"]),
                specializationShortName=clean_val(sg["specializationShortName"]),
                studyYear=int(sg["studyYear"]),
                groupName=clean_val(sg["groupName"]),
                subgroupIndex=clean_val(sg["subgroupIndex"]),
                isModular=int(sg["isModular"])
            ))

       # --- 5. ADMIN (Gestiune inteligentă administrator) ---
        print("👤 Verificăm contul de administrator...")
        admin_email = "stoicamaria180@gmail.com"

        # Căutăm dacă admin-ul există deja după email
        existing_admin = db.query(User).filter(User.email == admin_email).first()

        if existing_admin:
            # Dacă există, îi actualizăm doar datele (opțional)
            existing_admin.lastName = "Stoica"
            existing_admin.firstName = "Maria Alexandra"
            existing_admin.role = UserRole.ADMIN.value
            print("✅ Cont administrator actualizat.")
        else:
            # Dacă nu există, îl creăm de la zero
            admin_user = User(
                lastName="Stoica", 
                firstName="Maria Alexandra", 
                email=admin_email,
                role=UserRole.ADMIN.value 
            )
            db.add(admin_user)
            print("✅ Cont administrator creat.")

        db.commit()

        # --- RESETARE SECVENȚĂ ID ---
        # Această comandă forțează PostgreSQL să seteze următorul ID 
        # la valoarea MAX(id) + 1, evitând conflictele la insert-uri viitoare.
        db.execute(text("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users))"))
        db.commit()

        print("✅ Populare finalizată cu succes!")

    except Exception as e:
        print(f"❌ Eroare: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(populate())