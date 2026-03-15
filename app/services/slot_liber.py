# app\services\slot_liber.py
from datetime import datetime
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa, Profesor, Sala, Rezervare
from app.schemas.user import SlotLiberRequest
from app.utils.time_helper import get_now
from typing import List
import hashlib
from ortools.sat.python import cp_model

from app.services.future_weeks import get_future_weeks_logic
from app.utils.date_helper import get_calendar_date
from .slot_alternativ import format_row, parse_weeks_from_info

def format_rezervare_to_orar(rez: Rezervare, tag: str):
    """
    Transformă un obiect Rezervare într-un dicționar compatibil cu format_row,
    pentru a fi procesat unitar de solver.
    """
    return {
        "idURL": tag,
        "weekDay": rez.zi,
        "startHour": rez.oraInceput,
        "duration": rez.durata,
        "parity": 0,  # Rezervările ad-hoc sunt specifice unei săptămâni
        "otherInfo": f"S{rez.saptamana}" 
    }

def get_profesor_id(db: Session, email: str):
    '''Identifică profesorul în baza de date folosind adresa de email.'''
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    
    if not profesor:
        return None
    
    return profesor.id

def get_max_week_for_groups(db: Session, id_grupe: List[int], current_semester: int) -> int:
    """
    Determină săptămâna maximă (10 sau 14).
    Anii terminali au:
    - 14 săptămâni în Semestrul 1
    - 10 săptămâni în Semestrul 2
    """
    # Dacă suntem în Semestrul 1, oricum toată lumea are 14 săptămâni
    if current_semester == 1:
        return 14

    grupe = db.query(Subgrupa).filter(Subgrupa.id.in_(id_grupe)).all()
    if not grupe:
        return 14

    is_terminal = False
    for g in grupe:
        # Căutăm care este anul maxim pentru specializarea acestei grupe
        max_year = db.query(func.max(Subgrupa.studyYear)).filter(
            Subgrupa.specializationShortName == g.specializationShortName,
            Subgrupa.faculty_id == g.faculty_id
        ).scalar()
        
        # Dacă grupa curentă este în anul maxim, e an terminal
        if g.studyYear == max_year:
            is_terminal = True
            break # E suficient ca o grupă să fie terminală pentru a limita căutarea
            
    return 10 if is_terminal else 14

def valideaza_configuratie_grupe(id_grupe: List[int], tip_activitate: str):
    """
    Validează dacă numărul de grupe selectate este permis pentru tipul de activitate.
    """
    tip = tip_activitate.lower()
    numar_grupe = len(id_grupe)

    if tip in ["laborator", "proiect"] and numar_grupe > 1:
        return {
            "info": f"Pentru activități de tip {tip_activitate}, se poate selecta o singură grupă."
        }
    
    if tip == "seminar" and numar_grupe > 2:
        return {
            "info": "Pentru activități de tip seminar, se pot selecta maxim 2 grupe."
        }
    
    return None

def verifica_existenta_materie(db: Session, id_profesor: int, id_grupe: List[int], materie: str, tip_materie: str) -> bool:
    """
    Verifică existența materiei în orar.
    - Pentru CURS: Verifică dacă materia există la profesor, iar grupele au acest profesor 
      la acest tip de activitate (permite variații de nume între specializări).
    - Pentru ALTEL (Lab/Sem): Verifică potrivirea strictă profesor-materie-grupă.
    """
    tip_lower = tip_materie.lower()
    
    # 1. Validare inițială: Materia trebuie să existe obligatoriu în orarul profesorului
    prof_record = db.query(Orar).filter(
        Orar.idURL == f"p{id_profesor}",
        Orar.teacherID == id_profesor,
        func.lower(Orar.topicLongName) == func.lower(materie),
        func.lower(Orar.typeLongName) == func.lower(tip_materie)
    ).first()

    if not prof_record:
        return False

    # 2. Validare pentru fiecare grupă
    for gid in id_grupe:
        tag_grupa = f"g{gid}"
        
        if "curs" in tip_lower:
            # LOGICĂ CURS: Verificăm dacă profesorul predă cursul la această grupă, 
            # indiferent dacă numele materiei diferă puțin (ex: "Mate 1" vs "Mate")
            grupa_has_prof = db.query(Orar).filter(
                Orar.idURL == tag_grupa,
                Orar.teacherID == id_profesor,
                func.lower(Orar.typeLongName) == tip_lower
            ).first()
            
            if not grupa_has_prof:
                return False
        else:
            # LOGICĂ STRICTĂ (Lab/Sem/Proiect): Materia și profesorul trebuie să coincidă exact
            grupa_has_exact_topic = db.query(Orar).filter(
                Orar.idURL == tag_grupa,
                Orar.teacherID == id_profesor,
                func.lower(Orar.topicLongName) == func.lower(materie),
                func.lower(Orar.typeLongName) == tip_lower
            ).first()
            
            if not grupa_has_exact_topic:
                return False

    return True

