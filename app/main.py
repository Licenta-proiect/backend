# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, admin, professors, subgroups, data, reservation
from app.db.session import SessionLocal
from app.models.models import SystemStatus
from app.services.scheduler import scheduled_sync_job, scheduler, scheduled_backup_job
from app.utils.config import settings

# Lifespan Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    db = SessionLocal()
    status = db.query(SystemStatus).first()
    db.close()
    
    if status:
        # Backup
        if status.backup_enabled:
            hour_b, min_b = status.backup_time.split(':')
            # We add the job with a unique ID to be able to manipulate it later if necessary
            scheduler.add_job(
                scheduled_backup_job, 
                'cron', 
                hour=hour_b, 
                minute=min_b, 
                id="daily_backup")
        
        # Sync 
        if status.auto_sync_enabled:
            hour_s, min_s = status.sync_time.split(':')
            
            scheduler.add_job(
                scheduled_sync_job, 
                'cron', 
                hour=hour_s, 
                minute=min_s, 
                id="scheduled_sync_task")
    
    scheduler.start()
    yield  # application runs
    
    # --- SHUTDOWN ---
    scheduler.shutdown()

app = FastAPI(
    title="USV Recovery Manager", 
    lifespan=lifespan 
)

# Session Middleware
app.add_middleware(SessionMiddleware, secret_key= settings.SECRET_KEY)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"{settings.FRONTEND_URL}"],  # Allows the frontend origin
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

