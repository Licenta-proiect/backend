# app\schemas\user.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.models.models import UserRole

# Schema de bază (comună)
class UserBase(BaseModel):
    email: EmailStr
    firstName: str
    lastName: str
    role: UserRole = UserRole.STUDENT

# Schema pentru Creare (ce trimiți din front)
class UserCreate(UserBase):
    pass

# Schema pentru Răspuns (ce primește front-ul)
class UserResponse(UserBase):
    id: int
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True # Permite maparea obiectelor SQLAlchemy

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse