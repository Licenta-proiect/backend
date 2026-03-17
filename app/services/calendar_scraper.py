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
    Role: Expert in structured data extraction.
    Task: Analyze the academic calendar and extract activities according to the following strict rules:
    
    1. COURSE PERIODS (Weeks 1-14):
       - Split these periods into exactly 14 rows per semester.
       - Use numbers 1-14 for the "week_number" column.
       - Period format: yyyy.mm.dd-yyyy.mm.dd (e.g., 2025.09.29-2025.10.05).
       - If a course week is fragmented by a holiday, put both intervals on the same row separated by ";" (e.g., 2025.12.22-2025.12.24;2026.01.08-2026.01.11).

    2. OTHER ACTIVITIES (Exam Sessions, Re-takes, Re-examinations, Vacations):
       - DO NOT split these into weeks. Extract them as a SINGLE row per activity, exactly as they appear on the site.
       - For the "week_number" column, continue numbering from 15 upwards (15, 16, 17...) to keep the primary key unique in the database.
       - At the start of Semester 2, course week numbering resets from 1 to 14, while post-semester activities continue from 15 upwards.

    3. CALENDAR VERIFICATION (CRITICAL):
       - Check if the targeted year is a LEAP year or not. 
       - In NON-LEAP years (such as 2026), February has STRICTLY 28 days. DO NOT generate the date 2026.02.29.
       - Ensure the transition from one month to the next is correct (e.g., after the 30th or 31st of the month comes the 01st of the following month).
       - All generated dates must be mathematically VALID.

    4. DATE FORMAT: yyyy.mm.dd (Example: 2026.01.19-2026.02.08).

    5. ACADEMIC YEAR: "yyyy-yyyy"

    6. NOTES:
       - Write the activity type: "Course", "Exam Session", "Re-take Session", "Vacation", "Re-examinations".
       - Add legal public holidays if they exist ONLY in that interval, separated by ";" (e.g., "Exam Session; 2026.01.24").

    7. ATTENTION: Use ONLY the source text for structured data extraction.

    Output Format: JSON (list of objects) without explanatory text.
    JSON Structure:
    {{
        "academic_year": "yyyy-yyyy",
        "semester": int,
        "week_number": int,
        "period": "string",
        "notes": "string"
    }}

    Source text:
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