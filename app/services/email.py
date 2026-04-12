# app\services\email.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

def send_2fa_email(receiver_email: str, otp_code: str):
    """
    Sends a 2FA verification code to the specified email address using Gmail SMTP.
    Requires EMAIL_SENDER and EMAIL_PASSWORD (App Password) environment variables.
    """
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")

    # Create the email container
    message = MIMEMultipart()
    message["From"] = f"SGRD - Autentificare"
    message["To"] = receiver_email
    message["Subject"] = f"{otp_code} este codul tău de verificare"

    # HTML body stays in Romanian as it is viewed by the user
    body = f"""
    <h2>Verificare securitate <i>Sistem de gestionare a recuperărilor didactice</i></h2>
    <p>Bună ziua,</p>
    <p>Codul tău de verificare pentru accesarea platformei este:</p>
    <h1 style="color: #2563eb; letter-spacing: 5px;">{otp_code}</h1>
    <p>Acest cod este valabil 5 minute.</p>
    <p>Dacă nu ai încercat să te loghezi, te rugăm să ignori acest mesaj.</p>
    """
    
    message.attach(MIMEText(body, "html"))

    try:
        # Establish a secure connection with the server and send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(sender_email, sender_password)
            server.send_message(message)
        return True
    except Exception as error:
        # Log the error and return False if delivery fails
        print(f"Error sending email: {error}")
        return False