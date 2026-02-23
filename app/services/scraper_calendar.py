# app\services\scraper_calendar.py
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
from app.models.models import CalendarUniversitar

load_dotenv()

# Configurare Client Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def validate_and_fix_period(period_str: str) -> bool:
    """
    Verifică dacă toate datele din string-ul perioadă sunt valide calendaristic.
    Format așteptat: yyyy.mm.dd-yyyy.mm.dd (opțional multiple separate prin ;)
    """
    if not period_str:
        return False
    
    # Separăm intervalele (cazul săptămânilor fragmentate)
    intervals = period_str.split(';')
    
    for interval in intervals:
        # Separăm start de end
        dates = interval.split('-')
        if len(dates) != 2:
            return False
            
        for date_text in dates:
            date_text = date_text.strip()
            try:
                # Încercăm să parsăm data. Dacă e 29 februarie într-un an non-bisect, 
                # aici va arunca ValueError
                datetime.strptime(date_text, "%Y.%m.%d")
            except ValueError:
                print(f"❌ Dată invalidă detectată: {date_text} în intervalul {period_str}")
                return False
    return True

async def get_text_from_url(url: str):
    """Extrage textul curat de pe pagina calendarului."""
    async with httpx.AsyncClient() as h_client:
        response = await h_client.get(url, timeout=30.0)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Eliminam elementele inutile
        for element in soup(["script", "style", "nav", "footer"]):
            element.decompose()
        return soup.get_text(separator=' ', strip=True)

async def process_with_gemini(text: str):
    prompt = f"""
    Rol: Expert în extragerea datelor structurate.
    Sarcina: Analizează calendarul academic și extrage activitățile conform următoarelor reguli stricte:

    1. PERIOADE DE CURS (Săptămânile 1-14):
       - Împarte aceste perioade în exact 14 rânduri per semestru.
       - Folosește numerele 1-14 pentru coloana "saptamana".
       - Format perioadă: yyyy.mm.dd-yyyy.mm.dd (ex: 2025.09.29-2025.10.05).
       - Dacă o săptămână de curs este fragmentată de vacanță, pune ambele intervale pe același rând separate prin ";" (ex: 2025.12.22-2025.12.24;2026.01.08-2026.01.11).

    2. ALTE ACTIVITĂȚI (Sesiuni, Restanțe, Reexaminări, Vacanțe):
       - NU le împărți pe săptămâni. Extrage-le ca UN SINGUR rând per activitate, exact cum apar în site.
       - Pentru coloana "saptamana", continuă numerotarea de la 15 în sus (15, 16, 17...) pentru a păstra cheia primară unică în baza de date.
       - La începutul Semestrului 2, numerotarea săptămânilor de curs se reia de la 1 la 14, iar activitățile post-semestru continuă de la 15 în sus.

    3. VERIFICARE CALENDARISTICĂ (CRITIC):
       - Verifică dacă anul vizat este BISECT sau nu. 
       - În anii NON-BISECȚI (cum este 2026), februarie are STRICT 28 de zile. NU genera data de 2026.02.29.
       - Asigură-te că trecerea de la o lună la alta este corectă (ex: după 30 sau 31 ale lunii urmează data de 01 a lunii următoare).
       - Toate datele generate trebuie să fie VALIDE matematic.

    4. FORMAT DATE: yyyy.mm.dd (Exemplu: 2026.01.19-2026.02.08).

    5. ANUL UNIVERISTAR: "yyyy-yyyy"
    
    6. OBSERVATII:
       - Scrie tipul activității: "Curs", "Sesiune Examene", "Sesiune Restante", "Vacanta", "Reexaminari".
       - Adaugă zilele libere legale dacă există DOAR în acel interval, separate prin ";" (ex: "Sesiune Examene; 2026.01.24").

    7. ATENȚIE: Pentru extragerea datelor structurate folosește DOAR textul sursă.

    Format Ieșire: JSON (listă de obiecte) fără text explicativ.
    Structura JSON:
    {{
        "an_universitar": "yyyy-yyyy",
        "semestru": int,
        "saptamana": int,
        "perioada": "string",
        "observatii": "string"
    }}

    Text sursă:
    {text}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt
        )
        # Eliminăm eventualele blocuri de cod markdown din răspuns
        raw_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_json)
    except Exception as e:
        error_str = str(e)
        # Gestionăm atât limitele de rată (429) cât și indisponibilitatea (503 / 500)
        if "429" in error_str or "503" in error_str:
            wait_time = 65
            print(f"⏳ Eroare detectată ({'Limită' if '429' in error_str else 'Server supraîncărcat'}). Reîncercăm în {wait_time}s...")
            await asyncio.sleep(wait_time)
            return await process_with_gemini(text)
        raise e

def save_to_database(calendar_data)-> bool:
    """Șterge datele existente și inserează datele noi. Returnează True la succes."""
    db: Session = SessionLocal()
    try:
        # Step 1: Ștergem toate rândurile din tabel folosind DELETE
        print("🧹 Ștergem datele existente din calendar_universitar...")
        db.execute(text("DELETE FROM calendar_universitar"))

        valid_entries = []

        # Step 2: Inserăm noile date primite de la Gemini
        for entry in calendar_data:
            # Validare structurală de bază
            period = entry.get('perioada', '')

            # Validare calendaristică strictă (Python check)
            if not validate_and_fix_period(period):
                # Aruncăm o excepție personalizată pentru a merge pe ramura de rollback
                raise ValueError(f"Date invalide în perioada: {period}")

            # Pregătire date
            entry['semestru'] = int(entry.get('semestru', 1))
            entry['saptamana'] = int(entry.get('saptamana', 0))
            entry['observatii'] = bleach.clean(entry.get('observatii', ''), tags=[], strip=True)
            
            valid_entries.append(CalendarUniversitar(**entry))

        # Inserăm totul doar dacă toate rândurile sunt valide
        db.add_all(valid_entries)
        db.commit()
        print(f"✅ Succes! S-au populat {len(calendar_data)} săptămâni în formatul cerut.")
        return True
    
    except ValueError as ve:
        print(f"⚠️ Validare eșuată: {ve}. Sincronizarea a fost oprită.")
        db.rollback()
        return False
    except Exception as e:
        print(f"❌ Eroare DB: {e}")
        db.rollback()
        return False
    finally:
        db.close()

async def run(url="https://usv.ro/academic/calendar-academic/", retries=3):
    # URL-ul unde USV publica de obicei structura anului
    for i in range(retries):
        print("Step 1: Scraping text...")
        text = await get_text_from_url(url)
        
        print("Step 2: Processing with Gemini AI...")
        data = await process_with_gemini(text)
        
        print("Step 3: Saving to DB...")
        # Modifică save_to_database să returneze True/False
        success = save_to_database(data)
        if success:
            break
        print(f"🔄 Reîncercăm procesarea (încercarea {i+2}/{retries})...")


if __name__ == "__main__":
    asyncio.run(run("https://usv.ro/academic/calendar-academic/"))