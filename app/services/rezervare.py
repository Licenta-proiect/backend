# app\services\rezervari.py
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.models.models import Rezervare, Subgrupa, Profesor, Sala, Orar
from app.schemas.user import RezervareSlotRequest, AnulareRezervareRequest
from app.utils.time_helper import get_now

def create_slot_reservation(db: Session, req: RezervareSlotRequest):
    """
    Creează o rezervare în baza de date după verificarea conflictelor.
    Include validarea împotriva orarului oficial și a rezervărilor ad-hoc existente.
    """
    try:
        # VERIFICARE TIMP (Să nu fie în trecut)
        now = get_now()
        today_date = now.date()
        # Ora curentă convertită în minute de la începutul zilei pentru comparare
        current_time_minutes = now.hour * 60 + now.minute
        ora_inceput_minutes = req.ora_start * 60

        # Verificăm dacă data este în trecut
        if req.data_rezervare < today_date:
            return {"error": "Nu se pot face rezervări pentru zile care au trecut."}
        
        # Verificăm dacă este astăzi, dar ora de început a trecut deja
        if req.data_rezervare == today_date and ora_inceput_minutes < current_time_minutes:
            return {"error": "Nu se pot face rezervări pentru un interval orar care a început deja."}

        # Identificăm profesorul (folosind email-ul din request)
        profesor = db.query(Profesor).filter(Profesor.emailAddress == req.email).first()
        if not profesor:
            return {"error": "Profesorul nu a fost găsit în baza de date."}

        ora_inceput = req.ora_start * 60 
        durata_minute = req.durata * 60
        ora_final = ora_inceput + durata_minute

        # VERIFICARE CONFLICTE (Sala, Profesor, Grupe)
        # Căutăm orice rezervare existentă care se suprapune cu intervalul dorit
        query_conflict = db.query(Rezervare).filter(
            Rezervare.zi == req.zi,
            Rezervare.saptamana == req.saptamana,
            func.lower(Rezervare.status) == func.lower("rezervat"),
            Rezervare.oraInceput < ora_final,
            (Rezervare.oraInceput + Rezervare.durata) > ora_inceput # Rezervare.durata e deja minute în DB
        )

        # Aplicăm filtrele de entitate: Sala SAU Profesor SAU Oricare dintre Grupe
        conflict = query_conflict.filter(
            or_(
                Rezervare.sala_id == req.sala_id,
                Rezervare.profesor_id == profesor.id,
                Rezervare.grupe.any(Subgrupa.id.in_(req.grupe_ids))
            )
        ).first()

        if conflict:
            if conflict.sala_id == req.sala_id:
                msg = "Sala este deja ocupată în acest interval."
            elif conflict.profesor_id == profesor.id:
                msg = "Aveți deja o altă rezervare în acest interval."
            else:
                msg = "Una dintre grupele selectate are deja o rezervare în acest interval."
            return {"error": msg}
        
        # Identificăm subgrupele
        subgrupe_obj = db.query(Subgrupa).filter(Subgrupa.id.in_(req.grupe_ids)).all()
        if len(subgrupe_obj) != len(req.grupe_ids):
            return {"error": "Una sau mai multe subgrupe selectate sunt invalide."}
        
        # Creăm obiectul Rezervare
        noua_rezervare = Rezervare(
            profesor_id=profesor.id,
            sala_id=req.sala_id,
            materie=req.materie,
            tip=req.tip_activitate,
            oraInceput=ora_inceput,
            durata=durata_minute,
            zi=req.zi,
            saptamana=req.saptamana,
            data_calendaristica=req.data_rezervare,
            capacitate_necesara=req.numar_persoane,
            status="rezervat",
            grupe=subgrupe_obj
        )

        db.add(noua_rezervare)
        db.commit()
        return {"success": "Rezervarea a fost confirmată cu succes."}
    
    except Exception as e:
        db.rollback()
        return {"error": f"Eroare la salvare: {str(e)}"}
    
def cancel_reservation(db: Session, req: AnulareRezervareRequest):
    '''
    Anulează o rezervare validă. Nu se poate anula o rezervare din trecut, sau în acceași zi.
    '''
    rezervare = db.query(Rezervare).filter(Rezervare.id == req.rezervare_id).first()
    
    if not rezervare:
        return {"error": "Rezervarea nu a fost găsită."}
    
    # Nu putem anula o rezervare care este deja 'anulat' sau 'efectuat'
    if rezervare.status.lower() != "rezervat":
        return {"error": f"Această rezervare este anulată deja."}

    now = get_now()
    today_date = now.date()

    # 1. Verificăm dacă rezervarea este în trecut
    if rezervare.data_calendaristica < today_date:
        return {"error": "Nu se pot anula rezervări din zilele trecute."}
    
    # 2. Verificăm dacă rezervarea este astăzi
    if rezervare.data_calendaristica == today_date:
        return {"error": "Anularea unei rezervări nu se poate face în aceeași zi cu evenimentul."}

    # Verificăm dacă rezervarea aparține profesorului
    profesor = db.query(Profesor).filter(Profesor.emailAddress == req.email).first()
    if not profesor or rezervare.profesor_id != profesor.id:
        return {"error": "Nu aveți dreptul să anulați această rezervare."}

    try:
        rezervare.status = "anulat"
        rezervare.motiv_anulare = req.motiv
        db.commit()
        return {"success": "Rezervarea a fost anulată cu succes."}
    except Exception as e:
        db.rollback()
        return {"error": f"Eroare la anulare: {str(e)}"}

