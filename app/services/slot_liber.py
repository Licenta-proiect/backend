# app\services\slot_liber.py
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa, Profesor, Sala
from app.schemas.user import SlotLiberRequest
from typing import List
from .slot_alternativ import format_row, parse_weeks_from_info

def get_profesor_id(db: Session, email: str):
    '''Identifică profesorul în baza de date folosind adresa de email.'''
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    
    if not profesor:
        return None
    
    return profesor.id

def verifica_existenta_materie(db: Session, id_profesor: int, id_grupe: List[int], materie: str, tip_materie: str) -> bool:
    """
    Verifică dacă materia și tipul de activitate există în orarul profesorului 
    și al tuturor grupelor selectate.
    Nu e neapărat ca profesorul să predea la grupa respectivă, el poate selecta o grupă pentru a înlocui un alt profesor.
    
    Returnează True doar dacă fiecare entitate (profesor + fiecare grupă) 
    are cel puțin o înregistrare pentru materia respectivă.
    """
    # Construim lista de identificatori (tag-uri) folosiți în coloana idURL
    target_tags = [f"p{id_profesor}"] + [f"g{gid}" for gid in id_grupe]
    
    # Numărăm entitățile distincte din lista noastră care apar în orar cu această materie
    existent_entities_count = db.query(func.count(distinct(Orar.idURL))).filter(
        Orar.idURL.in_(target_tags),
        func.lower(Orar.topicLongName) == func.lower(materie),
        func.lower(Orar.typeLongName) == func.lower(tip_materie)
    ).scalar()
    
    # Verificăm dacă numărul de entități găsite coincide cu numărul de entități căutate
    # Acest lucru garantează că profesorul predă materia și TOATE grupele o au în program
    return existent_entities_count == len(target_tags)

def get_data(db: Session, req: SlotLiberRequest):
    '''Extrage datele din orar pentru profesor,subgrupe și săli'''
    # 1. Preia ID Profesor din email
    id_prof = get_profesor_id(db, req.email)
    if not id_prof:
        return {"info": f"Profesorul cu email-ul {req.email} nu a fost găsit."}

    # 2. Verifică existența materiei și tipului pentru toți actorii (Prof + Grupe)
    if not verifica_existenta_materie(db, id_prof, req.grupe_ids, req.materie, req.tip_activitate):
        return {"info": "Materia sau tipul de activitate nu a fost găsit în orarul profesorului sau al grupelor."}

    # 3. Construiește lista de tag-uri pentru idURL (Profesor, Grupe, Săli)
    # p + idProf, g + idGrupa, s + idSala
    target_tags = [f"p{id_prof}"] 
    target_tags += [f"g{gid}" for gid in req.grupe_ids]
    target_tags += [f"s{sid}" for sid in req.sali_ids]

    # 4. Extrage toate datele din orar care au idURL în lista construită
    query = db.query(Orar).filter(Orar.idURL.in_(target_tags))

    # 5. Filtrare după ZI (weekDay), dacă este specificată
    if req.zi is not None:
        query = query.filter(Orar.weekDay == req.zi)

    all_schedule_data = query.all()

    # 6. Filtrare SĂLI după Capacitate (dacă numar_persoane e furnizat)
    # Trebuie să verificăm în tabelul 'sali' dacă id-urile din sali_ids au capacitate >= numar_persoane
    if req.numar_persoane is not None:
        # Căutăm sălile care fie au capacitate suficientă, fie au capacitate 0 (nespecificată)
        sali_valide = db.query(Sala.id).filter(
            Sala.id.in_(req.sali_ids),
            (Sala.capacitate >= req.numar_persoane) | (Sala.capacitate == 0)
        ).all()
        
        valid_sala_ids = [s[0] for s in sali_valide]
        
        # Dacă nicio sală nu are capacitatea necesară, returnăm eroare
        if not valid_sala_ids:
            return {"error": f"Nicio sală selectată nu are capacitatea minimă de {req.numar_persoane} locuri."}
        
        # Filtrăm datele din orar pentru a păstra doar constrângerile sălilor care au trecut testul capacității
        # Nota: Datele despre Prof și Grupe rămân, filtrăm doar tag-urile de tip 's' care nu sunt în valid_sala_ids
        tags_sali_invalide = [f"s{sid}" for sid in req.sali_ids if sid not in valid_sala_ids]
        all_schedule_data = [d for d in all_schedule_data if d.idURL not in tags_sali_invalide]

    # 7. Formatăm rezultatul pentru algoritmul de identificare sloturi libere
    return {"constraints": [format_row(row) for row in all_schedule_data]}

