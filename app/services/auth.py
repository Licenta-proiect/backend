# app\services\auth.py
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from authlib.integrations.starlette_client import OAuth
import pyotp
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import User, UserRole, Professor
from app.services.scraper import clean_val
from app.utils.config import settings

# Load environment variables from .env
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

security = HTTPBearer()

oauth = OAuth()
oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def generate_otp_secret():
    return pyotp.random_base32()

def get_otp_verifier(secret: str):
    return pyotp.TOTP(secret, interval=300)

def create_access_token(data: dict):
    """Generates a signed JWT token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(request: Request, db: Session = Depends(get_db), auth: HTTPAuthorizationCredentials = Depends(security)):
    """
    Dependency to extract the current user.
    Verifies the token from the Authorization Header: Bearer <token>
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentificare necesară"
        )

    token = auth.credentials 
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Token invalid")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token-ul a expirat. Te rugăm să te loghezi din nou.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalid.")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utilizator inexistent")
    return user

async def handle_google_login(user_info: dict, db: Session):
    """Handles registration/authentication logic after the Google callback."""
    email = user_info['email']
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        # 1. Check if the user is a professor (email exists in professors table)
        professor_data = db.query(Professor).filter(
            Professor.email_address == email,
            Professor.has_schedule == True
        ).first()
        
        teacher_id = None
        if professor_data:
            new_role = UserRole.PROFESSOR.value
            teacher_id = professor_data.id  # Save ID to link it to the new User
        # 2. Check if the user is a student (domain matches @student.usv.ro)
        elif email.endswith("@student.usv.ro"):
            new_role = UserRole.STUDENT.value
        # 3. If neither, block access
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Doar studenții și profesorii de la FIESC cu orar activ pot accesa sistemul."
            )

        # Create the new user with teacher_id if found
        user = User(
            email=clean_val(email),
            first_name=clean_val(user_info.get('given_name')),
            last_name=clean_val(user_info.get('family_name')),
            role=new_role,
            teacher_id=teacher_id  # Automatic link established on first login
        )
        db.add(user)

    # Set the current login time for all users
    user.last_login = datetime.now(timezone.utc)

    db.commit()
    db.refresh(user)

    return user
