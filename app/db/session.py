# app\db\session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependență pentru a obține sesiunea de DB în rutele API
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

if __name__ == "__main__":
    try:
        # Încearcă să creeze o conexiune fizică
        connection = engine.connect()
        print("Conexiune reușită la PostgreSQL! 🚀")
        connection.close()
    except Exception as e:
        print(f"Eroare de conexiune: {e}")