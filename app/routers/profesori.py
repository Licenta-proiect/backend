# app\routers\profesori.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import Profesor, Orar, Subgrupa, Sala, User
from app.services.auth import get_current_user
from app.services.rezervare import get_teacher_reservations

# Inițializezi router-ul
router = APIRouter(prefix="/profesor", tags=["Profesori"])

@router.get("/materii")
async def get_profesor_materii(email: str, db: Session = Depends(get_db)):
    """
    Returnează lista unică de materii predate de profesor doar grupelor 
    de la facultatea FIESC.
    """
    # 1. Identificăm profesorul pentru a-i lua ID-ul
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    
    if not profesor:
        raise HTTPException(
            status_code=404, 
            detail="Profesorul cu acest email nu a fost găsit în baza de date."
        )

    # 2. Căutăm în Orar toate materiile (topicLongName) asociate acestui profesor,
    # dar filtrăm doar rândurile care aparțin grupelor (idURL începe cu 'g')
    # Această filtrare asigură că vezi doar cursurile predate facultății tale.
    materii_query = db.query(Orar.topicLongName).filter(
        Orar.teacherID == profesor.id,
        Orar.idURL.like('g%')
    ).distinct().all()

    # 3. Convertim rezultatul într-o listă unică de string-uri, ordonată alfabetic
    set_materii = sorted([m[0] for m in materii_query if m[0]])

    return {
        "id": profesor.id,
        "lastName": profesor.lastName,
        "firstName": profesor.firstName,
        "materii": set_materii
    }

@router.get("/grupe")
async def get_profesor_grupe(email: str, db: Session = Depends(get_db)):
    """
    Identifică grupele la care predă profesorul, doar de la facultatea FIESC.
    """
    # 1. Identificăm profesorul pentru a-i lua ID-ul
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    if not profesor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # 2. Căutăm în Orar toate idURL-urile de tip grupă ('g...') unde apare acest profesor
    # teacherID este salvat pe toate rândurile evenimentului (inclusiv pe cele de grupă)
    grupe_ids_query = db.query(Orar.idURL).filter(
        Orar.teacherID == profesor.id,
        Orar.idURL.like('g%')
    ).distinct().all()

    # 3. Extragem ID-urile numerice din formatul 'gID'
    ids_set = {int(row[0][1:]) for row in grupe_ids_query if row[0] and len(row[0]) > 1}

    if not ids_set:
        return {
            "id": profesor.id,
            "lastName": profesor.lastName,
            "firstName": profesor.firstName,
            "grupe": []
        }

    # 4. Luăm detaliile din Subgrupa și ordonăm direct din query după nume (groupName) și index (subgroupIndex)
    # Folosim .asc() pentru a asigura ordinea crescătoare
    grupe_detalii = db.query(Subgrupa).filter(
        Subgrupa.id.in_(list(ids_set))
    ).order_by(
        Subgrupa.groupName.asc(), 
        Subgrupa.subgroupIndex.asc()
    ).all()

    # 5. Trimitem lista de obiecte {id, nume}
    rezultat = [
        {
            "id": g.id,
            "nume": g.groupName, 
            "subgroupIndex":g.subgroupIndex if g.subgroupIndex else '',
            "studyYear": g.studyYear,
            "specializationShortName": g.specializationShortName
        } for g in grupe_detalii
    ]

    return {
        "id": profesor.id,
        "lastName": profesor.lastName,
        "firstName": profesor.firstName,
        "grupe": rezultat
    }

@router.get("/sali")
async def get_profesor_sali(email: str, db: Session = Depends(get_db)):
    """
    Identifică sălile în care predă profesorul, limitat la grupele de la FIESC.
    """
    # 1. Identificăm profesorul pentru a-i lua ID-ul intern
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    if not profesor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # 2. Căutăm în Orar toate roomId-urile distincte pentru acest profesor
    # Folosim idURL.like('g%') pentru a ne asigura că luăm sălile doar de la grupele de la FIESC
    sali_ids_query = db.query(Orar.roomId).filter(
        Orar.teacherID == profesor.id,
        Orar.idURL.like('g%')
    ).distinct().all()

    # 3. Extragem ID-urile reale ale sălilor din coloana roomId (filtrând valorile None)
    ids_set = {row[0] for row in sali_ids_query if row[0] is not None}

    if not ids_set:
        return {
            "id": profesor.id,
            "lastName": profesor.lastName,
            "firstName": profesor.firstName,
            "sali": []
        }

    # 4. Luăm detaliile din tabelul Sala și le ordonăm alfabetic după nume
    sali_detalii = db.query(Sala).filter(
        Sala.id.in_(list(ids_set))
    ).order_by(Sala.name.asc()).all()

    # 5. Trimitem lista de obiecte conform modelului Sala
    rezultat = [
        {
            "id": s.id,
            "nume": s.name,
            "shortName": s.shortName,
            "buildingName": s.buildingName
        } for s in sali_detalii
    ]

    return {
        "id": profesor.id,
        "lastName": profesor.lastName,
        "firstName": profesor.firstName,
        "sali": rezultat
    }