def get_data(db: Session, req: SlotLiberRequest, current_semester: int):
    '''Extrage datele din orar ȘI rezervări pentru profesor, subgrupe și săli'''
    validare = valideaza_configuratie_grupe(req.grupe_ids, req.tip_activitate)
    if validare:
        return validare
    
    # Preia ID Profesor din email
    id_prof = get_profesor_id(db, req.email)
    if not id_prof:
        return {"info": f"Profesorul cu email-ul {req.email} nu a fost găsit."}

    # Verifică existența materiei și tipului pentru toți actorii (Prof + Grupe)
    if not verifica_existenta_materie(db, id_prof, req.grupe_ids, req.materie, req.tip_activitate):
        return {"info": "Materia sau tipul de activitate nu a fost găsit în orarul profesorului sau al grupelor."}

    # Determinăm săptămâna maximă pe baza anului de studiu
    max_week_limit = get_max_week_for_groups(db, req.grupe_ids, current_semester)

    # COLECTARE DATE DIN ORARUL OFICIAL
    tags_prof = [f"p{id_prof}"]
    tags_grupe = [f"g{gid}" for gid in req.grupe_ids]
    tags_sali = [f"s{sid}" for sid in req.sali_ids]
    all_tags = tags_prof + tags_grupe + tags_sali

    # Extrage toate datele din orar care au idURL în lista construită
    query_orar = db.query(Orar).filter(Orar.idURL.in_(all_tags))

    # Filtrare după ZI (weekDay), dacă este specificată
    if req.zi is not None:
        query_orar = query_orar.filter(Orar.weekDay == req.zi)
    
    orar_data = query_orar.all()

    # COLECTARE REZERVĂRI AD-HOC (Conflict prevention)
    # Căutăm rezervările active care implică profesorul, sălile sau grupele selectate
    query_rezervari = db.query(Rezervare).filter(
        Rezervare.status == "rezervat"
    )

    if req.zi is not None:
        query_rezervari = query_rezervari.filter(Rezervare.zi == req.zi)

    # Executăm query-ul pentru rezervări
    toate_rezervarile = query_rezervari.all()

    # FILTRARE ȘI FORMATARE DATE
    # Pregătim containerele pentru solver
    prof_blocks = [format_row(r) for r in orar_data if r.idURL in tags_prof]
    grupe_blocks = [format_row(r) for r in orar_data if r.idURL in tags_grupe]
    sali_blocks = [format_row(r) for r in orar_data if r.idURL in tags_sali]

    # Adăugăm rezervările ad-hoc în containerele corespunzătoare
    for rez in toate_rezervarile:
        # Dacă profesorul este implicat în această rezervare
        if rez.profesor_id == id_prof:
            prof_blocks.append(format_rezervare_to_orar(rez, f"p{id_prof}"))
        
        # Dacă sala este una din cele căutate
        if rez.sala_id in req.sali_ids:
            sali_blocks.append(format_rezervare_to_orar(rez, f"s{rez.sala_id}"))
        
        # Dacă oricare dintre grupele selectate este implicată în rezervare
        # Verificăm intersecția dintre grupele rezervării și grupele cerute
        rez_grupe_ids = [g.id for g in rez.grupe]
        for gid in req.grupe_ids:
            if gid in rez_grupe_ids:
                grupe_blocks.append(format_rezervare_to_orar(rez, f"g{gid}"))
                break # Evităm duplicatele dacă o rezervare are mai multe din grupele noastre

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
        
        # Păstrăm doar blocajele pentru sălile care au capacitate suficientă
        sali_blocks = [b for b in sali_blocks if int(b['idURL'][1:]) in valid_sala_ids]
    
    return {
        "profesor": prof_blocks,
        "subgrupe": grupe_blocks,
        "sali": sali_blocks,
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
                    b_start = int(block['startHour'])
                    b_end = b_start + int(block['duration'])
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
                            "start": f_start,
                            "end": f_end,
                            "sala_id": sid
                        })
                        current_search_start = f_start + 60
                    else: break

            # Salveaza in cache si in program
            solver_cache[signature] = day_results
            free_schedule[week][day] = day_results

    return free_schedule