def get_teacher_reservations(db: Session, email: str):
    """
    Obține toate rezervările unui profesor și calculează statusul (rezervat/anulat/efectuat).
    """
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    if not profesor:
        return []

    rezervari = db.query(Rezervare).filter(Rezervare.profesor_id == profesor.id).all()
    
    now = get_now()
    today_date = now.date()
    current_time_minutes = now.hour * 60 + now.minute

    result = []
    for r in rezervari:
        # Păstrăm statusul original din DB (rezervat/anulat)
        status_final = r.status 

        # Dacă statusul este 'rezervat' dar timpul a trecut, îl raportăm ca 'efectuat'
        if r.status.lower() == "rezervat":
            if r.data_calendaristica < today_date:
                status_final = "efectuată"
            elif r.data_calendaristica == today_date:
                # Dacă e azi, verificăm dacă s-a terminat și durata
                ora_final = r.oraInceput + r.durata
                if current_time_minutes > ora_final:
                    status_final = "efectuată"

        nume_grupe = [f"{g.specializationShortName} {g.groupName}{g.subgroupIndex}" for g in r.grupe]

        result.append({
            "id": r.id,
            "materie": r.materie,
            "tip": r.tip,
            "sala": r.sala.name if r.sala else "N/A",
            "grupe": nume_grupe,
            "saptamana": r.saptamana,
            "zi": r.zi,
            "data": r.data_calendaristica,
            "ora_start": r.oraInceput // 60,
            "durata": r.durata // 60,
            "status": status_final,
            "motiv_anulare": r.motiv_anulare if r.status == "anulat" else None
        })
    
    # Sortăm să vedem cele mai recente/viitoare primele
    return sorted(result, key=lambda x: x['data'], reverse=True)

def get_all_reservations_admin(db: Session):
    """
    Returnează toate rezervările din sistem pentru panoul de admin.
    Include numele profesorului și logica de status dinamic.
    """
    rezervari = db.query(Rezervare).all()
    
    now = get_now()
    today_date = now.date()
    current_time_minutes = now.hour * 60 + now.minute

    result = []
    for r in rezervari:
        status_final = r.status 

        # Logica status dinamic
        if r.status.lower() == "rezervat":
            if r.data_calendaristica < today_date:
                status_final = "efectuată"
            elif r.data_calendaristica == today_date:
                ora_final = r.oraInceput + r.durata
                if current_time_minutes > ora_final:
                    status_final = "efectuată"

        # Formatare nume grupe
        nume_grupe = [f"{g.specializationShortName} {g.groupName}{g.subgroupIndex}" for g in r.grupe]

        nume_profesor = "N/A"
        email_profesor = "N/A"
        
        if r.profesor_titular:
            nume_profesor = f"{r.profesor_titular.lastName} {r.profesor_titular.firstName}"
            email_profesor = r.profesor_titular.emailAddress
            
        result.append({
            "id": r.id,
            "profesor": nume_profesor,
            "email_profesor": email_profesor,
            "materie": r.materie,
            "tip": r.tip,
            "sala": r.sala.name if r.sala else "N/A",
            "grupe": nume_grupe,
            "data": r.data_calendaristica,
            "ora_start": r.oraInceput // 60,
            "durata": r.durata // 60,
            "status": status_final,
            "motiv_anulare": r.motiv_anulare if r.status == "anulat" else None
        })
    
    # Sortăm descrescător după dată (cele mai noi/viitoare primele)
    return sorted(result, key=lambda x: x['data'], reverse=True)

