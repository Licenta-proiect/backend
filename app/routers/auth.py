# app\routers\auth.py
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
import urllib.parse
import os
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.auth import (
    oauth, create_access_token, handle_google_login, get_current_user
)

from app.schemas.user import LoginResponse, ProfessorAccessRequestCreate
from app.models.models import ProfessorEmailRequest, User
from app.services.scraper import clean_val

router = APIRouter(tags=["Authentication"])

@router.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    
    # Force Google to display the account selection window
    return await oauth.google.authorize_redirect(
        request, 
        redirect_uri,
        prompt="select_account" 
    )

@router.get("/logout")
async def logout(request: Request):
    request.session.clear() # Clears temporary OAuth2 session data
    return {"message": "Logged out successfully"}

@router.get("/auth/callback", response_model=LoginResponse) 
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')

        # This function throws HTTPException(403) if the user does not have access
        user = await handle_google_login(user_info, db)
        
        access_token = create_access_token(data={"sub": user.email})
        
        # Build the frontend URL (e.g., localhost:3000/callback)
        # Add necessary data to query parameters
        frontend_url = f"{os.getenv('FRONTEND_URL')}/callback"
        params = {
            "access_token": access_token,
            "role": user.role,
            "email": user.email,
            "firstName": user.first_name,
            "lastName": user.last_name
        }
        
        query_string = urllib.parse.urlencode(params)
        return RedirectResponse(url=f"{frontend_url}?{query_string}") 
    
    except HTTPException as e:
        # If it's 403 or another business error, send the message to the UI
        error_msg = urllib.parse.quote(e.detail)
        return RedirectResponse(url=f"{os.getenv('FRONTEND_URL')}/auth-error?message={error_msg}")
    
    except Exception:
        raise HTTPException(status_code=400, detail="Eroare comunicare Google")

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}

@router.post("/request-access")
async def request_professor_access(data: ProfessorAccessRequestCreate, db: Session = Depends(get_db)):
    '''
    Request from a professor to the administrator to update their email in the database.
    '''
    # Check if a request already exists for this email with "pending" status
    existing_request = db.query(ProfessorEmailRequest).filter(
        ProfessorEmailRequest.email == data.email,
        ProfessorEmailRequest.status == "pending"
    ).first()

    if existing_request:
        raise HTTPException(status_code=400, detail="Există deja o cerere în curs pentru acest email.")

    new_request = ProfessorEmailRequest(
        first_name=clean_val(data.first_name),
        last_name=clean_val(data.last_name),
        email=clean_val(data.email)
    )
    
    db.add(new_request)
    db.commit()
    db.refresh(new_request)
    
    return {"message": "Cererea a fost trimisă cu succes!"}