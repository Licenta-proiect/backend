# app\routers\admin.py
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone
from app.db.session import get_db
from app.schemas.sync import SyncSettingsUpdate
from app.services.auth import get_current_user
from app.models.models import User, UserRole, Professor, SyncHistory, ProfessorEmailRequest, SystemStatus
from app.services.reservation import get_all_reservations_admin
from app.services.scraper import clean_val, populate as populate_base
from app.services.calendar_scraper import run as populate_calendar
from app.services.schedule_scraper import populate as populate_orar
from app.schemas.user import UserCreate, UserResponse, UserUpdate, SyncHistoryResponse
from app.services.sync_logger import run_sync_with_logging
from app.services.backup import execute_db_backup

router = APIRouter(prefix="/admin", tags=["Admin"])

def check_admin(user: User):
    """Verifies if the user has an administrator role."""
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

async def sync_base_and_schedule_logic():
    """Executes base data population followed by schedule population sequentially."""
    await populate_base()
    await populate_orar()

# --- USER MANAGEMENT ROUTES ---
@router.get("/users", response_model=List[UserResponse])
async def get_all_users(
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """Retrieves all users from the database."""
    check_admin(admin_user)
    users = db.query(User).all() 
    return users

@router.post("/users/create")
async def create_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """Creates a new user and links them to the professors table if applicable."""
    check_admin(admin_user)
    
    # 1. Check if the user already exists in the users table
    existing_user = db.query(User).filter(User.email == user_in.email).first() 
    if existing_user:
        raise HTTPException(status_code=400, detail="Email deja înregistrat.")
    
    # 2. Initialize new user
    new_user = User(
        last_name=clean_val(user_in.last_name),
        first_name=clean_val(user_in.first_name),
        email=clean_val(user_in.email),
        role=clean_val(user_in.role)
    ) 
    
    # 3. If the role is PROFESSOR, look for a match in the professors table
    if user_in.role == UserRole.PROFESSOR:
        # Search for professor by email
        professor = db.query(Professor).filter(Professor.email_address == user_in.email).first()
        
        if professor:
            # Link via ID
            new_user.teacher_id = professor.id
        else:
            # If the professor is not in the schedule database, we refuse creation
            raise HTTPException(
                status_code=404, 
                detail="Acest email nu a fost găsit în lista oficială de profesori (orar)."
            )

    db.add(new_user) 
    try:
        db.commit() 
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Eroare la salvarea în baza de date.")

    return {"message": f"Utilizatorul {user_in.first_name} {user_in.last_name} a fost creat cu succes sub rolul de {user_in.role}."}

@router.delete("/users/delete/{email}")
async def delete_user(
    email: str, 
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """Deletes a user by email, with protection for the main administrator."""
    check_admin(admin_user)
    
    user_to_delete = db.query(User).filter(User.email == email).first() 
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="Utilizatorul nu a fost găsit.")
    
    # Check if the target user is the main admin (ID 1)
    if user_to_delete.id == 1:
        raise HTTPException(
            status_code=403, 
            detail="Administratorul principal al sistemului nu poate fi șters."
        )
    
    # Prevent an admin from deleting themselves
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
    update_data: UserUpdate,
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """
    Updates user data with protection for the main admin and self-modification.
    """
    check_admin(admin_user)
    
    # Search for user by current email
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu a fost găsit.")
    
    # --- PROTECTION LOGIC ---
    
    # Check if email modification is attempted
    if update_data.new_email is not None and update_data.new_email != email:
        
        # 1. Main Admin Protection (ID 1)
        if user.id == 1:
            raise HTTPException(
                status_code=403, 
                detail="Email-ul administratorului principal nu poate fi modificat din motive de securitate."
            )
        
        # 2. Self-Modification Protection
        if user.id == admin_user.id:
            raise HTTPException(
                status_code=400, 
                detail="Nu îți poți modifica propriul email din această interfață (ar duce la deconectare imediată)."
            )

    # 1. Update name/surname
    if update_data.last_name is not None:
        user.last_name = clean_val(update_data.last_name) 
    if update_data.first_name is not None:
        user.first_name = clean_val(update_data.first_name)

    # 2. Update Email with Manual Sync
    if update_data.new_email is not None and update_data.new_email != email:
        # Check if the new email is already used by someone else
        email_taken = db.query(User).filter(User.email == update_data.new_email).first()
        if email_taken:
            raise HTTPException(status_code=400, detail="Noul email este deja înregistrat.")
        
        # Manual sync in the Professors table
        if user.professor_info:
            user.professor_info.email_address = clean_val(update_data.new_email)
        
        # Update the primary email
        user.email = clean_val(update_data.new_email)

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Eroare la salvare: {str(e)}")

    return user

# --- PROFESSOR ACCESS REQUEST MANAGEMENT --- 

@router.get("/requests")
async def get_professor_requests(
    status: Optional[str] = None, # Filtering parameter (pending, approved, rejected)
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """
    Returns access requests. 
    If status is not provided, returns all (for history).
    """
    check_admin(admin_user)
    
    query = db.query(ProfessorEmailRequest)
    
    if status:
        query = query.filter(ProfessorEmailRequest.status == status)
    
    # Order by request date (newest first)
    requests = query.order_by(ProfessorEmailRequest.request_date.desc()).all()
    return requests

@router.post("/requests/approve/{request_id}")
async def approve_professor_request(
    request_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_user)
):
    """
    Approves an access request.
    Finds the professor with the same name who has a NULL email and updates it.
    If validation fails, the request is automatically marked as rejected.
    """
    check_admin(admin_user)

    # 1. Find the request
    request_obj = db.query(ProfessorEmailRequest).filter(ProfessorEmailRequest.id == request_id).first()
    if not request_obj:
        raise HTTPException(status_code=404, detail="Cererea nu a fost găsită.")
    
    if request_obj.status != "pending":
        raise HTTPException(status_code=400, detail="Cererea a fost deja procesată.")

    # 2. Search for the corresponding professor
    professor = db.query(Professor).filter(
        func.lower(Professor.last_name) == func.lower(request_obj.last_name),
        func.lower(Professor.first_name) == func.lower(request_obj.first_name),
        Professor.email_address == None
    ).first()

    if not professor:
        request_obj.status = "rejected"
        request_obj.resolution_date = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=404,
            detail="Nu s-a găsit niciun profesor potrivit fără email. Cererea a fost respinsă automat."
        )

    # 3. Validate if the email in the request is already in use
    existing_email = db.query(Professor).filter(Professor.email_address == request_obj.email).first()
    if existing_email:
        request_obj.status = "rejected"
        request_obj.resolution_date = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Email-ul este deja atribuit altui profesor. Cererea a fost respinsă automat."
        )

    try:
        # 4. Update professor email
        professor.email_address = clean_val(request_obj.email)

        # 5. Finalize the request with success
        request_obj.status = "approved"
        request_obj.resolution_date = datetime.now(timezone.utc)

        db.commit()
        return {"message": f"Cerere aprobată pentru {professor.last_name}."}
    
    except Exception as e:
        db.rollback()
        try:
            request_obj.status = "rejected"
            request_obj.resolution_date = datetime.now(timezone.utc)
            db.commit()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Eroare la procesare: {str(e)}")

