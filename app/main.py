# app/main.py
from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, admin, professors, subgroups, data, reservation
from app.db.session import SessionLocal
from app.models.models import SystemStatus
from app.services.scheduler import scheduler, scheduled_backup_job

# Lifespan Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    db = SessionLocal()
    status = db.query(SystemStatus).first()
    db.close()
    
    if status:
        hour, minute = status.backup_time.split(':')
        # We add the job with a unique ID to be able to manipulate it later if necessary
        scheduler.add_job(
            scheduled_backup_job, 
            'cron', 
            hour=hour, 
            minute=minute, 
            id="daily_backup")
    
    scheduler.start()
    yield  # application runs
    
    # --- SHUTDOWN ---
    scheduler.shutdown()

app = FastAPI(
    title="USV Recovery Manager", 
    lifespan=lifespan 
)

# Session Middleware
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"{os.getenv('FRONTEND_URL')}"],  # Allows the frontend origin
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

# --- AUTHENTICATION ROUTES ---
app.include_router(auth.router)

# --- ADMIN ROUTES ---
app.include_router(admin.router)

# --- PROFESSORS ROUTES ---
app.include_router(professors.router)

# --- SUBGROUPS ROUTES ---
app.include_router(subgroups.router)

# --- DATA ROUTES ---
app.include_router(data.router)

# --- RESERVATION ROUTES ---
app.include_router(reservation.router)

@app.get("/")
def root():
    return {"message": "Sistemul este online!"}

