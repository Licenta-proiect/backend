# app\schemas\user.py
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import date, datetime
from app.models.models import UserRole
from typing import List

# Schema de bază (comună)
class UserBase(BaseModel):
    email: EmailStr
    firstName: str
    lastName: str
    role: UserRole = UserRole.STUDENT

    class Config:
        from_attributes = True
        use_enum_values = True

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

class UserUpdate(BaseModel):
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    new_email: Optional[EmailStr] = None

class ProfesorUpdate(BaseModel):
    emailAddress: Optional[EmailStr] = None
    lastName: Optional[str] = None
    firstName: Optional[str] = None
    positionShortName: Optional[str] = None
    phdShortName: Optional[str] = None
    otherTitle: Optional[str] = None

class ProfessorAccessRequestCreate(BaseModel):
    firstName: str
    lastName: str
    email: EmailStr

class SyncHistoryResponse(BaseModel):
    id: int
    tip_sincronizare: str
    tip_declansare: str
    data_start: datetime
    data_final: Optional[datetime] = None
    status: str
    mesaj_eroare: Optional[str] = None

    class Config:
        from_attributes = True

class SlotAlternativRequest(BaseModel):
    selected_group_id: int = Field(..., alias="selectedGroupId", description="ID-ul subgrupei studentului")
    selected_subject: str = Field(..., alias="selectedSubject", min_length=1, description="Numele complet al materiei")
    selected_type: str = Field(..., alias="selectedType", description="Tipul activitatii: Seminar, Laborator sau Proiect")
    attends_course: bool = Field(..., alias="attendsCourse", description="Daca studentul doreste sa evite suprapunerea cu orele de curs")

    class Config:
        # Permite folosirea numelor atat in format camelCase (din frontend) 
        # cat si snake_case (in codul Python)
        populate_by_name = True

class SlotLiberRequest(BaseModel):
    email: EmailStr
    materie: str
    grupe_ids: List[int]
    sali_ids: List[int]
    durata: int
    tip_activitate: str
    numar_persoane: Optional[int] = None
    zi: Optional[int] = None
    saptamani: List[int]

    class Config:
        populate_by_name = True

class RezervareSlotRequest(BaseModel):
    email: EmailStr
    sala_id: int = Field(..., alias="salaId")
    grupe_ids: List[int] = Field(..., alias="grupeIds")
    materie: str
    tip_activitate: str = Field(..., alias="tipActivitate")
    zi: int = Field(..., ge=1, le=6, description="1=Luni, 6=Sambata")
    saptamana: int = Field(..., ge=1, le=14)
    ora_start: int = Field(..., alias="oraStart", ge=480, le=1320)
    durata: int = Field(..., ge=1, le=6)
    data_rezervare: date = Field(..., alias="data") 
    numar_persoane: Optional[int] = Field(0, alias="numarPersoane")

    class Config:
        populate_by_name = True
        from_attributes = True