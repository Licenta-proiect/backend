# app\services\slot_liber.py
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa, Profesor, Sala
from app.schemas.user import SlotLiberRequest
from typing import List
import hashlib
from ortools.sat.python import cp_model

from app.services.future_weeks import get_future_weeks_logic
from .slot_alternativ import format_row, parse_weeks_from_info

def get_profesor_id(db: Session, email: str):
    '''Identifică profesorul în baza de date folosind adresa de email.'''
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    
    if not profesor:
        return None
    
    return profesor.id

def get_max_week_for_groups(db: Session, id_grupe: List[int]) -> int:
    """
    Determină săptămâna maximă (10 sau 14) verificând dacă grupele sunt în an terminal.
    Un an este terminal dacă studyYear este egal cu maximul studyYear pentru acea specializare.
    """
    # 1. Luăm specializările și anii de studiu pentru grupele noastre
    grupe = db.query(Subgrupa).filter(Subgrupa.id.in_(id_grupe)).all()
    
    if not grupe:
        return 14

    is_terminal = False
    for g in grupe:
        # 2. Căutăm care este anul maxim pentru specializarea acestei grupe
        max_year = db.query(func.max(Subgrupa.studyYear)).filter(
            Subgrupa.specializationShortName == g.specializationShortName,
            Subgrupa.faculty_id == g.faculty_id
        ).scalar()
        
        # 3. Dacă grupa curentă este în anul maxim, e an terminal
        if g.studyYear == max_year:
            is_terminal = True
            break # E suficient ca o grupă să fie terminală pentru a limita căutarea
            
    return 10 if is_terminal else 14

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
    # Preia ID Profesor din email
    id_prof = get_profesor_id(db, req.email)
    if not id_prof:
        return {"info": f"Profesorul cu email-ul {req.email} nu a fost găsit."}

    # Verifică existența materiei și tipului pentru toți actorii (Prof + Grupe)
    if not verifica_existenta_materie(db, id_prof, req.grupe_ids, req.materie, req.tip_activitate):
        return {"info": "Materia sau tipul de activitate nu a fost găsit în orarul profesorului sau al grupelor."}

    # Determinăm săptămâna maximă pe baza anului de studiu
    max_week_limit = get_max_week_for_groups(db, req.grupe_ids)

    # Extragem toate datele relevante într-un singur query pentru eficiență
    tags_prof = [f"p{id_prof}"]
    tags_grupe = [f"g{gid}" for gid in req.grupe_ids]
    tags_sali = [f"s{sid}" for sid in req.sali_ids]
    all_tags = tags_prof + tags_grupe + tags_sali

    # Extrage toate datele din orar care au idURL în lista construită
    query = db.query(Orar).filter(Orar.idURL.in_(all_tags))

    # Filtrare după ZI (weekDay), dacă este specificată
    if req.zi is not None:
        query = query.filter(Orar.weekDay == req.zi)

    all_schedule_data = query.all()

    # Filtrare SĂLI după Capacitate (dacă numar_persoane e furnizat)
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

    return {
        "profesor": [format_row(r) for r in all_schedule_data if r.idURL in tags_prof],
        "subgrupe": [format_row(r) for r in all_schedule_data if r.idURL in tags_grupe],
        "sali": [format_row(r) for r in all_schedule_data if r.idURL in tags_sali],
        "max_week_limit": max_week_limit
    }

def find_free_slots_cp_sat(db: Session, constraints: dict, sali_ids: List[int], duration_minutes: int, target_day: int, active_weeks: List[int]):
    START_DAY, END_DAY = 8 * 60, 21 * 60
    free_schedule = {w: {d: [] for d in range(1, 7)} for w in active_weeks}
    nume_sali = {s.id: s.name for s in db.query(Sala).filter(Sala.id.in_(sali_ids)).all()}
    
    # Cache pentru a nu rula solverul pentru configuratii identice de blocaje
    # { "semnatura_blocaje": { day: [slots] } }
    solver_cache = {}

    for week in active_weeks:
        zile = [target_day] if target_day is not None else range(1, 7)
        
        for day in zile:
            # 1. Cream o "semnatura" a blocajelor pentru aceasta saptamana si zi
            # Luam toate ID-urile si orele blocajelor care pica in aceasta saptamana
            current_blocks_raw = []
            for cat in ['profesor', 'subgrupe', 'sali']:
                for c in constraints[cat]:
                    if c['weekDay'] == day:
                        weeks_allowed = parse_weeks_from_info(c['otherInfo'], c['parity'])
                        if week in weeks_allowed:
                            # Adaugam informatiile relevante care definesc unicitatea blocajului
                            current_blocks_raw.append(f"{c['idURL']}_{c['startHour']}_{c['duration']}")
            
            # Sortam pentru a ne asigura ca aceleasi blocaje produc aceeasi semnatura
            current_blocks_raw.sort()
            # Adaugam si ID-urile salilor cautate in semnatura (pentru ca solverul itereaza si prin ele)
            signature = hashlib.md5(f"{day}_{''.join(current_blocks_raw)}_{sali_ids}".encode()).hexdigest()

            # 2. Verificam daca am calculat deja aceasta configuratie
            if signature in solver_cache:
                free_schedule[week][day] = solver_cache[signature]
                continue

            # 3. Daca nu e in cache, rulam solverul
            day_results = []
            for sid in sali_ids:
                model = cp_model.CpModel()
                start_var = model.NewIntVar(START_DAY, END_DAY - duration_minutes, 'start')
                end_var = model.NewIntVar(START_DAY + duration_minutes, END_DAY, 'end')
                model.Add(end_var == start_var + duration_minutes)

                # Colectam blocajele specifice pentru acest model
                block_list = []
                for cat in ['profesor', 'subgrupe', 'sali']:
                    for c in constraints[cat]:
                        if c['weekDay'] == day:
                            # Daca e sala, verificam sa fie sala curenta
                            if cat == 'sali' and c['idURL'] != f"s{sid}":
                                continue
                            weeks_allowed = parse_weeks_from_info(c['otherInfo'], c['parity'])
                            if week in weeks_allowed:
                                block_list.append(c)

                # Non-Overlap constraints
                for block in block_list:
                    b_start, b_end = int(block['startHour']), int(block['startHour']) + int(block['duration'])
                    o1, o2 = model.NewBoolVar('o1'), model.NewBoolVar('o2')
                    model.Add(end_var <= b_start).OnlyEnforceIf(o1)
                    model.Add(start_var >= b_end).OnlyEnforceIf(o2)
                    model.AddBoolOr([o1, o2])

                solver = cp_model.CpSolver()
                current_search_start = START_DAY
                while current_search_start <= (END_DAY - duration_minutes):
                    model.Add(start_var >= current_search_start)
                    status = solver.Solve(model)
                    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                        f_start, f_end = solver.Value(start_var), solver.Value(end_var)
                        day_results.append({
                            "start": f_start, "end": f_end,
                            "formatted": f"{f_start//60:02d}:{f_start%60:02d} - {f_end//60:02d}:{f_end%60:02d}",
                            "sala": nume_sali.get(sid, f"Sala {sid}")
                        })
                        current_search_start = f_start + 60
                    else: break

            # Salveaza in cache si in program
            solver_cache[signature] = day_results
            free_schedule[week][day] = day_results

    return free_schedule