@router.get("/grupe-materie")
async def get_grupe_prin_materie(
    email: str, 
    materie: str, 
    tip: str = None, 
    db: Session = Depends(get_db)
):
    """
    Identifică grupele la care predă un profesor o materie.
    Dacă tipul este 'Curs', caută și grupele de la specializări diferite (comasate).
    """
    # 1. Identificăm profesorul
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    if not profesor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # 2. Obținem setul de date "ancoră" (grupele care au materia cu numele exact)
    # Căutăm înregistrările de tip grupă ('g%')
    ancora_query = db.query(Orar).filter(
        Orar.teacherID == profesor.id,
        Orar.idURL.like('g%'),
        Orar.topicLongName == materie
    )
    
    if tip:
        ancora_query = ancora_query.filter(Orar.typeLongName == tip)
        
    ancora_rows = ancora_query.all()
    
    # ID-urile grupelor inițiale și numele lor scurte pentru cross-check
    ids_set = {int(row.idURL[1:]) for row in ancora_rows if row.idURL and len(row.idURL) > 1}

    # 3. Logica specială pentru CURS (Căutare grupe comasate/specializări diferite)
    if tip and "curs" in tip.lower() and ancora_rows:
        # Pre-încărcăm specializările pentru grupele ancoră ca să știm ce să căutăm în otherInfo
        specializari_ancora = db.query(Subgrupa.id, Subgrupa.specializationShortName).filter(
            Subgrupa.id.in_(list(ids_set))
        ).all()
        # Map: {id_subgrupa: specializationShortName}
        map_ancore = {s.id: s.specializationShortName for s in specializari_ancora if s.specializationShortName}

        for row in ancora_rows:
            id_ancora = int(row.idURL[1:])
            spec_ancora = map_ancore.get(id_ancora)
            
            # Căutăm evenimente simultane (același profesor, timp, sală), dar materie diferită
            potentiale = db.query(Orar).filter(
                Orar.teacherID == profesor.id,
                Orar.idURL.like('g%'),
                Orar.weekDay == row.weekDay,
                Orar.startHour == row.startHour,
                Orar.duration == row.duration,
                Orar.roomId == row.roomId,
                Orar.topicLongName != materie
            ).all()

            for p in potentiale:
                id_p = int(p.idURL[1:])
                # Obținem specializarea grupei potențiale
                sub_p = db.query(Subgrupa).filter(Subgrupa.id == id_p).first()
                if not sub_p or not sub_p.specializationShortName:
                    continue

                spec_p = sub_p.specializationShortName

                # VALIDARE SIMETRICĂ:
                # 1. Specializarea ancorei (ex: C) trebuie să fie în notele lui p (otherInfo)
                # 2. Specializarea lui p (ex: AIA) trebuie să fie în notele ancorei (row.otherInfo)
                check_A = (p.otherInfo and spec_ancora and spec_ancora in p.otherInfo)
                check_B = (row.otherInfo and spec_p and spec_p in row.otherInfo)

                if check_A and check_B:
                    ids_set.add(id_p)

    if not ids_set:
        return {
            "id": profesor.id,
            "lastName": profesor.lastName,
            "firstName": profesor.firstName,
            "materie": materie,
            "grupe": [],
            "tip_selectat": tip,
        }

    # 4. Obținem detaliile complete pentru toate ID-urile colectate
    grupe_detalii = db.query(Subgrupa).filter(
        Subgrupa.id.in_(list(ids_set))
    ).order_by(
        Subgrupa.groupName.asc(), 
        Subgrupa.subgroupIndex.asc()
    ).all()

    rezultat = [
        {
            "id": g.id,
            "nume": g.groupName, 
            "subgroupIndex": g.subgroupIndex if g.subgroupIndex else '',
            "studyYear": g.studyYear,
            "specializationShortName": g.specializationShortName
        } for g in grupe_detalii
    ]

    return {
        "id": profesor.id,
        "lastName": profesor.lastName,
        "firstName": profesor.firstName,
        "materie": materie,
        "tip_selectat": tip,
        "grupe": rezultat
    }

@router.get("/sali-materie")
async def get_sali_prin_materie(email: str, materie: str, db: Session = Depends(get_db)):
    """
    Identifică sălile unde un anumit profesor predă o anumită materie,
    limitat la grupele de la FIESC.
    """
    # 1. Identificăm profesorul după email
    profesor = db.query(Profesor).filter(Profesor.emailAddress == email).first()
    if not profesor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # 2. Căutăm în Orar toate roomId-urile distincte unde profesorul predă materia respectivă
    # Folosim idURL.like('g%') pentru a limita rezultatele la orarul grupelor sincronizate
    sali_ids_query = db.query(Orar.roomId).filter(
        Orar.teacherID == profesor.id,
        Orar.idURL.like('g%'),
        Orar.topicLongName == materie
    ).distinct().all()

    # 3. Extragem ID-urile numerice ale sălilor (filtrând valorile nule)
    ids_set = {row[0] for row in sali_ids_query if row[0] is not None}

    if not ids_set:
        return {
            "id": profesor.id,
            "lastName": profesor.lastName,
            "firstName": profesor.firstName,
            "materie": materie,
            "sali": []
        }

    # 4. Luăm detaliile din tabelul Sala și le ordonăm alfabetic după nume
    sali_detalii = db.query(Sala).filter(
        Sala.id.in_(list(ids_set))
    ).order_by(Sala.name.asc()).all()

    # 5. Formatăm rezultatul similar cu ruta /sali
    rezultat = [
        {
            "id": s.id,
            "nume": s.name,
            "shortName": s.shortName,
            "buildingName": s.buildingName
        } for s in sali_detalii
    ]

    return {
        "id": profesor.id,
        "lastName": profesor.lastName,
        "firstName": profesor.firstName,
        "materie": materie,
        "sali": rezultat
    }

@router.get("/rezervari")
def listare_rezervari_profesor(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returnează lista tuturor rezervărilor făcute de profesorul logat,
    cu statusul actualizat în funcție de timp.
    """
    return get_teacher_reservations(db, current_user.email)