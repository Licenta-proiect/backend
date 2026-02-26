# app\models\models.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Date, Table, event
from sqlalchemy.orm import relationship
from app.db.session import Base
from datetime import datetime, timezone
import enum

class UserRole(enum.Enum):
    ADMIN = "ADMIN"
    STUDENT = "STUDENT"
    PROFESOR = "PROFESOR"

# --- TABELE DE LEGĂTURĂ ---
rezervari_grupe = Table(
    "rezervari_grupe",
    Base.metadata,
    Column("rezervare_id", Integer, ForeignKey("rezervari.id"), primary_key=True),
    Column("subgrupa_id", Integer, ForeignKey("subgrupe.id"), primary_key=True),
)

# --- MODELE PRINCIPALE ---

class Facultate(Base):
    __tablename__ = "facultati"
    id = Column(Integer, primary_key=True)
    shortName = Column(String)
    longName = Column(String)
    subgrupe = relationship("Subgrupa", back_populates="facultate")
    profesori = relationship("Profesor", back_populates="facultate")

class Profesor(Base):
    __tablename__ = "profesori"
    id = Column(Integer, primary_key=True)
    lastName = Column(String)
    firstName = Column(String)
    positionShortName = Column(String)
    phdShortName = Column(String)
    otherTitle = Column(String)
    emailAddress = Column(String, index=True, nullable=True)
    faculty_id = Column(Integer, ForeignKey("facultati.id"), nullable=True)
    departmentName = Column(String)
    has_schedule = Column(Boolean, default=False)

    # Relația către modelul User
    user_account = relationship("User", back_populates="profesor_info", uselist=False)

    facultate = relationship("Facultate", back_populates="profesori")
    orar = relationship("Orar", back_populates="profesor")
    rezervari_titular = relationship("Rezervare", back_populates="profesor_titular")

class Sala(Base):
    __tablename__ = "sali"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    shortName = Column(String)
    buildingName = Column(String)
    capacitate = Column(Integer)
    computers = Column(Integer)
    has_schedule = Column(Boolean, default=False)

    orar = relationship("Orar", back_populates="sala")
    rezervari = relationship("Rezervare", back_populates="sala")

class Subgrupa(Base):
    __tablename__ = "subgrupe"
    id = Column(Integer, primary_key=True)
    type = Column(String)
    faculty_id = Column(Integer, ForeignKey("facultati.id"))
    specializationShortName = Column(String)
    studyYear = Column(Integer)
    groupName = Column(String)
    subgroupIndex = Column(String)
    isModular = Column(Integer)
    has_schedule = Column(Boolean, default=False)

    facultate = relationship("Facultate", back_populates="subgrupe")

class Orar(Base):
    __tablename__ = "orar"
    id = Column(Integer, primary_key=True)
    idURL = Column(String, primary_key=True, index=True) 
    typeShortName = Column(String)
    teacherID = Column(Integer, ForeignKey("profesori.id"), nullable=True)
    roomId = Column(Integer, ForeignKey("sali.id"), nullable=True)
    topicLongName = Column(String)
    topicShortName = Column(String)
    weekDay = Column(Integer)
    startHour = Column(String)
    duration = Column(Integer)
    parity = Column(Integer) 
    otherInfo = Column(String)
    typeLongName = Column(String)
    isDidactic = Column(Integer)
    grupa = Column(String, index=True)

    profesor = relationship("Profesor", back_populates="orar")
    sala = relationship("Sala", back_populates="orar")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    lastName = Column(String)
    firstName = Column(String)
    email = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, default=UserRole.STUDENT.value) 
    teacher_id = Column(Integer, ForeignKey("profesori.id"), nullable=True)

    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relația către modelul Profesor
    profesor_info = relationship("Profesor", back_populates="user_account")

class CerereEmailProfesor(Base):
    __tablename__ = "cereri_email_profesori"
    id = Column(Integer, primary_key=True)
    lastName = Column(String, nullable=False)
    firstName = Column(String, nullable=False)
    email = Column(String, nullable=False)
    data_cerere = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    status = Column(String, default="pending") # "pending", "approved", "rejected"
    data_solutionare = Column(DateTime, nullable=True)

class Rezervare(Base):
    __tablename__ = "rezervari"
    id = Column(Integer, primary_key=True)
    idProfesorTitular = Column(Integer, ForeignKey("profesori.id"))
    idSala = Column(Integer, ForeignKey("sali.id"))
    saptamana = Column(Integer)
    zi = Column(Integer)
    tip = Column(String)
    oraInceput = Column(Integer)
    durata = Column(Integer)
    capacitate_necesara = Column(Integer)
    data_calendaristica = Column(Date)
    materie = Column(String)
    status = Column(String, default="rezervat")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    motiv_anulare = Column(String, nullable=True)

    profesor_titular = relationship("Profesor", back_populates="rezervari_titular")
    sala = relationship("Sala", back_populates="rezervari")
    
    grupe = relationship("Subgrupa", secondary=rezervari_grupe)

class SistemStatus(Base):
    __tablename__ = "sistem_status"
    id = Column(Integer, primary_key=True)
    is_vacation = Column(Boolean, default=False)
    is_updating = Column(Boolean, default=False)
    last_sync = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    message = Column(String, nullable=True)
    
    # --- Coloane pentru setările de sincronizare ---
    auto_sync_enabled = Column(Boolean, default=True)
    sync_interval = Column(String, default="weekly") # daily, weekly sau monthly
    sync_time = Column(String, default="00:00")     # Format "HH:MM"

class IstoricSincronizare(Base):
    __tablename__ = "istoric_sincronizari"
    id = Column(Integer, primary_key=True)
    tip_sincronizare = Column(String)  # "Base", "Calendar", "Orar"
    tip_declansare = Column(String)    # "Manual" sau "Automat"
    data_start = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    data_final = Column(DateTime, nullable=True)
    status = Column(String)            # "Succes" sau "Eroare"
    mesaj_eroare = Column(String, nullable=True)

class CalendarUniversitar(Base):
    __tablename__ = "calendar_universitar"
    an_universitar = Column(String, primary_key=True) # ex: "2025-2026"
    semestru = Column(Integer, primary_key=True)      # 1 sau 2
    saptamana = Column(Integer, primary_key=True)     # 1 - 14
    
    perioada = Column(String, nullable=False)         # ex: "29.09.2025-05.10.2025" sau "22.12.2025-24.12.2025;08.01.2026-11.01.2026"
    observatii = Column(String, nullable=True)        # Sărbători sau motive de fracționare

# --- LOGICA DE SINCRONIZARE (SQLAlchemy Events) ---
# Când se schimbă email-ul în tabela Profesor -> Modifică în User
@event.listens_for(Profesor.emailAddress, 'set')
def sync_professor_to_user(target, value, oldvalue, initiator):
    if value == oldvalue or value is None:
        return
    
    # Dacă profesorul are un cont, actualizăm email-ul de login
    if target.user_account:
        if target.user_account.email != value:
            target.user_account.email = value