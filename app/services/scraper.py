# app\services\scraper.py
import httpx
import asyncio
import bleach
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
    """Transformă string-urile goale sau cu spații în None pentru DB."""
    if val is None: 
        return None
    # 1. Transformă în string și elimină spațiile
    cleaned = str(val).strip()
    if cleaned == "": 
        return None
    
    # 2. Elimină orice tag-uri HTML (Protectie XSS)
    # Acesta va transforma "<b>Nume</b>" în "Nume" sau va elimina <script>
    cleaned = bleach.clean(cleaned, tags=[], strip=True)
    
    return cleaned

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
            if p["id"] == "0": continue

            # Găsim faculty_id folosind numele facultății din JSON și maparea noastră
            f_id = fac_map.get(clean_val(p.get("facultyName")))

            db.merge(Profesor(
                id=int(p["id"]),
                lastName=clean_val(p["lastName"]),
                firstName=clean_val(p["firstName"]),       
                emailAddress=clean_val(p["emailAddress"]),
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

        # --- 5. ADMIN (Adăugare manuală administrator) ---
        print("👤 Creăm contul de administrator...")
        admin_user = User(
            lastName="Stoica", 
            firstName="Maria Alexandra", 
            email="stoicamaria180@gmail.com",
            role=UserRole.ADMIN.value 
        )

        # Folosim merge pentru a nu da eroare dacă admin-ul există deja
        db.merge(admin_user)
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