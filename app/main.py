# app/main.py
import os
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, admin, profesori

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
app.include_router(auth.router)

# --- RUTE ADMIN ---
app.include_router(admin.router)

# --- RUTE PROFESORI ---
app.include_router(profesori.router)

@app.get("/")
def root():
    return {"message": "Sistemul este online!"}

