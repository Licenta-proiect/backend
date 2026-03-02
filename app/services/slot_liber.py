# app\services\slot_liber.py
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa, Profesor, Sala
from app.schemas.user import SlotLiberRequest
from typing import List
from ortools.sat.python import cp_model

from app.services.future_weeks import get_future_weeks_logic
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
    # Preia ID Profesor din email
    id_prof = get_profesor_id(db, req.email)
    if not id_prof:
        return {"info": f"Profesorul cu email-ul {req.email} nu a fost găsit."}

    # Verifică existența materiei și tipului pentru toți actorii (Prof + Grupe)
    if not verifica_existenta_materie(db, id_prof, req.grupe_ids, req.materie, req.tip_activitate):
        return {"info": "Materia sau tipul de activitate nu a fost găsit în orarul profesorului sau al grupelor."}

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

    # Structurăm datele în cei 3 vectori ceruți
    constraints = {
        "profesor": [format_row(r) for r in all_schedule_data if r.idURL in tags_prof],
        "subgrupe": [format_row(r) for r in all_schedule_data if r.idURL in tags_grupe],
        "sali": [format_row(r) for r in all_schedule_data if r.idURL in tags_sali]
    }

    return constraints

def find_free_slots_cp_sat(db: Session, constraints: dict, sali_ids: List[int], duration_minutes: int, target_day: int, active_weeks: List[int]):
    """Identifică intervalele libere folosind CP-SAT, doar pentru săptămânile active."""
    START_DAY, END_DAY = 8 * 60, 21 * 60  # 08:00 - 21:00
    free_schedule = {w: {d: [] for d in range(1, 7)} for w in range(1, 15)}
    
    nume_sali = {s.id: s.name for s in db.query(Sala).filter(Sala.id.in_(sali_ids)).all()}

    # Iterăm doar prin săptămânile care nu s-au încheiat încă
    for week in active_weeks:
        zile = [target_day] if target_day is not None else range(1, 7)
        for day in zile:
            for sid in sali_ids:
                model = cp_model.CpModel()
                
                # 1. Definim variabila intervalului căutat (Slotul Liber)
                start_var = model.NewIntVar(START_DAY, END_DAY - duration_minutes, 'start')
                end_var = model.NewIntVar(START_DAY + duration_minutes, END_DAY, 'end')
                # Constrângere durată: end - start = durata
                model.Add(end_var == start_var + duration_minutes)
                
                # 2. Colectăm toate blocajele (Profesor + Toate Grupele + Sala curentă)
                block_list = []
                # Constrângeri profesor
                block_list += [c for c in constraints['profesor'] if c['weekDay'] == day and week in parse_weeks_from_info(c['otherInfo'], c['parity'])]
                # Constrângeri grupe
                block_list += [c for c in constraints['subgrupe'] if c['weekDay'] == day and week in parse_weeks_from_info(c['otherInfo'], c['parity'])]
                # Constrângeri sala specifică
                block_list += [c for c in constraints['sali'] if c['idURL'] == f"s{sid}" and c['weekDay'] == day and week in parse_weeks_from_info(c['otherInfo'], c['parity'])]

                # 3. Adăugăm constrângerile de Non-Overlap în model
                for block in block_list:
                    b_start = int(block['startHour'])
                    b_end = b_start + int(block['duration'])
                    
                    # Logica CP-SAT: Slotul (start_var, end_var) NU trebuie să se suprapună cu (b_start, b_end)
                    # Adică: slot_end <= b_start SAU slot_start >= b_end
                    overlap_condition_1 = model.NewBoolVar('overlap_1')
                    model.Add(end_var <= b_start).OnlyEnforceIf(overlap_condition_1)
                    
                    overlap_condition_2 = model.NewBoolVar('overlap_2')
                    model.Add(start_var >= b_end).OnlyEnforceIf(overlap_condition_2)
                    
                    model.AddBoolOr([overlap_condition_1, overlap_condition_2])

                # 4. Rezolvăm și căutăm toate soluțiile posibile pentru acest interval
                solver = cp_model.CpSolver()
                
                # Căutăm soluții în trepte de 30 minute pentru a nu genera mii de rezultate identice
                current_search_start = START_DAY
                while current_search_start <= (END_DAY - duration_minutes):
                    model.Add(start_var >= current_search_start)
                    status = solver.Solve(model)
                    
                    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
                        found_start = solver.Value(start_var)
                        found_end = solver.Value(end_var)
                        
                        free_schedule[week][day].append({
                            "start": found_start,
                            "end": found_end,
                            "formatted": f"{found_start//60:02d}:{found_start%60:02d} - {found_end//60:02d}:{found_end%60:02d}",
                            "sala": nume_sali.get(sid, f"Sala {sid}")
                        })
                        # Mergem mai departe cu căutarea (pas de 60 min)
                        current_search_start = found_start + 60
                    else:
                        break
                        
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
        zi=None,   # Testăm pentru toate zilele săptămânii
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
        data_result = get_data(db_session, test_req)
        
        if "error" in data_result or "info" in data_result:
            print(f"❌ Mesaj: {data_result.get('error') or data_result.get('info')}")
        else:
            print(f"✅ Date extrase ({len(data_result['profesor'])}P, {len(data_result['subgrupe'])}G, {len(data_result['sali'])}S)")

            # 3. Execuție Solver
            durata_min = test_req.durata * 60 if test_req.durata else 120
            
            free_slots_report = find_free_slots_cp_sat(
                db=db_session, 
                constraints=data_result, 
                sali_ids=test_req.sali_ids, 
                duration_minutes=durata_min,
                target_day=test_req.zi,
                active_weeks=active_weeks # Pasăm săptămânile determinate din calendar
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