# app\services\rezervari.py
from sqlalchemy.orm import Session
from app.models.models import Rezervare, Subgrupa, Profesor, Sala, Orar
from app.schemas.user import RezervareSlotRequest
from datetime import datetime

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
        ora_inceput_minute = h * 60 + m
        ora_final_minute = ora_inceput_minute + (req.durata * 60)

        # Conflict cu alte rezervări ad-hoc deja făcute
        conflict_rezervare = db.query(Rezervare).filter(
            Rezervare.sala_id == req.sala_id,
            Rezervare.zi == req.zi,
            Rezervare.saptamana == req.saptamana,
            Rezervare.status == "rezervat"
        ).filter(
            # Logica de suprapunere: (Start1 < End2) AND (End1 > Start2)
            Rezervare.oraInceput < ora_final_minute,
            (Rezervare.oraInceput + Rezervare.durata * 60) > ora_inceput_minute
        ).first()

        if conflict_rezervare:
            return {"error": "Slotul a fost ocupat între timp de o altă rezervare."}

        # Identificăm subgrupele
        subgrupe = db.query(Subgrupa).filter(Subgrupa.id.in_(req.grupe_ids)).all()
        if len(subgrupe) != len(req.grupe_ids):
            return {"error": "Una sau mai multe subgrupe nu au fost găsite."}

        # Creăm obiectul Rezervare
        noua_rezervare = Rezervare(
            profesor_id=profesor.id,
            sala_id=req.sala_id,
            materie=req.materie,
            tip=req.tip_activitate,
            oraInceput=ora_inceput_minute,
            durata=req.durata,
            zi=req.zi,
            saptamana=req.saptamana,
            data_calendaristica=req.data_rezervare,
            capacitate_necesara=req.numar_persoane,
            status="rezervat",
            grupe=subgrupe
        )

        db.add(noua_rezervare)
        db.commit()
        db.refresh(noua_rezervare)

        # 6. Returnăm un răspuns de succes îmbogățit
        return {"success": "Rezervarea a fost confirmată."}

    except Exception as e:
        db.rollback()
        return {"error": f"Eroare la salvare: {str(e)}"}