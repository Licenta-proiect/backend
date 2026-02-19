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
    """
    Procesează răspunsul JSON. Sare peste orarele goale de tip [[{}], {}]
    sau orare care nu conțin evenimente valide.
    """
    # 1. Verificare de bază a structurii [[...], {...}]
    if not data or not isinstance(data, list) or len(data) < 2:
        print(f"⚠️ Date JSON invalide sau incomplete pentru {source_tag}")
        return

    evenimente = data[0]
    mapping_grupe = data[1]

    # 2. Verificăm dacă lista de evenimente este goală sau conține doar un obiect gol/invalid
    if not evenimente or not isinstance(evenimente, list):
        print(f"ℹ️ Orar gol (fără evenimente) pentru {source_tag}")
        return

    # Verificăm dacă primul element este un obiect valid (evităm [[{}], {}])
    # Un orar valid trebuie să aibă cel puțin un obiect cu un 'id' diferit de None/0
    valid_events = [ev for ev in evenimente if isinstance(ev, dict) and ev.get("id") and int(ev.get("id")) != 0]
    
    if not valid_events:
        print(f"ℹ️ Sărit {source_tag}: Nu s-au găsit ore valide (posibil orar gol [[{{}}], {{}}])")
        return

    # 3. Procesăm doar evenimentele validate
    for ev in valid_events:
        try:
            ev_id = int(ev["id"])
            
            # Extragere ID-uri cu fallback
            t_id_str = ev.get("teacherID", "0")
            r_id_str = ev.get("roomId", "0")
            
            t_id = int(t_id_str) if t_id_str and t_id_str != "0" else None
            r_id = int(r_id_str) if r_id_str and r_id_str != "0" else None

            # Mapping grupă
            lista_info = mapping_grupe.get(str(ev_id), ["Nespecificat"]) if isinstance(mapping_grupe, dict) else ["Nespecificat"]
            nume_grupa = "; ".join(lista_info)

            # Update date profesor (dacă există în DB-ul local)
            if t_id:
                prof = db.query(Profesor).filter(Profesor.id == t_id).first()
                if prof:
                    prof.positionShortName = clean_val(ev.get("positionShortName"))
                    prof.phdShortName = clean_val(ev.get("phdShortName"))
                    prof.otherTitle = clean_val(ev.get("otherTitle"))

            # Merge în tabela Orar
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
            print(f"❌ Eroare la procesarea unui eveniment din {source_tag}: {str(e)}")
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

    subgrupe = db.query(Subgrupa).filter(
        Subgrupa.isModular == 0,
        Subgrupa.faculty_id == ID_FACULTATE_FIESC
    ).all()

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