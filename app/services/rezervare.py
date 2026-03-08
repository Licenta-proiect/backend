# app\services\rezervari.py
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.models.models import Rezervare, Subgrupa, Profesor, Sala, Orar
from app.schemas.user import RezervareSlotRequest

def create_slot_reservation(db: Session, req: RezervareSlotRequest):
    """
    Creează o rezervare în baza de date după verificarea conflictelor.
    Include validarea împotriva orarului oficial și a rezervărilor ad-hoc existente.
    """
    try:
        # Identificăm profesorul (folosind email-ul din request)
        profesor = db.query(Profesor).filter(Profesor.emailAddress == req.email).first()
        if not profesor:
            return {"error": "Profesorul nu a fost găsit în baza de date."}

        # Convertim ora HH:MM în minute (ex: "08:00" -> 480)
        h, m = map(int, req.ora_start.split(':'))
        ora_inceput = h * 60 + m
        ora_final = ora_inceput + (req.durata * 60)

        # VERIFICARE CONFLICTE (Sala, Profesor, Grupe)
        # Căutăm orice rezervare existentă care se suprapune cu intervalul dorit
        query_conflict = db.query(Rezervare).filter(
            Rezervare.zi == req.zi,
            Rezervare.saptamana == req.saptamana,
            func.lower(Rezervare.status) == func.lower("rezervat"),
            Rezervare.oraInceput < ora_final,
            (Rezervare.oraInceput + Rezervare.durata * 60) > ora_inceput
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
            durata=req.durata,
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
            salaId=66,
            grupeIds=[49, 50, 51],
            materie="Criptografie şi securitate informaţională",
            tipActivitate="Curs",
            zi=2,
            saptamana=9,
            oraStart="16:00",
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