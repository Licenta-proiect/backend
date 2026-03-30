# app\models\models.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Date, Table, event
from sqlalchemy.orm import relationship
from app.db.session import Base, SessionLocal
from datetime import datetime, timezone
import enum

class UserRole(enum.Enum):
    ADMIN = "ADMIN"
    STUDENT = "STUDENT"
    PROFESSOR = "PROFESSOR"

# --- JUNCTION TABLES ---
reservations_subgroups = Table(
    "reservations_subgroups",
    Base.metadata,
    Column("reservation_id", Integer, ForeignKey("reservations.id"), primary_key=True),
    Column("subgroup_id", Integer, ForeignKey("subgroups.id"), primary_key=True),
)

reservations_professors = Table(
    "reservations_professors",
    Base.metadata,
    Column("reservation_id", Integer, ForeignKey("reservations.id"), primary_key=True),
    Column("professor_id", Integer, ForeignKey("professors.id"), primary_key=True),
)

# --- MAIN MODELS ---

class Faculty(Base):
    __tablename__ = "faculties"
    id = Column(Integer, primary_key=True)
    short_name = Column(String)
    long_name = Column(String)
    subgroups = relationship("Subgroup", back_populates="faculty")
    professors = relationship("Professor", back_populates="faculty")

class Professor(Base):
    __tablename__ = "professors"
    id = Column(Integer, primary_key=True)
    last_name = Column(String)
    first_name = Column(String)
    position_short_name = Column(String)
    phd_short_name = Column(String)
    other_title = Column(String)
    email_address = Column(String, index=True, nullable=True)
    faculty_id = Column(Integer, ForeignKey("faculties.id"), nullable=True)
    department_name = Column(String)
    has_schedule = Column(Boolean, default=False)

    # Relation to User model
    user_account = relationship("User", back_populates="professor_info", uselist=False)

    faculty = relationship("Faculty", back_populates="professors")
    schedule = relationship("Schedule", back_populates="professor")
    main_reservations = relationship("Reservation", back_populates="main_professor")
    participating_events = relationship("Reservation", secondary=reservations_professors, back_populates="additional_professors")

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    short_name = Column(String)
    building_name = Column(String)
    capacity = Column(Integer)
    computers = Column(Integer)
    has_schedule = Column(Boolean, default=False)

    schedule = relationship("Schedule", back_populates="room")
    reservations = relationship("Reservation", back_populates="room")

class Subgroup(Base):
    __tablename__ = "subgroups"
    id = Column(Integer, primary_key=True)
    type = Column(String)
    faculty_id = Column(Integer, ForeignKey("faculties.id"))
    specialization_short_name = Column(String)
    study_year = Column(Integer)
    group_name = Column(String)
    subgroup_index = Column(String)
    is_modular = Column(Integer)
    has_schedule = Column(Boolean, default=False)

    faculty = relationship("Faculty", back_populates="subgroups")

class Schedule(Base):
    __tablename__ = "schedule"
    id = Column(Integer, primary_key=True)
    id_url = Column(String, primary_key=True, index=True) 
    type_short_name = Column(String)
    teacher_id = Column(Integer, ForeignKey("professors.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    topic_long_name = Column(String)
    topic_short_name = Column(String)
    week_day = Column(Integer)
    start_hour = Column(String)
    duration = Column(Integer)
    parity = Column(Integer) 
    other_info = Column(String)
    type_long_name = Column(String)
    is_didactic = Column(Integer)
    group_info = Column(String)

    professor = relationship("Professor", back_populates="schedule")
    room = relationship("Room", back_populates="schedule")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    last_name = Column(String)
    first_name = Column(String)
    email = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, default=UserRole.STUDENT.value) 
    teacher_id = Column(Integer, ForeignKey("professors.id"), nullable=True)

    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relation to Professor model
    professor_info = relationship("Professor", back_populates="user_account")

class ProfessorEmailRequest(Base):
    __tablename__ = "professor_email_requests"
    id = Column(Integer, primary_key=True)
    last_name = Column(String, nullable=False)
    first_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    request_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    status = Column(String, default="pending") # "pending", "approved", "rejected"
    resolution_date = Column(DateTime, nullable=True)

class Reservation(Base):
    __tablename__ = "reservations"
    id = Column(Integer, primary_key=True)
    professor_id = Column(Integer, ForeignKey("professors.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    subject = Column(String, nullable=False)
    type = Column(String, nullable=False)
    start_time_minutes = Column(Integer, nullable=False) 
    duration = Column(Integer, nullable=False) 
    day_of_week = Column(Integer, nullable=False) 
    week_number = Column(Integer, nullable=False) 
    calendar_date = Column(Date, nullable=False)
    required_capacity = Column(Integer, default=0)
    
    status = Column(String, default="reserved")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    cancellation_reason = Column(String, nullable=True)

    main_professor = relationship("Professor", back_populates="main_reservations", foreign_keys=[professor_id])
    room = relationship("Room", back_populates="reservations")
    
    subgroups = relationship("Subgroup", secondary=reservations_subgroups)

    additional_professors = relationship("Professor", secondary=reservations_professors, back_populates="participating_events")

class SystemStatus(Base):
    __tablename__ = "system_status"
    id = Column(Integer, primary_key=True)
    is_vacation = Column(Boolean, default=False)
    is_updating = Column(Boolean, default=False)
    last_sync = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    message = Column(String, nullable=True)
    
    # --- Columns for synchronization settings ---
    auto_sync_enabled = Column(Boolean, default=True)
    sync_interval = Column(String, default="weekly") # daily, weekly or monthly
    sync_time = Column(String, default="00:00")     # "HH:MM" format
    
class SyncHistory(Base):
    __tablename__ = "sync_history"
    id = Column(Integer, primary_key=True)
    sync_type = Column(String)      # "Base", "Calendar", "Schedule"
    trigger_type = Column(String)   # "Manual" or "Automatic"
    start_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    end_date = Column(DateTime, nullable=True)
    status = Column(String)         # "Success" or "Error"
    error_message = Column(String, nullable=True)

class AcademicCalendar(Base):
    __tablename__ = "academic_calendar"
    academic_year = Column(String, primary_key=True) # e.g., "2025-2026"
    semester = Column(Integer, primary_key=True)     # 1 or 2
    week_number = Column(Integer, primary_key=True)  # 1 - 14
    
    period = Column(String, nullable=False)          # e.g., "29.09.2025-05.10.2025"
    notes = Column(String, nullable=True)            # Holidays or reason for splitting

# --- SYNCHRONIZATION LOGIC (SQLAlchemy Events) ---

# When emailAddress changes in Professor table -> Update in User table
@event.listens_for(Professor.email_address, 'set')
def sync_professor_to_user(target, value, oldvalue, initiator):
    if value == oldvalue or value is None:
        return
    
    # Extract the active session of the object
    from sqlalchemy.orm import object_session
    session = object_session(target)
    
    if target.user_account:
        if session:
            # Check if the new email is already taken by ANOTHER user
            # to avoid database crash (Unique Constraint)
            existing_user = session.query(User).filter(
                User.email == value, 
                User.id != target.user_account.id
            ).first()
            
            if not existing_user:
                target.user_account.email = value
            else:
                print(f"Conflict: Email {value} is already in use. Account sync skipped.")
        else:
            # If there is no session (object is new), just set the value
            # SQLAlchemy will handle the rest on flush
            target.user_account.email = value