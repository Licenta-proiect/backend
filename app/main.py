# app\main.py
import uvicorn
import os
from fastapi import FastAPI
from app.db.session import engine, Base
from app.models.models import (
    Facultate, Profesor, Sala, Subgrupa, 
    Orar, User, Rezervare, SistemStatus, CalendarUniversitar
)

app = FastAPI(title="USV Recovery Manager")

@app.get("/")
def root():
    return {"message": "Sistemul este online!"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000)) # Ia 3000 din env, sau 8000 default
    uvicorn.run("app.main:app", host="localhost", port=port, reload=True)