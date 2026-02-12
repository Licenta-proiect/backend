import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from fastapi import Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import User, UserRole

# Încărcare variabile din .env
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 ore

security = HTTPBearer()

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def create_access_token(data: dict):
    """Generează un token JWT semnat."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(request: Request, db: Session = Depends(get_db), auth: HTTPAuthorizationCredentials = Depends(security)):
    """
    Dependență pentru a extrage utilizatorul curent.
    Verifică token-ul din Header-ul Authorization: Bearer <token>
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
    """Gestionează logica de înregistrare/autentificare după callback-ul Google."""
    user = db.query(User).filter(User.email == user_info['email']).first()
    
    if not user:
        user = User(
            email=user_info['email'],
            firstName=user_info.get('given_name'),
            lastName=user_info.get('family_name'),
            role=UserRole.STUDENT.value
        )
        db.merge(user)
        db.commit()
        user = db.query(User).filter(User.email == user_info['email']).first()
    
    return user

