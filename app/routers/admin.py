# app\routers\admin.py
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from app.services.auth import get_current_user
from app.models.models import User
from app.services.scraper import populate as populate_base
from app.services.scraper_calendar import run as populate_calendar
from app.services.scraper_orar import populate as populate_orar

router = APIRouter(prefix="/admin", tags=["Admin"])

def check_admin(user: User):
    """Verifică dacă utilizatorul are rol de administrator."""
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Acces interzis. Necesar Admin.")

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