# app\routers\admin.py
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.db.session import get_db
from app.services.auth import get_current_user
from app.models.models import User, UserRole, Profesor
from app.services.scraper import populate as populate_base
from app.services.scraper_calendar import run as populate_calendar
from app.services.scraper_orar import populate as populate_orar
from app.schemas.user import UserCreate, UserResponse, ProfesorUpdate

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

@router.post("/users/create", response_model=UserResponse)
async def create_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """Creează un utilizator nou folosind schema UserCreate cu un rol specific."""
    check_admin(admin_user)
    
    # Verificăm dacă user-ul există deja folosind user_in.email
    existing_user = db.query(User).filter(User.email == user_in.email).first() 
    if existing_user:
        raise HTTPException(status_code=400, detail="Email deja înregistrat.")
    
    # Mapăm datele din Pydantic către modelul SQLAlchemy
    new_user = User(
        lastName=user_in.lastName,
        firstName=user_in.firstName,
        email=user_in.email,
        role=user_in.role.value
    ) 
    
    db.add(new_user) 
    db.commit() 
    db.refresh(new_user)
    return new_user

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
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """Actualizează numele, prenumele sau ambele (email-ul și rolul rămân neschimbate)."""
    check_admin(admin_user)
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu a fost găsit.")
    
    if last_name is not None:
        user.lastName = last_name 
    
    if first_name is not None:
        user.firstName = first_name 
    
    db.commit()
    db.refresh(user)
    return user

# --- RUTE MANAGEMENT PROFESORI ---

@router.put("/profesori/update/{profesor_id}")
async def update_profesor(
    profesor_id: int,
    prof_data: ProfesorUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_user)
):
    """
    Actualizează detaliile unui profesor (nume, prenume, email, titluri).
    Accesibilă doar administratorilor.
    """
    check_admin(admin_user)

    # Căutăm profesorul în baza de date după ID
    profesor = db.query(Profesor).filter(Profesor.id == profesor_id).first()
    if not profesor:
        raise HTTPException(status_code=404, detail="Profesorul nu a fost găsit.")

    # Actualizăm doar câmpurile trimise în request (care nu sunt None)
    update_data = prof_data.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(profesor, key, value)

    db.commit()
    db.refresh(profesor)
    
    return profesor

# --- RUTE SINCRONIZARE ORAR ---

@router.post("/sync/base")
async def sync_base_data(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(populate_base)
    return {"message": "Sincronizare base pornită."}

@router.post("/sync/calendar")
async def sync_calendar(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(populate_calendar)
    return {"message": "Sincronizare calendar pornită."}

@router.post("/sync/orar")
async def sync_orar(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(populate_orar)
    return {"message": "Sincronizare orar pornită."}