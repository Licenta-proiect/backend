# app\services\auth.py
import base64
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

def get_or_create_user_identity(email: str, db: Session, default_first: str = None, default_last: str = None) -> User:
    """
    Shared internal helper to evaluate system eligibility constraints,
    map academic roles, and get or create a database User record.
    """
    email = clean_val(email.lower().strip())
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

        # Fallback parsing strategy from email strings if defaults aren't provided
        final_first = default_first or email.split('.')[0].capitalize()
        final_last = default_last or email.split('@')[0].split('.')[-1].capitalize()

        # Provision the brand new synchronized User entity
        user = User(
            email=email,
            first_name=clean_val(final_first),
            last_name=clean_val(final_last),
            role=new_role,
            teacher_id=teacher_id
        )
        db.add(user)
        
    return user

async def handle_google_login(user_info: dict, db: Session):
    """Handles registration/authentication logic after the Google callback."""
    email = user_info['email']
    
    # Delegate identity resolution logic to the shared core helper
    user = get_or_create_user_identity(
        email=email,
        db=db,
        default_first=user_info.get('given_name'),
        default_last=user_info.get('family_name')
    )

    # Set the current login time for all users
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    return user

def get_passwordless_otp_verifier(email: str):
    """
    Generates a deterministic TOTP secret based on the user's email address.
    This eliminates the need to persist and fetch temporary OTP secrets in the database.
    The generated token is valid for 5 minutes (interval=300 seconds).
    """
    encoded_bytes = base64.b32encode(email.encode('utf-8'))
    
    # Decode bytes back to a string and strip padding characters '=' for pyotp compatibility
    secret_b32 = encoded_bytes.decode('utf-8').replace('=', '')[:32]
    
    # Pad the string with a trailing 'A' fallback if the generated length is under 32 characters
    if len(secret_b32) < 32:
        secret_b32 = secret_b32.ljust(32, 'A')
        
    return pyotp.TOTP(secret_b32, interval=300)

async def verify_passwordless_login(email: str, code: str, db: Session) -> User:
    """
    Validates the temporary TOTP magic code and handles user authentication/provisioning.
    """
    totp = get_passwordless_otp_verifier(email)
    
    # Enforce safe verification of numeric TOTP tokens
    if not totp.verify(code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Codul de verificare este incorect sau a expirat."
        )
    
    # Delegate identity resolution logic to the shared core helper
    user = get_or_create_user_identity(email=email, db=db)
        
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    
    return user