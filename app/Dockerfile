FROM python:3.13.2-slim

# Set environment variables to prevent Python from writing .pyc files 
# and to ensure logs are displayed in real-time (without buffering)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install necessary system dependencies for:
# 1. psycopg2 (libpq-dev, gcc - usually bundled or required via libpq)
# 2. pg_dump/database tools (postgresql-client)
RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install Python libraries
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the code into the container
COPY . .

# Expose the FastAPI port
EXPOSE 8000

# Start command - Ensure main.py is correctly referenced
# If main.py is inside an 'app' folder, use "app.main:app"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]