@router.post("/requests/reject/{request_id}")
async def reject_professor_request(
    request_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_user)
):
    """Rejects an access request."""
    check_admin(admin_user)
    
    request_obj = db.query(ProfessorEmailRequest).filter(ProfessorEmailRequest.id == request_id).first()
    
    if not request_obj:
        raise HTTPException(status_code=404, detail="Cererea nu a fost găsită.")
    
    if request_obj.status != "pending":
        raise HTTPException(
            status_code=400, 
            detail=f"Cererea are deja statusul: {request_obj.status}."
        )

    try:
        request_obj.status = "rejected"
        request_obj.resolution_date = datetime.now(timezone.utc)
        
        db.commit()
        return {"message": "Cererea a fost respinsă cu succes."}
        
    except Exception as e:
        db.rollback()
        try:
            request_obj.status = "rejected"
            db.commit()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Eroare la respingerea cererii: {str(e)}")

# --- SCHEDULE SYNC ROUTES ---

@router.post("/sync/base")
async def sync_base_data(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(run_sync_with_logging, populate_base, "Base")
    return {"message": "Sincronizare date de bază pornită."}

@router.post("/sync/calendar")
async def sync_calendar(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)

    print("Initiating preventive backup...")
    backup_file = execute_db_backup()
    if not backup_file:
         raise HTTPException(status_code=500, detail="Backup-ul a eșuat. Sincronizarea a fost oprită pentru siguranță.")

    bg.add_task(run_sync_with_logging, populate_calendar, "Calendar")
    return {"message": "Sincronizare calendar pornită."}

@router.post("/sync/schedule")
async def sync_schedule(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)

    print("Initiating preventive backup...")
    backup_file = execute_db_backup()
    if not backup_file:
         raise HTTPException(status_code=500, detail="Backup-ul a eșuat. Sincronizarea a fost oprită pentru siguranță.")

    bg.add_task(run_sync_with_logging, populate_orar, "Schedule")
    return {"message": "Sincronizare orar pornită."}

@router.post("/sync/base-schedule")
async def sync_full_db_schedule(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    """
    Combined route that syncs base data followed immediately by the Schedule.
    """
    check_admin(user)

    print("Initiating preventive backup...")
    backup_file = execute_db_backup()
    if not backup_file:
         raise HTTPException(status_code=500, detail="Backup-ul a eșuat. Sincronizarea a fost oprită pentru siguranță.")

    bg.add_task(run_sync_with_logging, sync_base_and_schedule_logic, "Base + Schedule")
    return {"message": "Sincronizarea combinată (Bază + Orar) a pornit în fundal."}

@router.get("/sync/history", response_model=List[SyncHistoryResponse])
async def get_sync_history(
    db: Session = Depends(get_db), 
    admin_user: User = Depends(get_current_user)
):
    """
    Returns the complete synchronization history.
    Accessible only to administrators.
    """
    check_admin(admin_user)
    
    history = db.query(SyncHistory).order_by(SyncHistory.start_date.desc()).all()
    
    return history

@router.get("/sync/settings")
async def get_sync_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Returns the current configuration for automatic synchronization."""
    check_admin(user)
    status_obj = db.query(SystemStatus).first()
    return status_obj

@router.post("/sync/settings")
async def update_sync_settings(
    settings: SyncSettingsUpdate, 
    db: Session = Depends(get_db), 
    user: User = Depends(get_current_user)
):
    """Updates how the system executes automatic synchronizations."""
    check_admin(user)
    status_obj = db.query(SystemStatus).first()
    
    if not status_obj:
        status_obj = SystemStatus()
        db.add(status_obj)
    
    status_obj.auto_sync_enabled = settings.auto_sync_enabled
    status_obj.sync_interval = settings.sync_interval
    status_obj.sync_time = settings.sync_time
    
    db.commit()
    return {"message": "Setări de sincronizare actualizate cu succes."}

# --- RESERVATION ROUTES ---

@router.get("/reservations")
def get_all_reservations(db: Session = Depends(get_db)):
    """
    Admin route that returns the global history of all reservations.
    """
    return get_all_reservations_admin(db)