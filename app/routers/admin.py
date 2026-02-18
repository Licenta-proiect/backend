# app\routers\admin.py
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone
from app.db.session import get_db
from app.services.auth import get_current_user
from app.models.models import User, UserRole, Profesor, IstoricSincronizare, CerereEmailProfesor
from app.services.scraper import populate as populate_base
from app.services.scraper_calendar import run as populate_calendar
from app.services.scraper_orar import populate as populate_orar
from app.schemas.user import UserCreate, UserResponse, ProfesorUpdate, SyncHistoryResponse
from app.services.sync_logger import run_sync_with_logging

router = APIRouter(prefix="/admin", tags=["Admin"])

def check_admin(user: User):
    """Verifică dacă utilizatorul are rol de administrator."""
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Acces interzis. Necesar Admin.")

# --- RUTE MANAGEMENT USERI ---
@router.get("/users", response_model=List[UserResponse])
async def get_all_users(
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """Selectează toți utilizatorii din baza de date."""
    check_admin(admin_user)
    users = db.query(User).all() 
    return users

@router.post("/users/create")
async def create_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """Creează un utilizator nou și îl leagă de tabela profesori dacă este cazul."""
    check_admin(admin_user)
    
    # 1. Verificăm dacă user-ul există deja în tabela users
    existing_user = db.query(User).filter(User.email == user_in.email).first() 
    if existing_user:
        raise HTTPException(status_code=400, detail="Email deja înregistrat.")
    
    # 2. Inițializăm noul utilizator
    new_user = User(
        lastName=user_in.lastName,
        firstName=user_in.firstName,
        email=user_in.email,
        role=user_in.role.value
    ) 
    
    # 3. Dacă rolul este PROFESOR, căutăm corespondența în tabela profesori
    if user_in.role.value == UserRole.PROFESOR.value:
        # Căutăm profesorul după email
        profesor = db.query(Profesor).filter(Profesor.emailAddress == user_in.email).first()
        
        if profesor:
            # Facem legătura prin ID
            new_user.teacher_id = profesor.id
        else:
            # Opțional: Poți decide dacă permiți crearea fără legătură sau arunci eroare
            # Dacă profesorul nu e în baza de date a orarului, poate ar trebui să refuzi
            raise HTTPException(
                status_code=404, 
                detail="Acest email nu a fost găsit în lista oficială de profesori (orar)."
            )

    db.add(new_user) 
    try:
        db.commit() 
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Eroare la salvarea în baza de date.")

    return {"message": f"Utilizatorul {user_in.firstName} {user_in.lastName} a fost creat cu succes sub rolul de {user_in.role.value}."}

@router.delete("/users/delete/{email}")
async def delete_user(
    email: str, 
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """Șterge un utilizator după adresa de email, cu protecție pentru admin-ul principal."""
    check_admin(admin_user)
    
    user_to_delete = db.query(User).filter(User.email == email).first() 
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="Utilizatorul nu a fost găsit.")
    
    # Verificăm dacă user-ul vizat este admin-ul principal (ID 1)
    if user_to_delete.id == 1:
        raise HTTPException(
            status_code=403, 
            detail="Administratorul principal al sistemului nu poate fi șters."
        )
    
    # Împiedicăm un admin să se șteargă singur
    if user_to_delete.id == admin_user.id:
        raise HTTPException(
            status_code=400, 
            detail="Nu îți poți șterge propriul cont din această interfață."
        )

    db.delete(user_to_delete)
    db.commit() 
    return {"message": f"Utilizatorul {email} a fost șters cu succes."}

@router.put("/users/update/{email}", response_model=UserResponse)
async def update_user(
    email: str, 
    last_name: Optional[str] = None, 
    first_name: Optional[str] = None,
    new_email: Optional[str] = None,
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """
    Actualizează datele utilizatorului. 
    Dacă se schimbă email-ul, se actualizează manual și în tabela profesori.
    """
    check_admin(admin_user)
    
    # Căutăm utilizatorul după email-ul actual
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu a fost găsit.")
    
    # 1. Actualizare nume/prenume
    if last_name is not None:
        user.lastName = last_name 
    if first_name is not None:
        user.firstName = first_name 

    # 2. Actualizare Email cu Sincronizare Manuală
    if new_email is not None and new_email != email:
        # Verificăm dacă noul email este deja folosit
        email_taken = db.query(User).filter(User.email == new_email).first()
        if email_taken:
            raise HTTPException(
                status_code=400, 
                detail="Noul email este deja înregistrat de un alt utilizator."
            )
        
        # Sincronizare manuală în tabela Profesori
        # Dacă utilizatorul are o legătură cu tabela profesori (prin profesor_info sau teacher_id)
        if user.profesor_info:
            user.profesor_info.emailAddress = new_email
        
        # Actualizăm email-ul principal
        user.email = new_email 

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Eroare la salvare: {str(e)}")

    return user

# --- RUTE MANAGEMENT CERERI ACCES PROFESORI --- 

@router.get("/requests")
async def get_professor_requests(
    status: Optional[str] = None, # Parametru pentru filtrare (pending, approved, rejected)
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """
    Returnează cererile de acces. 
    Dacă status nu este furnizat, le returnează pe toate (pentru istoric).
    """
    check_admin(admin_user)
    
    query = db.query(CerereEmailProfesor)
    
    if status:
        query = query.filter(CerereEmailProfesor.status == status)
    
    # Ordonăm după data cererii (cele mai noi primele)
    requests = query.order_by(CerereEmailProfesor.data_cerere.desc()).all()
    return requests

@router.post("/requests/approve/{request_id}")
async def approve_professor_request(
    request_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_user)
):
    """
    Aprobă o cerere de acces.
    Caută profesorul cu același nume/prenume care are email-ul NULL și îl actualizează.
    """
    check_admin(admin_user)

    # 1. Găsim cererea
    cerere = db.query(CerereEmailProfesor).filter(CerereEmailProfesor.id == request_id).first()
    if not cerere:
        raise HTTPException(status_code=404, detail="Cererea nu a fost găsită.")
    
    if cerere.status != "pending":
        raise HTTPException(status_code=400, detail="Cererea a fost deja procesată.")

    # 2. Căutăm profesorul corespunzător în tabela profesori
    # Condiții: Nume identic, Prenume identic și emailAddress este NULL
    profesor = db.query(Profesor).filter(
        func.lower(Profesor.lastName) == func.lower(cerere.lastName),
        func.lower(Profesor.firstName) == func.lower(cerere.firstName),
        Profesor.emailAddress == None
    ).first()

    if not profesor:
        # Marcăm cererea ca eșuată sau informăm adminul
        raise HTTPException(
            status_code=404, 
            detail="Nu s-a găsit niciun profesor potrivit fără email configurat."
        )

    # 3. Validăm dacă email-ul din cerere nu este deja folosit de alt profesor
    existing_email = db.query(Profesor).filter(Profesor.emailAddress == cerere.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email-ul din cerere este deja atribuit altui profesor.")

    try:
        # 4. Actualizăm email-ul profesorului
        # Această acțiune va declanșa automat sync_professor_to_user dacă profesorul are deja un User creat
        profesor.emailAddress = cerere.email

        # 5. Finalizăm cererea
        cerere.status = "approved"
        cerere.data_solutionare = datetime.now(timezone.utc)

        db.commit()
        return {"message": f"Cerere aprobată. Email-ul a fost atribuit profesorului {profesor.lastName}."}
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Eroare la procesare: {str(e)}")

@router.post("/requests/reject/{request_id}")
async def reject_professor_request(
    request_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_user)
):
    """Respinge o cerere de acces."""
    check_admin(admin_user)
    cerere = db.query(CerereEmailProfesor).filter(CerereEmailProfesor.id == request_id).first()
    
    if not cerere:
        raise HTTPException(status_code=404, detail="Cererea nu a fost găsită.")
    
    cerere.status = "rejected"
    cerere.data_solutionare = datetime.now(timezone.utc)
    db.commit()
    
    return {"message": "Cererea a fost respinsă."}

# --- RUTE SINCRONIZARE ORAR ---

@router.post("/sync/base")
async def sync_base_data(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    # Rulăm wrapper-ul care se ocupă de logare și execuția populate_base
    bg.add_task(run_sync_with_logging, populate_base, "Base")
    return {"message": "Sincronizare date de bază pornită."}

@router.post("/sync/calendar")
async def sync_calendar(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(run_sync_with_logging, populate_calendar, "Calendar")
    return {"message": "Sincronizare calendar pornită."}

@router.post("/sync/orar")
async def sync_orar(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(run_sync_with_logging, populate_orar, "Orar")
    return {"message": "Sincronizare orar pornită."}

@router.get("/sync/history", response_model=List[SyncHistoryResponse])
async def get_sync_history(
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """
    Returnează istoricul complet al sincronizărilor efectuate.
    Accesibil doar administratorilor.
    """
    check_admin(admin_user)
    
    # Preluăm istoricul ordonat după cele mai recente sincronizări
    history = db.query(IstoricSincronizare).order_by(IstoricSincronizare.data_start.desc()).all()
    
    return history

