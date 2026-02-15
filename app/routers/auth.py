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
from app.schemas.user import LoginResponse

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