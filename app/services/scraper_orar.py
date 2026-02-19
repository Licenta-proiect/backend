# app\services\scraper_orar.py
import random
import httpx
import asyncio
from app.services.scraper import clean_val
from sqlalchemy import or_, select, distinct
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.models import Orar, Profesor, Sala, Subgrupa, Facultate

# Configurația URL-urilor de bază pentru cele 3 tipuri de entități
BASE_URLS = {
    "grupa": "https://orar.usv.ro/orar/vizualizare//orar-grupe.php?mod=grupa&ID={id}&json",
    "prof": "https://orar.usv.ro/orar/vizualizare/data/orarSPG.php?mod=prof&ID={id}&json",
    "sala": "https://orar.usv.ro/orar/vizualizare/data/orarSPG.php?mod=sala&ID={id}&json"
}

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

async def process_and_save(db: Session, data, source_tag):
    if not data or not isinstance(data, list) or len(data) < 2:
        print(f"⚠️ Date JSON invalide sau mesaje de eroare primite pentru {source_tag}")
        return

    evenimente = data[0]
    mapping_grupe = data[1]

    for ev in evenimente:
        # VERIFICARE: Dacă serverul USV trimite un string în loc de obiect (se întâmplă la erori)
        if not isinstance(ev, dict):
            print(f"❌ Element invalid în {source_tag}: Se aștepta dicționar, s-a primit {type(ev)}. Conținut: {ev}")
            continue

        try:
            # Aici apărea eroarea KeyError: 'id'
            if "id" not in ev:
                print(f"❌ Cheia 'id' lipsește din evenimentul sursei {source_tag}. Chei disponibile: {list(ev.keys())}")
                continue

            ev_id = int(ev["id"])
            if ev_id == 0: continue

            t_id = int(ev["teacherID"]) if ev.get("teacherID") and ev["teacherID"] != "0" else None
            r_id = int(ev["roomId"]) if ev.get("roomId") and ev["roomId"] != "0" else None

            lista_info = mapping_grupe.get(str(ev_id), ["Nespecificat"])
            nume_grupa = "; ".join(lista_info)

            if t_id:
                prof = db.query(Profesor).filter(Profesor.id == t_id).first()
                if prof:
                    prof.positionShortName = clean_val(ev.get("positionShortName"))
                    prof.phdShortName = clean_val(ev.get("phdShortName"))
                    prof.otherTitle = clean_val(ev.get("otherTitle"))

            db.merge(Orar(
                id=ev_id,
                idURL=source_tag,
                typeShortName=clean_val(ev.get("typeShortName")),
                teacherID=t_id,
                roomId=r_id,
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
        except Exception as e:
            print(f"❌ Eroare neașteptată la procesarea orarului {source_tag}: {str(e)}")
            continue

async def populate():
    """
    Funcția principală de control care parcurge secvențial:
    Descărcarea orarului doar pentru grupele selectate. (FIESC)
    Extragerea ID-urilor unice de profesori din orarul grupelor și descărcarea orarului lor.
    Extragerea ID-urilor unice de săli din orarul deja descărcat (grupe + profesori) și descărcarea orarului lor.
    """
    db: Session = SessionLocal()
    
    fac_fiesc = db.query(Facultate).filter(Facultate.shortName == "FIESC").first()
    if not fac_fiesc:
        print("❌ Eroare: Nu am găsit facultatea FIESC în DB. Rulează mai întâi scraper.py!")
        return
    
    ID_FACULTATE_FIESC = fac_fiesc.id

    # 1. DEFINIRE GRUPE INITIALE
    #grupe_tinta = [49, 50, 51, 2333, 2433, 2434]
    #subgrupe = db.query(Subgrupa).filter(Subgrupa.id.in_(grupe_tinta)).all()

    subgrupe = db.query(Subgrupa).filter(Subgrupa.faculty_id == ID_FACULTATE_FIESC).all()

    print(f"🚀 Pornim importul controlat...")

    async with httpx.AsyncClient() as client:
        # --- FAZA 1: DOAR GRUPELE ---
        print(f"📂 --- Faza 1: GRUPE ({len(subgrupe)} entități) ---")
        for entity in subgrupe:
            source_tag = f"g{entity.id}"
            url = BASE_URLS["grupa"].format(id=entity.id)
            data = await fetch_json(client, url)
            if data:
                await process_and_save(db, data, source_tag)
                entity.has_schedule = True
                db.commit()
            await asyncio.sleep(random.uniform(6.0, 7.0))

        # --- FAZA 2: PROFESORII UNICI DIN ORARUL GRUPELOR ---
        # Luăm profesorii care apar în orele grupelor descărcate anterior
        prof_ids_query = db.query(distinct(Orar.teacherID)).filter(
            Orar.idURL.like('g%'),
            Orar.teacherID.isnot(None)
        ).all()
        prof_ids = [row[0] for row in prof_ids_query]
        profesor_entities = db.query(Profesor).filter(Profesor.id.in_(prof_ids)).all()

        print(f"📂 --- Faza 2: PROFESORI DETECTAȚI ({len(profesor_entities)} entități) ---")
        for entity in profesor_entities:
            source_tag = f"p{entity.id}"
            url = BASE_URLS["prof"].format(id=entity.id)
            data = await fetch_json(client, url)
            if data:
                await process_and_save(db, data, source_tag)
                entity.has_schedule = True
                db.commit()
            await asyncio.sleep(random.uniform(6.0, 7.0))

        # --- FAZA 3: SĂLILE UNICE DIN TOT ORARUL (GRUPE + PROFESORI) ---
        sali_ids_query = db.query(distinct(Orar.roomId)).filter(
            Orar.roomId.isnot(None)
        ).all()
        sali_ids = [row[0] for row in sali_ids_query]
        sali_entities = db.query(Sala).filter(Sala.id.in_(sali_ids)).all()

        print(f"📂 --- Faza 3: SĂLI DETECTATE ({len(sali_entities)} entități) ---")
        for entity in sali_entities:
            source_tag = f"s{entity.id}"
            url = BASE_URLS["sala"].format(id=entity.id)
            data = await fetch_json(client, url)
            if data:
                await process_and_save(db, data, source_tag)
                entity.has_schedule = True
                db.commit()
            await asyncio.sleep(random.uniform(6.0, 7.0))

    print("\n✅ Baza de date a fost completată cu succes!")
    db.close()

if __name__ == "__main__":
    asyncio.run(populate())