def group_slots_for_ui(db: Session, free_slots_raw: dict, current_semester: int):
    """
    Transformă output-ul solverului în structură UI.
    Filtrează zilele trecute și orele trecute din ziua curentă conform get_now().
    """
    day_map = {1: "Luni", 2: "Marți", 3: "Miercuri", 4: "Joi", 5: "Vineri", 6: "Sâmbătă"}
    grouped = {}
    
    now = get_now()
    today_date = now.date()

    for week, days in free_slots_raw.items():
        week_data = []
        for day_idx, slots in days.items():
            if not slots:
                continue

            # Calculăm data calendaristică a slotului
            data_str = get_calendar_date(db, week, day_idx, current_semester)
            
            try:
                slot_date = datetime.strptime(data_str, "%d.%m.%Y").date()
                
                #  Dacă ziua a trecut deja, sărim peste toată ziua
                if slot_date <= today_date:
                    continue
                    
            except (ValueError, TypeError):
                continue

            # Grupăm sloturile direct într-un format plat
            day_slots = []
            for s in slots:
                day_slots.append({
                    "sala_id": s['sala_id'],
                    "ora_start": s['start'] // 60, 
                    "ora_final": s['end'] // 60,   
                })
            
            if day_slots:
                week_data.append({
                    "zi_index": day_idx,
                    "zi_nume": day_map.get(day_idx),
                    "data": slot_date.strftime("%Y-%m-%d"),
                    "optiuni": day_slots
                })
        
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
        saptamani=[9]
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
        data_result = get_data(db_session, test_req, current_semester)
        
        if "error" in data_result or "info" in data_result:
            print(f"❌ Mesaj: {data_result.get('error') or data_result.get('info')}")
        else:
            # Calculăm limita DOAR dacă datele au fost extrase cu succes
            max_w = data_result.get("max_week_limit", 14)
            target_weeks = test_req.saptamani if test_req.saptamani else active_weeks
            
            filtered_active_weeks = [
                w for w in target_weeks 
                if w <= max_w and w in active_weeks
            ]
            
            if not filtered_active_weeks:
                print(f"⚠️ Nicio săptămână din cele selectate ({test_req.saptamani}) nu este validă academic sau viitoare.")
            else:
                print(f"✅ Date extrase. Calculăm pentru: {filtered_active_weeks}")

                durata_min = test_req.durata * 60 if test_req.durata else 120
                
                # Rulăm solverul DOAR pe săptămânile filtrate
                free_slots_report = find_free_slots_cp_sat(
                    db=db_session, 
                    constraints=data_result, 
                    sali_ids=test_req.sali_ids, 
                    duration_minutes=durata_min,
                    target_day=test_req.zi,
                    active_weeks=filtered_active_weeks 
                ) 
                
                ui_report = group_slots_for_ui(db_session, free_slots_report, current_semester)

                if not ui_report:
                    print("📭 Nu s-au găsit sloturi libere.")
                else:
                    for week, days in ui_report.items():
                        print(f"\n--- 📦 CARD SAPTAMANA {week} ---")
                        for day_name, rooms in days.items():
                            print(f"  📍 {day_name}:")
                            for r in rooms:
                                print(f"    🏢 Sala {r['sala']} | 🕒 Ore start: {r['ore_posibile']}")

        print(f"\n⏱️ Timp execuție: {time.time()-start_time:.2f}s")
    finally:
        db_session.close()