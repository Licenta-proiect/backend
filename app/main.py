# app/main.py
import os
from fastapi import FastAPI, BackgroundTasks, Depends, Request, HTTPException
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.db.session import get_db

from app.models.models import User
from app.services.auth import (
    oauth, create_access_token, get_current_user, 
    handle_google_login, security
)
from app.services.scraper import populate as populate_base
from app.services.scraper_calendar import run as populate_calendar
from app.services.scraper_orar import populate as populate_orar

app = FastAPI(title="USV Recovery Manager")

# Middleware pentru Sesiuni
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))

# Middleware pentru CORS 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite orice sursă (pentru dezvoltare)
    allow_credentials=True,
    allow_methods=["*"],  # Permite toate metodele (GET, POST, etc.)
    allow_headers=["*"],  # Permite toți header-ii
)

# --- RUTE AUTENTIFICARE ---
@app.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    
    # Forțăm Google să afișeze fereastra de selecție a contului
    return await oauth.google.authorize_redirect(
        request, 
        redirect_uri,
        prompt="select_account" 
    )

@app.get("/logout")
async def logout(request: Request):
    request.session.clear() # Șterge datele temporare OAuth2
    return {"message": "Logged out successfully"}

@app.get("/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')
    except Exception:
        raise HTTPException(status_code=400, detail="Eroare comunicare Google")

    # Apelăm funcția simplificată din service
    user = await handle_google_login(user_info, db)
    
    return {
        "access_token": create_access_token(data={"sub": user.email}),
        "token_type": "bearer",
        "user": user # FastAPI va converti automat obiectul User în JSON
    }

# --- RUTE ADMIN ---
def check_admin(user: User):
    """Verifică dacă utilizatorul are rol de administrator."""
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Acces interzis. Necesar Admin.")

@app.post("/admin/sync/base")
async def sync_base_data(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(populate_base)
    return {"message": "Sincronizare base pornită."}

@app.post("/admin/sync/calendar")
async def sync_calendar(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(populate_calendar)
    return {"message": "Sincronizare calendar pornită."}

@app.post("/admin/sync/orar")
async def sync_orar(bg: BackgroundTasks, user: User = Depends(get_current_user)):
    check_admin(user)
    bg.add_task(populate_orar)
    return {"message": "Sincronizare orar pornită."}

@app.get("/")
def root():
    return {"message": "Sistemul este online!"}