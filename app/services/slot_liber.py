# app\services\slot_liber.py
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from app.models.models import Orar, Subgrupa, Profesor, Sala
from app.schemas.user import SlotLiberRequest
from typing import List, Optional
import re
from slot_alternativ import format_row, parse_weeks_from_info

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
        sali_valide = db.query(Sala.id).filter(
            Sala.id.in_(req.sali_ids),
            Sala.capacity >= req.numar_persoane
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