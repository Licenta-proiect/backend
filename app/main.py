# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, admin, professors, subgroups, data, reservation
from app.db.session import Base, SessionLocal, engine
from app.models.models import SystemStatus
from app.services.scheduler import scheduled_sync_job, scheduler, scheduled_backup_job
from app.utils.config import settings

Base.metadata.create_all(bind=engine)

# Lifespan Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    db = SessionLocal()
    try:
        status = db.query(SystemStatus).first()
        
        if status:
            # Backup Job Registration
            if status.backup_enabled:
                try:
                    hour_b, min_b = status.backup_time.split(':')
                    scheduler.add_job(
                        scheduled_backup_job, 
                        'cron', 
                        hour=hour_b, 
                        minute=min_b, 
                        id="daily_backup"
                    )
                    print(f"INFO: Backup job scheduled at {status.backup_time}")
                except ValueError:
                    print("ERROR: Invalid backup_time format in database.")

            # Sync Job Registration
            if status.auto_sync_enabled:
                try:
                    hour_s, min_s = status.sync_time.split(':')
                    scheduler.add_job(
                        scheduled_sync_job, 
                        'cron', 
                        hour=hour_s, 
                        minute=min_s, 
                        id="scheduled_sync_task"
                    )
                    print(f"INFO: Sync job scheduled at {status.sync_time}")
                except ValueError:
                    print("ERROR: Invalid sync_time format in database.")
    except Exception as e:
        print(f"CRITICAL: Could not initialize scheduler from DB: {e}")
    finally:
        db.close()
    
    if not scheduler.running:
        scheduler.start()
        
    yield 
    
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

