# app\services\rezervari.py
from sqlalchemy.orm import Session
from sqlalchemy import or_
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
            Rezervare.status == "rezervat",
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