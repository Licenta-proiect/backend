# app/main.py
import os
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Header, status
from dotenv import load_dotenv

# Importăm funcțiile de populare din servicii
from app.services.scraper import populate as populate_base
from app.services.scraper_calendar import run as populate_calendar
from app.services.scraper_orar import populate as populate_orar

load_dotenv()

# Funcție de securitate (Dependency)
async def verify_admin(x_admin_token: str = Header(None)):
    admin_key = os.getenv("ADMIN_SECRET_KEY")
    if x_admin_token != admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acces neautorizat. Token admin invalid."
        )
    return x_admin_token

app = FastAPI(title="USV Recovery Manager")

# 1. Rută pentru datele de bază (Facultăți, Săli, Profesori)
@app.post("/admin/sync/base", dependencies=[Depends(verify_admin)])
async def sync_base_data(background_tasks: BackgroundTasks):
    background_tasks.add_task(populate_base)
    return {"message": "Sincronizarea datelor de bază a început în fundal."}

# 2. Rută pentru Calendarul Academic (Gemini API)
@app.post("/admin/sync/calendar", dependencies=[Depends(verify_admin)])
async def sync_calendar(background_tasks: BackgroundTasks):
    background_tasks.add_task(populate_calendar)
    return {"message": "Actualizarea calendarului academic prin AI a început."}

# 3. Rută pentru Orar (Proces de durată)
@app.post("/admin/sync/orar", dependencies=[Depends(verify_admin)])
async def sync_orar(background_tasks: BackgroundTasks):
    background_tasks.add_task(populate_orar)
    return {"message": "Descărcarea orarelor a început. Acest proces poate dura câteva minute."}

@app.get("/")
def root():
    return {"message": "Sistemul este online!"}