def group_slots_for_ui(free_slots_raw: dict):
    """
    Transformă output-ul brut al solverului într-o structură optimizată pentru UI.
    Structura: { week_no: { day_name: [ { sala: name, ore_start: [] } ] } }
    """
    day_map = {1: "Luni", 2: "Marți", 3: "Miercuri", 4: "Joi", 5: "Vineri", 6: "Sâmbătă"}
    grouped = {}

    for week, days in free_slots_raw.items():
        week_data = {}
        for day_idx, slots in days.items():
            if not slots:
                continue
            
            day_name = day_map.get(day_idx, f"Ziua {day_idx}")
            # Grupăm sloturile după numele sălii în această zi
            rooms_in_day = {}
            for s in slots:
                room_name = s['sala']
                if room_name not in rooms_in_day:
                    rooms_in_day[room_name] = []
                # Adăugăm doar ora de start (ex: "14:00")
                ora_start = s['formatted'].split(" - ")[0]
                rooms_in_day[room_name].append(ora_start)
            
            # Formatăm pentru UI (listă de obiecte pentru a fi ușor de iterat în frontend)
            week_data[day_name] = [
                {"sala": r_name, "ore_posibile": sorted(list(set(starts)))} 
                for r_name, starts in rooms_in_day.items()
            ]
        
        if week_data:
            grouped[week] = week_data
            
    return grouped

if __name__ == "__main__":
    from app.db.session import SessionLocal
    from app.schemas.user import SlotLiberRequest
    import time

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
        ora_start=8
    )

    # 2. Deschidem sesiunea DB
    db_session = SessionLocal()
    
    try:
        print(f"--- 🚀 Pornire Test CP-SAT ---")
        start_time = time.time()

        # 1. Determinăm săptămânile active folosind logica de calendar
        current_semester, active_weeks, current_status, _ = get_future_weeks_logic(db_session)
        print(f"📅 Status: {current_status} | Semestrul: {current_semester}")
        print(f"🗓️ Săptămâni de curs rămase: {active_weeks}")

        # 2. Extragere date structurate
        # 2. Extragere date structurate
        data_result = get_data(db_session, test_req)
        
        if "error" in data_result or "info" in data_result:
            print(f"❌ Mesaj: {data_result.get('error') or data_result.get('info')}")
        else:
            # Calculăm limita DOAR dacă datele au fost extrase cu succes
            max_w = data_result.get("max_week_limit", 14)
            filtered_active_weeks = [w for w in active_weeks if w <= max_w]
            
            print(f"✅ Date extrase ({len(data_result['profesor'])}P, {len(data_result['subgrupe'])}G, {len(data_result['sali'])}S)")
            print(f"📅 Limita academică detectată: s{max_w} | Săptămâni de calcul: {filtered_active_weeks}")

            # 3. Execuție Solver
            durata_min = test_req.durata * 60 if test_req.durata else 120
            
            free_slots_report = find_free_slots_cp_sat(
                db=db_session, 
                constraints=data_result, 
                sali_ids=test_req.sali_ids, 
                duration_minutes=durata_min,
                target_day=test_req.zi,
                active_weeks=filtered_active_weeks 
            ) 
            
            ui_report = group_slots_for_ui(free_slots_report)

            # 5. Afișare simulată ca în Interfață (Carduri)
            if not ui_report:
                print("📭 Nu s-au găsit sloturi libere.")
            else:
                for week, days in ui_report.items():
                    print(f"\n--- 📦 CARD SAPTAMANA {week} ---")
                    for day_name, rooms in days.items():
                        print(f"  📍 {day_name}:")
                        for r in rooms:
                            # Aici r['ore_posibile'] ar fi conținutul Dropdown-ului
                            print(f"    🏢 Sala {r['sala']} | 🕒 Dropdown ore start: {r['ore_posibile']}")

        print(time.time()-start_time)
    except Exception as e:
        print(f"🔥 Eroare: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db_session.close()