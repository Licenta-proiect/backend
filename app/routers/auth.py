# app\routers\auth.py
from fastapi import APIRouter, Depends, Request, HTTPException
from datetime import datetime, timedelta, timezone
from fastapi.responses import RedirectResponse
import urllib.parse
from jose import jwt
import pyotp
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.auth import (
    ALGORITHM, SECRET_KEY, generate_otp_secret, oauth, create_access_token, handle_google_login, get_current_user
)

from app.schemas.user import ProfessorAccessRequestCreate
from app.models.models import ProfessorEmailRequest, User, UserRole
from app.services.email import send_2fa_email
from app.services.scraper import clean_val
from app.utils.config import settings
from app.utils.maintenance import verify_system_available

router = APIRouter(tags=["Authentication"])

@router.get("/login", dependencies=[Depends(verify_system_available)])
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
    """
    Clears the OAuth session data.
    """
    request.session.clear() 
    return {"message": "Logged out successfully"}

@router.get("/auth/callback", dependencies=[Depends(verify_system_available)])
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    """
    Handles the redirect from Google OAuth and initiates 2FA if necessary.
    """
    try:
        # Fetch token from Google
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')
        user = await handle_google_login(user_info, db)
        
        # 2FA Logic for Admin and Professor roles
        if user.role in [UserRole.ADMIN.value, UserRole.PROFESSOR.value]:
            if not user.otp_secret:
                user.otp_secret = generate_otp_secret()
                db.commit()
            
            # Generate current OTP code
            totp = pyotp.TOTP(user.otp_secret, interval=300)
            otp_code = totp.now()
            
            # Dispatch the email
            send_2fa_email(user.email, otp_code)

            now_timestamp = int(datetime.now(timezone.utc).timestamp())

            temp_token = jwt.encode(
                {
                    "sub": user.email, 
                    "pending_2fa": True, 
                    "iat_2fa": now_timestamp, # "Issued At" pentru 2FA
                    "exp": datetime.now(timezone.utc) + timedelta(minutes=10)
                },
                SECRET_KEY, 
                algorithm=ALGORITHM
            )
            
            # Build the frontend redirect URL for verification
            frontend_base = settings.FRONTEND_URL.rstrip('/')
            target_url = f"{frontend_base}/verify-2fa?temp_token={temp_token}"
            
            return RedirectResponse(url=target_url)

        # Standard flow for Students
        access_token = create_access_token(data={"sub": user.email})
        frontend_url = f"{settings.FRONTEND_URL}/callback"
        params = {
            "access_token": access_token,
            "role": user.role,
            "email": user.email,
            "firstName": user.first_name,
            "lastName": user.last_name
        }
        return RedirectResponse(url=f"{frontend_url}?{urllib.parse.urlencode(params)}") 

    except Exception as error:
        print(f"Auth Callback Error: {str(error)}")
        error_msg = urllib.parse.quote("Eroare la autentificare. Încercați din nou.")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth-error?message={error_msg}")
    
@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Returns current authenticated user details.
    """
    return {
        "id": current_user.id, 
        "email": current_user.email,
        "role": current_user.role  
    }

@router.post("/request-access", dependencies=[Depends(verify_system_available)])
async def request_professor_access(data: ProfessorAccessRequestCreate, db: Session = Depends(get_db)):
    """
    Allows a professor to request access if their email is missing.
    """
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

@router.post("/auth/verify-2fa", dependencies=[Depends(verify_system_available)])
async def verify_2fa(data: dict, db: Session = Depends(get_db)):
    """
    Validates the OTP code and issues the final access token.
    """
    temp_token = data.get("temp_token")
    user_provided_code = data.get("code")
    
    try:
        # Decode and validate temporary token
        payload = jwt.decode(temp_token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("pending_2fa"):
            raise HTTPException(status_code=401, detail="Acces neautorizat")
        
        user_email = payload.get("sub")
        user = db.query(User).filter(User.email == user_email).first()
        
        if not user or not user.otp_secret:
            raise HTTPException(status_code=401, detail="Sesiune invalidă")

        # Verify OTP code
        totp = pyotp.TOTP(user.otp_secret, interval=300)
        if totp.verify(user_provided_code):
            # Code is valid -> Issue final JWT
            final_access_token = create_access_token(data={"sub": user.email})
            return {
                "access_token": final_access_token,
                "role": user.role,
                "firstName": user.first_name,
                "lastName": user.last_name,
                "email": user.email
            }
        else:
            raise HTTPException(status_code=400, detail="Cod incorect sau expirat")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesiunea de verificare a expirat")
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalid")