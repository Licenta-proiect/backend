# app\routers\auth.py
from typing import Annotated
from fastapi import APIRouter, Depends, Request, HTTPException, status
from datetime import datetime, timedelta, timezone
from fastapi.responses import RedirectResponse
import urllib.parse
from jose import jwt
import pyotp
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.auth import (
    ALGORITHM, SECRET_KEY, generate_otp_secret, get_passwordless_otp_verifier, oauth, create_access_token, handle_google_login, get_current_user, verify_passwordless_login
)
from app.schemas.user import OTPLoginVerify, OTPRequest, ProfessorAccessRequestCreate
from app.models.models import Professor, ProfessorEmailRequest, User, UserRole
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
async def auth_callback(request: Request, db: Annotated[Session, Depends(get_db)]):
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
async def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    """
    Returns current authenticated user details.
    """
    return {
        "id": current_user.id, 
        "email": current_user.email,
        "role": current_user.role  
    }

@router.post("/request-access", dependencies=[Depends(verify_system_available)])
async def request_professor_access(data: ProfessorAccessRequestCreate, db: Annotated[Session, Depends(get_db)]):
    """
    Allows a professor to request access if their email is missing.
    """
    # Check if a request already exists for this email with "pending" status
    existing_request = db.query(ProfessorEmailRequest).filter(
        ProfessorEmailRequest.email == data.email,
        ProfessorEmailRequest.status == "pending"
    ).first()

    if existing_request:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Există deja o cerere în curs pentru acest email.")

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
async def verify_2fa(data: dict, db: Annotated[Session, Depends(get_db)]):
    """
    Validates the OTP code and issues the final access token.
    """
    temp_token = data.get("temp_token")
    user_provided_code = data.get("code")
    
    try:
        # Decode and validate temporary token
        payload = jwt.decode(temp_token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("pending_2fa"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Acces neautorizat")
        
        user_email = payload.get("sub")
        user = db.query(User).filter(User.email == user_email).first()
        
        if not user or not user.otp_secret:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesiune invalidă")

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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cod incorect sau expirat")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesiunea de verificare a expirat")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalid")
    
@router.post("/auth/passwordless/request", dependencies=[Depends(verify_system_available)])
async def request_passwordless_code(data: OTPRequest, db: Annotated[Session, Depends(get_db)]):
    """
    Endpoint to request a passwordless magic code via email.
    Verifies domain and schedule eligibility constraints before dispatching the email.
    """
    email = data.email.lower().strip()
    
    # 1. Verify if the email is eligible (existing user, professor with active schedule, or admin)
    user_exists = db.query(User).filter(User.email == email).first()
    
    if not user_exists:
        is_professor = db.query(Professor).filter(
            Professor.email_address == email,
            Professor.has_schedule == True
        ).first()
        
        is_student = email.endswith("@student.usv.ro")
        is_admin = email == settings.ADMIN_EMAIL
        
        if not (is_professor or is_student or is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Doar studenții și profesorii de la FIESC cu orar activ pot accesa sistemul."
            )
            
    # 2. Generate the deterministic TOTP magic token valid for 5 minutes
    totp = get_passwordless_otp_verifier(email)
    otp_code = totp.now()
    
    # 3. Dispatch the email securely via SMTP
    email_sent = send_2fa_email(email, otp_code)
    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Eroare la trimiterea e-mailului de verificare. Încercați din nou."
        )
        
    return {"message": "Codul de verificare a fost trimis cu succes pe e-mail."}

@router.post("/auth/passwordless/verify", dependencies=[Depends(verify_system_available)])
async def verify_passwordless_code(payload: OTPLoginVerify, db: Annotated[Session, Depends(get_db)]):
    """
    Endpoint to verify the magic code and issue the final access JWT token.
    """
    email = payload.email.lower().strip()
    code = payload.code.strip()
    
    # Verify the incoming token and retrieve or register the validated user identity context
    user = await verify_passwordless_login(email, code, db)
    
    # Generate the standard 24-hour final JWT access token using the signature service
    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "role": user.role,
            "first_name": user.first_name,
            "last_name": user.last_name
        }
    }