def find_free_slots_with_rooms(db: Session, constraints: List[dict], sali_ids: List[int], duration_minutes: int = 120):
    """
    Identifică intervalele libere comune profesorului și grupelor, 
    apoi verifică care din sălile solicitate sunt disponibile în acele intervale.
    """
    START_DAY = 60 * 8
    END_DAY = 60 * 22
    
    # 1. Separăm constrângerile: Oameni (p, g) vs Săli (s)
    people_constraints = []
    room_constraints = {sid: [] for sid in sali_ids}
    
    for c in constraints:
        active_weeks = parse_weeks_from_info(c.get("otherInfo"), c.get("parity"))
        info = {
            "day": int(c["weekDay"]),
            "start": int(c["startHour"]),
            "end": int(c["startHour"]) + int(c["duration"]),
            "weeks": active_weeks
        }
        
        if c["idURL"].startswith('s'):
            # Extragem ID-ul numeric al sălii din tag-ul "s123"
            try:
                sid = int(c["idURL"][1:])
                if sid in room_constraints:
                    room_constraints[sid].append(info)
            except: continue
        else:
            people_constraints.append(info)

    # Obținem numele sălilor pentru un output frumos
    nume_sali = {s.id: s.name for s in db.query(Sala).filter(Sala.id.in_(sali_ids)).all()}

    free_schedule = {w: {d: [] for d in range(1, 7)} for w in range(1, 15)}

    for week in range(1, 15):
        for day in range(1, 7):
            # A. Găsim când sunt LIBERI oamenii (Profesor + Grupe)
            blocks_people = sorted([
                (c["start"], c["end"]) 
                for c in people_constraints 
                if c["day"] == day and week in c["weeks"]
            ])
            
            people_free_intervals = []
            curr = START_DAY
            for b_start, b_end in blocks_people:
                if b_start - curr >= duration_minutes:
                    people_free_intervals.append((curr, b_start))
                if b_end > curr: curr = b_end
            if END_DAY - curr >= duration_minutes:
                people_free_intervals.append((curr, END_DAY))

            # B. Pentru fiecare interval în care oamenii sunt liberi, verificăm SĂLILE
            for p_start, p_end in people_free_intervals:
                sali_disponibile_interval = []
                
                for sid in sali_ids:
                    # Blocajele acestei săli în această zi/săptămână
                    blocks_room = [
                        (rc["start"], rc["end"]) 
                        for rc in room_constraints[sid] 
                        if rc["day"] == day and week in rc["weeks"]
                    ]
                    
                    # O sală e liberă dacă niciun blocaj al ei nu se suprapune cu intervalul (p_start, p_end)
                    # Totuși, sala poate avea un curs la mijlocul intervalului liber al oamenilor.
                    # Vom căuta sub-intervale în care și sala e liberă.
                    
                    curr_r = p_start
                    sorted_room_blocks = sorted(blocks_room)
                    
                    for br_start, br_end in sorted_room_blocks:
                        if br_start - curr_r >= duration_minutes:
                            sali_disponibile_interval.append({
                                "id": sid,
                                "nume": nume_sali.get(sid, f"Sala {sid}"),
                                "start": curr_r,
                                "end": br_start
                            })
                        if br_end > curr_r: curr_r = br_end
                    
                    if p_end - curr_r >= duration_minutes:
                        sali_disponibile_interval.append({
                            "id": sid,
                            "nume": nume_sali.get(sid, f"Sala {sid}"),
                            "start": curr_r,
                            "end": p_end
                        })

                # Grupăm rezultatele pe intervale orare unice pentru a nu repeta
                if sali_disponibile_interval:
                    # Sortăm după start pentru consistență
                    sali_disponibile_interval.sort(key=lambda x: x['start'])
                    
                    for item in sali_disponibile_interval:
                        free_schedule[week][day].append({
                            "start": item["start"],
                            "end": item["end"],
                            "formatted": f"{item['start']//60:02d}:{item['start']%60:02d} - {item['end']//60:02d}:{item['end']%60:02d}",
                            "sala": item["nume"]
                        })

    return free_schedule

if __name__ == "__main__":
    from app.db.session import SessionLocal
    from app.schemas.user import SlotLiberRequest
    import json

    # 1. Simulăm obiectul Request
    test_req = SlotLiberRequest(
        email="stoicaalexandra180@gmail.com",
        materie="Criptografie şi securitate informaţională",
        grupe_ids=[49, 50, 51],
        sali_ids=[66, 24, 30],
        durata=2,  # 2 ore
        tip_activitate="Curs",
        numar_persoane=0,
        zi=2,   # Testăm pentru toate zilele săptămânii
        ora_start=9
    )

    # 2. Deschidem sesiunea DB
    db_session = SessionLocal()
    
    try:
        print(f"--- Testare get_data pentru: {test_req.email} ---")
        
        # 3. Apelăm funcția get_data pentru a obține constrângerile (ocupările)
        result = get_data(db_session, test_req)
        
        # 4. Interpretăm rezultatele și apelăm find_free_slots
        if "info" in result:
            print(f"ℹ️ Info: {result['info']}")
        elif "error" in result:
            print(f"❌ Eroare: {result['error']}")
        else:
            constraints = result.get("constraints", [])
            print(f"✅ Succes! S-au extras {len(constraints)} constrângeri.")

            # --- APELUL NOII FUNCȚII ---
            print("\n--- Căutare sloturi libere cu Săli ---")
            durata_min = test_req.durata * 60 if test_req.durata else 120
            
            # Pasăm și req.sali_ids pentru a le verifica disponibilitatea individual
            free_slots_report = find_free_slots_with_rooms(
                db_session, 
                constraints, 
                test_req.sali_ids, 
                duration_minutes=durata_min
            )

            found_any = False
            for week in range(1, 15):
                printed_week = False
                for day_idx in range(1, 7):
                    slots = free_slots_report[week][day_idx]
                    if slots:
                        if not printed_week:
                            print(f"\nSăptămâna {week}:")
                            printed_week = True
                        found_any = True
                        day_name = ["Luni", "Marți", "Miercuri", "Joi", "Vineri", "Sâmbătă"][day_idx-1]
                        print(f"  {day_name}:")
                        for s in slots:
                            print(f"    - {s['formatted']} -> Liberă în: {s['sala']}")
            
            if not found_any:
                print("  Nu s-au găsit sloturi libere conform criteriilor.")

    except Exception as e:
        print(f"❌ Eroare critică în timpul testului: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db_session.close()