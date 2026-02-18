# app\routers\auth.py
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
import urllib.parse
import os
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.auth import (
    oauth, create_access_token, handle_google_login
)

from app.schemas.user import LoginResponse, ProfessorAccessRequestCreate
from app.models.models import CerereEmailProfesor

router = APIRouter(tags=["Autentificare"])

@router.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    
    # Forțăm Google să afișeze fereastra de selecție a contului
    return await oauth.google.authorize_redirect(
        request, 
        redirect_uri,
        prompt="select_account" 
    )

@router.get("/logout")
async def logout(request: Request):
    request.session.clear() # Șterge datele temporare OAuth2
    return {"message": "Logged out successfully"}

@router.get("/auth/callback", response_model=LoginResponse) 
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')
    except Exception:
        raise HTTPException(status_code=400, detail="Eroare comunicare Google")

    user = await handle_google_login(user_info, db)
    
    access_token = create_access_token(data={"sub": user.email})
    
    # Construim URL-ul de frontend (localhost:3000/callback)
    # Adăugăm datele necesare în query parameters
    frontend_url = os.getenv("FRONTEND_URL_CALLBACK")
    params = {
        "access_token": access_token,
        "role": user.role,
        "email": user.email,
        "firstName": user.firstName,
        "lastName": user.lastName
    }
    
    query_string = urllib.parse.urlencode(params)
    return RedirectResponse(url=f"{frontend_url}?{query_string}")

@router.post("/request-access")
async def request_professor_access(data: ProfessorAccessRequestCreate, db: Session = Depends(get_db)):
    '''
    Cerere de la profesor către administrator pentru a i se actualiza email-ul în baza de date.
    '''
    # Verificăm dacă există deja o cerere pentru acest email cu status "In asteptare"
    existing_request = db.query(CerereEmailProfesor).filter(
        CerereEmailProfesor.email == data.email,
        CerereEmailProfesor.status == "pending"
    ).first()

    if existing_request:
        raise HTTPException(status_code=400, detail="Există deja o cerere în curs pentru acest email.")

    new_request = CerereEmailProfesor(
        firstName=data.firstName,
        lastName=data.lastName,
        email=data.email
    )
    
    db.add(new_request)
    db.commit()
    db.refresh(new_request)
    
    return {"message": "Cererea a fost trimisă cu succes!"}