# app\services\calendar_scraper.py
import os
import json
import asyncio
import httpx
import bleach
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.models import AcademicCalendar

load_dotenv()

# Gemini Client Configuration
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def validate_and_fix_period(period_str: str) -> bool:
    """
    Checks if all dates in the period string are calendar-valid.
    Expected format: yyyy.mm.dd-yyyy.mm.dd (optional multiples separated by ;)
    """
    if not period_str:
        return False
    
    # Separate intervals (case for fragmented weeks)
    intervals = period_str.split(';')
    
    for interval in intervals:
        # Separate start from end
        dates = interval.split('-')
        if len(dates) != 2:
            return False
            
        for date_text in dates:
            date_text = date_text.strip()
            try:
                # Try to parse the date. If it's Feb 29th in a non-leap year,
                # this will throw a ValueError
                datetime.strptime(date_text, "%Y.%m.%d")
            except ValueError:
                print(f"Invalid date detected: {date_text} in interval {period_str}")
                return False
    return True

async def get_text_from_url(url: str):
    """Extracts clean text from the calendar page."""
    async with httpx.AsyncClient() as h_client:
        response = await h_client.get(url, timeout=30.0)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Remove unnecessary elements
        for element in soup(["script", "style", "nav", "footer"]):
            element.decompose()
        return soup.get_text(separator=' ', strip=True)

async def process_with_gemini(text: str):
    prompt = f"""
    Rol: Expert în extragerea datelor structurate, necreativ, urmează instrucțiunile AD LITTERAM.
    Sarcina: Analizează calendarul academic și extrage activitățile conform următoarelor reguli stricte:

    REGULI STRICTE DE EXTRAGERE:
    1. PERIOADE DE CURS (Săptămânile 1-14):
       - Împarte aceste perioade în exact 14 rânduri per semestru.
       - Folosește numerele 1-14 pentru coloana "week_number".
       - Format perioadă: yyyy.mm.dd-yyyy.mm.dd (ex: 2025.09.29-2025.10.05).
       - Dacă o săptămână de curs este fragmentată de vacanță, pune ambele intervale pe același rând separate prin ";" (ex: 2025.12.22-2025.12.24;2026.01.08-2026.01.11).

    2. ALTE ACTIVITĂȚI (Sesiuni, Restanțe, Reexaminări, Vacanțe):
       - NU le împărți pe săptămâni. Extrage-le ca UN SINGUR rând per activitate, exact cum apar în site.
       - Pentru coloana "week_number", continuă numerotarea de la 15 în sus (15, 16, 17...) pentru a păstra cheia primară unică în baza de date.
       - La începutul Semestrului 2, numerotarea săptămânilor de curs se reia de la 1 la 14, iar activitățile post-semestru continuă de la 15 în sus.

    3. FORMATUL COLOANEI "notes" (CRITIC):
       - Structură: [Nume Activitate]; [Data Liberă 1]; [Data Liberă 2]...
       - Folosește ";" ca separator între activitate și fiecare dată calendaristică.
       - TOATE datele menționate în note trebuie să fie în format yyyy.mm.dd.

    4. VERIFICARE CALENDARISTICĂ (CRITIC):
       - Verifică dacă anul vizat este BISECT sau nu. 
       - În anii NON-BISECȚI (cum este 2026), februarie are STRICT 28 de zile. NU genera data de 2026.02.29.
       - Asigură-te că trecerea de la o lună la alta este corectă (ex: după 30 sau 31 ale lunii urmează data de 01 a lunii următoare).
       - Toate datele generate trebuie să fie VALIDE matematic.

    5. FORMAT DATE: yyyy.mm.dd (Exemplu: 2026.01.19-2026.02.08).

    6. ANUL UNIVERISTAR: "yyyy-yyyy"
    
    7. OBSERVATII:
       - Scrie tipul activității: "Curs", "Sesiune Examene", "Sesiune Restanțe", "Vacanță", "Reexaminări".
       - Adaugă zilele libere legale dacă există DOAR în acel interval, separate prin ";" (ex: "Sesiune Examene; 2026.01.24").

    8. ATENȚIE: Pentru extragerea datelor structurate folosește DOAR textul sursă. 

    Format Ieșire: JSON (listă de obiecte) fără text explicativ.
    Structura JSON:
    {{
        "academic_year": "yyyy-yyyy",
        "semester": int,
        "week_number": int,
        "period": "string",
        "notes": "string"
    }}

    Text sursă:
    {text}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt
        )
        # Remove any markdown code blocks from the response
        raw_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_json)
    except Exception as e:
        error_str = str(e)
        # Handle both rate limits (429) and unavailability (503 / 500)
        if "429" in error_str or "503" in error_str:
            wait_time = 65
            print(f"Error detected ({'Limit' if '429' in error_str else 'Server overloaded'}). Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)
            return await process_with_gemini(text)
        raise e

def save_to_database(calendar_data)-> bool:
    """Deletes existing data and inserts new data. Returns True on success."""
    db: Session = SessionLocal()
    try:
        # Step 1: Delete all rows from the table using DELETE
        print("Deleting existing data from academic_calendar...")
        db.execute(text("DELETE FROM academic_calendar"))

        valid_entries = []

        # Step 2: Insert new data received from Gemini
        for entry in calendar_data:
            # Basic structural validation
            period = entry.get('period', '')

            # Strict calendar validation (Python check)
            if not validate_and_fix_period(period):
                # Throw custom exception to trigger rollback branch
                raise ValueError(f"Invalid dates in period: {period}")

            # Data preparation
            entry['semester'] = int(entry.get('semester', 1))
            entry['week_number'] = int(entry.get('week_number', 0))
            entry['notes'] = bleach.clean(entry.get('notes', ''), tags=[], strip=True)
            
            valid_entries.append(AcademicCalendar(**entry))

        # Insert everything only if all rows are valid
        db.add_all(valid_entries)
        db.commit()
        print(f"Success! Populated {len(calendar_data)} weeks in the required format.")
        return True
    
    except ValueError as ve:
        print(f"Validation failed: {ve}. Synchronization stopped.")
        db.rollback()
        return False
    except Exception as e:
        print(f"DB Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()

async def run(url="https://usv.ro/academic/calendar-academic/", retries=3):
    # URL where USV usually publishes the year structure
    for i in range(retries):
        print("Step 1: Scraping text...")
        text = await get_text_from_url(url)
        
        print("Step 2: Processing with Gemini AI...")
        data = await process_with_gemini(text)
        
        print("Step 3: Saving to DB...")
        # Modified save_to_database to return True/False
        success = save_to_database(data)
        if success:
            break
        print(f"Retrying process (attempt {i+2}/{retries})...")

if __name__ == "__main__":
    asyncio.run(run("https://usv.ro/academic/calendar-academic/"))