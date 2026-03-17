# app\schemas\user.py
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import date, datetime
from app.models.models import UserRole
from typing import List

# Base Schema (common)
class UserBase(BaseModel):
    email: EmailStr
    first_name: str = Field(..., alias="firstName")
    last_name: str = Field(..., alias="lastName")
    role: UserRole = UserRole.STUDENT

    class Config:
        from_attributes = True
        use_enum_values = True
        populate_by_name = True

# Schema for Creation (sent from frontend)
class UserCreate(UserBase):
    pass

# Schema for Response (received by frontend)
class UserResponse(UserBase):
    id: int
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True  # Allows mapping SQLAlchemy objects

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class UserUpdate(BaseModel):
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    new_email: Optional[EmailStr] = None

class ProfessorUpdate(BaseModel):
    email_address: Optional[EmailStr] = Field(None, alias="emailAddress")
    last_name: Optional[str] = Field(None, alias="lastName")
    first_name: Optional[str] = Field(None, alias="firstName")
    position_short_name: Optional[str] = Field(None, alias="positionShortName")
    phd_short_name: Optional[str] = Field(None, alias="phdShortName")
    other_title: Optional[str] = Field(None, alias="otherTitle")

    class Config:
        populate_by_name = True

class ProfessorAccessRequestCreate(BaseModel):
    first_name: str = Field(..., alias="firstName")
    last_name: str = Field(..., alias="lastName")
    email: EmailStr

    class Config:
        populate_by_name = True

class SyncHistoryResponse(BaseModel):
    id: int
    sync_type: str = Field(..., alias="syncType")
    trigger_type: str = Field(..., alias="triggerType")
    start_date: datetime = Field(..., alias="startDate")
    end_date: Optional[datetime] = Field(None, alias="endDate")
    status: str
    error_message: Optional[str] = Field(None, alias="errorMessage")

    class Config:
        from_attributes = True
        populate_by_name = True

class AlternativeSlotRequest(BaseModel):
    selected_group_id: int = Field(..., alias="selectedGroupId", description="The student's subgroup ID")
    selected_subject: str = Field(..., alias="selectedSubject", min_length=1, description="The full name of the subject")
    selected_type: str = Field(..., alias="selectedType", description="Activity type: Seminar, Lab, or Project")
    attends_course: bool = Field(..., alias="attendsCourse", description="Whether the student wants to avoid overlap with lecture hours")

    class Config:
        populate_by_name = True

class FreeSlotRequest(BaseModel):
    email: EmailStr
    subject: str = Field(..., alias="subject")
    group_ids: List[int] = Field(..., alias="groupIds")
    room_ids: List[int] = Field(..., alias="roomIds")
    duration: int = Field(..., alias="duration")
    activity_type: str = Field(..., alias="activityType")
    number_of_people: Optional[int] = Field(None, alias="numberOfPeople")
    day: Optional[int] = Field(None, alias="day")
    weeks: List[int] = Field(..., alias="weeks")

    class Config:
        populate_by_name = True

class SlotReservationRequest(BaseModel):
    email: EmailStr
    room_id: int = Field(..., alias="roomId")
    group_ids: List[int] = Field(..., alias="groupIds")
    subject: str = Field(..., alias="subject")
    activity_type: str = Field(..., alias="activityType")
    day: int = Field(..., ge=1, le=6, description="1=Monday, 6=Saturday")
    week: int = Field(..., ge=1, le=14, alias="week")
    start_hour: int = Field(..., alias="startHour", ge=8, le=21)
    duration: int = Field(..., ge=1, le=6, alias="duration")
    reservation_date: date = Field(..., alias="reservationDate") 
    number_of_people: Optional[int] = Field(0, alias="numberOfPeople")

    class Config:
        populate_by_name = True
        from_attributes = True

class ReservationCancellationRequest(BaseModel):
    reservation_id: int = Field(..., alias="reservationId")
    email: str
    reason: Optional[str] = Field("Unspecified", alias="reason")

    class Config:
        populate_by_name = True

class WeeksRequest(BaseModel):
    group_ids: List[int] = Field(..., alias="groupIds")

    class Config:
        populate_by_name = True