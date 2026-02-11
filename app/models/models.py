# app\models\models.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Date, Table
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

rezervari_profesori = Table(
    "rezervari_profesori",
    Base.metadata,
    Column("rezervare_id", Integer, ForeignKey("rezervari.id"), primary_key=True),
    Column("profesor_id", Integer, ForeignKey("profesori.id"), primary_key=True),
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

    facultate = relationship("Facultate", back_populates="profesori")
    # CORECTAT: back_populates="profesor" (era "profesori")
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

    # AICI se face referință la back_populates="orar" din Profesor
    profesor = relationship("Profesor", back_populates="orar")
    sala = relationship("Sala", back_populates="orar")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    lastName = Column(String)
    firstName = Column(String)
    email = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, default=UserRole.STUDENT.value) 
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    
    profesor_titular = relationship("Profesor", back_populates="rezervari_titular")
    sala = relationship("Sala", back_populates="rezervari")
    
    grupe = relationship("Subgrupa", secondary=rezervari_grupe)
    profesori_ajutatori = relationship("Profesor", secondary=rezervari_profesori)

class SistemStatus(Base):
    __tablename__ = "sistem_status"
    id = Column(Integer, primary_key=True)
    is_vacation = Column(Boolean, default=False)
    is_updating = Column(Boolean, default=False)
    last_sync = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    message = Column(String, nullable=True)

class CalendarUniversitar(Base):
    __tablename__ = "calendar_universitar"
    
    an_universitar = Column(String, primary_key=True) # ex: "2025-2026"
    semestru = Column(Integer, primary_key=True)      # 1 sau 2
    saptamana = Column(Integer, primary_key=True)     # 1 - 14
    
    perioada = Column(String, nullable=False)         # ex: "29.09.2025-05.10.2025" sau "22.12.2025-24.12.2025;08.01.2026-11.01.2026"
    observatii = Column(String, nullable=True)        # Sărbători sau motive de fracționare