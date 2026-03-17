# app/main.py
import os
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, admin, professors, subgroups, data, reservation

app = FastAPI(title="USV Recovery Manager")

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

