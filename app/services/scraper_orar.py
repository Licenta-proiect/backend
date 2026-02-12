# app\services\scraper_orar.py
import random
import httpx
import asyncio
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.models import Orar, Profesor, Sala, Subgrupa, Facultate

# Configurația URL-urilor de bază pentru cele 3 tipuri de entități
BASE_URLS = {
    "grupa": "https://orar.usv.ro/orar/vizualizare//orar-grupe.php?mod=grupa&ID={id}&json",
    "prof": "https://orar.usv.ro/orar/vizualizare/data/orarSPG.php?mod=prof&ID={id}&json",
    "sala": "https://orar.usv.ro/orar/vizualizare/data/orarSPG.php?mod=sala&ID={id}&json"
}

# Seturi globale (sau pasate) pentru a colecta ID-urile detectate în timpul scraping-ului
profesori_detectati = set()
sali_detectate = set()

async def fetch_json(client, url):
    """
    Efectuează o cerere GET asincronă către serverul USV.
    Include un timeout generos de 20s deoarece serverul de orar poate fi lent.
    """
    try:
        response = await client.get(url, timeout=20.0)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"⚠️ Eroare la {url}: {e}")
    return None

def clean_val(val):
    """Utilitar pentru a converti șirurile goale în None (NULL în baza de date)."""    
    if val is None: return None
    cleaned = str(val).strip()
    return cleaned if cleaned != "" else None

async def process_and_save(db: Session, data, source_tag):
    """
    Procesează răspunsul JSON (lista de evenimente și mapping-ul de grupe)
    și salvează datele în PostgreSQL.
    """
    if not data or not isinstance(data, list) or len(data) < 2:
        return

    evenimente = data[0] # Lista principală de ore de curs/lab
    mapping_grupe = data[1] # Dicționarul care leagă ID-ul evenimentului de numele grupei

    for ev in evenimente:
        ev_id = int(ev["id"])
        if ev_id == 0: continue

        # --- COLECTARE ID-URI PENTRU FAZA URMĂTOARE ---
        t_id = ev.get("teacherID")
        r_id = ev.get("roomId")
        if t_id and t_id != "0": profesori_detectati.add(int(t_id))
        if r_id and r_id != "0": sali_detectate.add(int(r_id))

        # Determinăm numele grupei folosind mapping-ul de la finalul JSON-ului
        # Aceasta transformă ID-ul intern în text lizibil (ex: "3132a")
        lista_info = mapping_grupe.get(str(ev_id), ["Nespecificat"])
        nume_grupa = "; ".join(lista_info)

        # Actualizăm titlurile academice dacă profesorul există
        if t_id and t_id != "0":
            prof = db.query(Profesor).filter(Profesor.id == int(t_id)).first()
            if prof:
                prof.positionShortName = clean_val(ev.get("positionShortName"))
                prof.phdShortName = clean_val(ev.get("phdShortName"))
                prof.otherTitle = clean_val(ev.get("otherTitle"))

        # Folosim db.merge pentru a gestiona cheia compusă (id, idURL).
        # Dacă combinația ID curs + Sursă există, se face update; altfel, insert.
        db.merge(Orar(
            id=ev_id,
            idURL=source_tag, # ex: "g49", "p13", "s24"
            typeShortName=clean_val(ev.get("typeShortName")),
            teacherID=int(ev["teacherID"]) if ev.get("teacherID") and ev["teacherID"] != "0" else None,
            roomId=int(ev["roomId"]) if ev.get("roomId") and ev["roomId"] != "0" else None,
            topicLongName=clean_val(ev.get("topicLongName")),
            topicShortName=clean_val(ev.get("topicShortName")),
            weekDay=int(ev.get("weekDay", 0)),
            startHour=clean_val(ev.get("startHour")),
            duration=int(ev.get("duration", 0)),
            parity=1 if ev.get("parity") == "i" else (2 if ev.get("parity") == "p" else 0),
            otherInfo=clean_val(ev.get("otherInfo")),
            typeLongName=clean_val(ev.get("typeLongName")),
            isDidactic=int(ev.get("isDidactic", 1)),
            grupa=nume_grupa
        ))

async def populate():
    """
    Funcția principală de control care parcurge secvențial:
    1. Grupele FIESC, 2. Toți Profesorii, 3. Toate Sălile.
    """
    db: Session = SessionLocal()

    fac_fiesc = db.query(Facultate).filter(Facultate.shortName == "FIESC").first()
    if not fac_fiesc:
        print("❌ Eroare: Nu am găsit facultatea FIESC în DB. Rulează mai întâi scraper.py!")
        return
    
    ID_FACULTATE_FIESC = fac_fiesc.id

    # 1. PASUL 1: Descarcăm doar GRUPELE FIESC
    # subgrupe = db.query(Subgrupa).filter(Subgrupa.faculty_id == ID_FACULTATE_FIESC).limit(1).all()
    subgrupe = db.query(Subgrupa).filter(Subgrupa.id.in_([49, 50, 51, 2333, 2433, 2434])).all()

    # 2. PASUL 2: Profesorii de la FIESC (baza inițială)
    prof_initiali = db.query(Profesor).filter(
        Profesor.faculty_id == ID_FACULTATE_FIESC
    ).limit(1).all()

    print(f"🚀 Pornim importul...")

    async with httpx.AsyncClient() as client:
        # Definirea fazelor pentru loop
        phases = [
            ("grupa", subgrupe),
            ("prof", []), # Se va popula dinamic mai jos
            ("sala", [])  # Se va popula dinamic mai jos
        ]

        for tag, entities in phases:
            # Re-evaluăm entitățile pentru fazele 2 și 3 pentru a include ID-urile noi detectate
            if tag == "prof":
                for p in prof_initiali: profesori_detectati.add(p.id)
                entities = db.query(Profesor).filter(
                    Profesor.id.in_(list(profesori_detectati))
                ).all()
            
            if tag == "sala":
                entities = db.query(Sala).filter(
                    Sala.id.in_(list(sali_detectate))
                ).all()

            if not entities: continue

            print(f"📂 --- Faza: {tag.upper()} ({len(entities)} entități) ---")
            
            for idx, entity in enumerate(entities):
                source_tag = f"{tag[0]}{entity.id}"
                url = BASE_URLS[tag].format(id=entity.id)
                
                print(f"⏳ [{idx+1}/{len(entities)}] Descarc {source_tag}...")
                data = await fetch_json(client, url)
                
                if data:
                    await process_and_save(db, data, source_tag)
                    
                    # --- ACTUALIZARE HAS_SCHEDULE ---
                    entity.has_schedule = True 
                    
                    db.commit()
                
                await asyncio.sleep(random.uniform(2.0, 2.5))

    print("\n✅ Baza de date a fost completată cu succes!")
    db.close()

if __name__ == "__main__":
    asyncio.run(populate())