def get_reservations_by_subgroups(db: Session):
    """
    Returnează toate rezervările grupate după ID-ul subgrupei.
    Include numele profesorului și statusul dinamic (efectuată/rezervat/anulat).
    """

    # Luăm toate rezervările care au grupe asociate
    rezervari = db.query(Rezervare).join(Rezervare.grupe).all()
    
    now = get_now()
    today_date = now.date()
    current_time_minutes = now.hour * 60 + now.minute

    rezervari_grupate = {}

    for r in rezervari:
        # Calcul status dinamic
        status_final = r.status 
        if r.status.lower() == "rezervat":
            if r.data_calendaristica < today_date:
                status_final = "efectuată"
            elif r.data_calendaristica == today_date:
                ora_final = r.oraInceput + r.durata
                if current_time_minutes > ora_final:
                    status_final = "efectuată"

        # Date profesor din relația profesor_titular
        nume_profesor = f"{r.profesor_titular.lastName} {r.profesor_titular.firstName}" if r.profesor_titular else "N/A"
        
        # Numele tuturor grupelor care participă la această rezervare
        nume_grupe_display = [f"{g.specializationShortName} {g.groupName}{g.subgroupIndex}" for g in r.grupe]

        rezervare_data = {
            "id": r.id,
            "profesor": nume_profesor,
            "email_profesor": r.profesor_titular.emailAddress if r.profesor_titular else "N/A",
            "materie": r.materie,
            "tip": r.tip,
            "sala": r.sala.name if r.sala else "N/A",
            "grupe_participante": nume_grupe_display,
            "data": r.data_calendaristica.isoformat(),
            "ora_start": r.oraInceput // 60,
            "durata": r.durata // 60,
            "status": status_final,
            "motiv_anulare": r.motiv_anulare if r.status == "anulat" else None
        }

        # Grupăm pentru fiecare subgrupă participantă
        for g in r.grupe:
            if g.id not in rezervari_grupate:
                rezervari_grupate[g.id] = []
            rezervari_grupate[g.id].append(rezervare_data)

    # Sortare cronologică pentru fiecare grupă
    for gid in rezervari_grupate:
        rezervari_grupate[gid].sort(key=lambda x: x['data'], reverse=True)

    return rezervari_grupate

if __name__ == "__main__":
    from app.db.session import SessionLocal
    from app.schemas.user import RezervareSlotRequest
    from datetime import date

    # 1. Inițializăm sesiunea
    db = SessionLocal()

    try:
        print(f"--- 🧪 Pornire Teste Logica Rezervari ---")

        # DATE DE TEST (Ajustate conform output-ului tău de solver sau datelor dorite)
        test_email = "stoicaalexandra180@gmail.com"
        
        # Simulăm un request de rezervare pentru Sala C203 (ID 66) 
        # Marți (Ziua 2), Săptămâna 9, Ora 16:00
        rezervare_data = RezervareSlotRequest(
            email=test_email,
            salaId=24,
            grupeIds=[49, 50, 51],
            materie="Criptografie şi securitate informaţională",
            tipActivitate="Curs",
            zi=2,
            saptamana=9,
            oraStart=18,
            durata=2,
            data=date(2026, 4, 28), # Data din output-ul tău de solver
            numarPersoane=50
        )

        # TEST 1: Creare Rezervare Nouă
        print(f"\n[Test 1] Încercăm crearea unei rezervări valide...")
        rezultat1 = create_slot_reservation(db, rezervare_data)
        
        if "success" in rezultat1:
            print(f"✅ Succes: {rezultat1['success']}")
        else:
            print(f"❌ Eroare: {rezultat1['error']}")

        # TEST 2: Încercare de Duplicare (Conflict de Sală/Profesor)
        print(f"\n[Test 2] Încercăm crearea aceleiași rezervări (trebuie să dea CONFLICT)...")
        rezultat2 = create_slot_reservation(db, rezervare_data)
        
        if "error" in rezultat2:
            print(f"✅ Test Conflict Reușit: Sistemul a blocat suprapunerea. Mesaj: {rezultat2['error']}")
        else:
            print(f"❌ Eroare: Sistemul a permis suprapunerea! (BAD)")

        # TEST 3: Conflict de Grupă (Alt profesor, aceleași grupe)
        print(f"\n[Test 3] Verificăm conflictul de grupă (alt profesor, aceeași oră/grupe)...")
        # Schimbăm doar profesorul (email-ul) și sala, dar păstrăm grupele și ora
        rezervare_grupa_ocupata = rezervare_data.model_copy(update={
            "email": "alt.profesor@unitbv.ro", 
            "salaId": 24 # Altă sală
        })
        
        rezultat3 = create_slot_reservation(db, rezervare_grupa_ocupata)
        if "error" in rezultat3:
            print(f"✅ Test Conflict Grupă Reușit: {rezultat3['error']}")
        else:
            print(f"❌ Eroare: Grupa a fost lăsată să fie în două locuri deodată!")

    except Exception as e:
        print(f"💥 Eroare neprevăzută în timpul testării: {e}")
    finally:
        # Ștergem datele de test pentru a nu polua DB-ul permanent (opțional)
        # db.query(Rezervare).filter(Rezervare.materie == "Criptografie şi securitate informaţională").delete()
        # db.commit()
        db.close()
        print(f"\n--- 🏁 Teste Finalizate ---")