"""
Notification service: email (SMTP), SMS (Twilio), and in-app.
Falls back gracefully when credentials are not configured.
"""
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE = os.getenv("TWILIO_PHONE", "")


def send_email(to_email: str, subject: str, body_html: str) -> bool:
    """Send an HTML email. Returns True on success."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[NOTIFY-EMAIL] (no SMTP) To: {to_email} | {subject}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[NOTIFY-EMAIL] Failed: {e}")
        return False


def send_sms(to_phone: str, message: str) -> bool:
    """Send SMS via Twilio. Returns True on success."""
    if not TWILIO_SID or not TWILIO_TOKEN:
        print(f"[NOTIFY-SMS] (no Twilio) To: {to_phone} | {message[:60]}")
        return False
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=message, from_=TWILIO_PHONE, to=to_phone)
        return True
    except Exception as e:
        print(f"[NOTIFY-SMS] Failed: {e}")
        return False


def _save_notification(db, user_id: int, subject: str, message: str,
                        channel: str, status: str, error: Optional[str] = None):
    from utils.models import Notification
    notif = Notification(
        user_id=user_id,
        subject=subject,
        message=message,
        channel=channel,
        status=status,
        error_detail=error,
        sent_at=datetime.utcnow() if status == "sent" else None,
    )
    db.add(notif)
    db.commit()


def notify_challan_issued(db, user, challan) -> None:
    subject = f"Traffic Challan Issued - {challan.challan_number}"
    body = f"""
    <h2>Traffic Challan Notice</h2>
    <p>Dear {user.name},</p>
    <p>A traffic challan has been issued against your vehicle.</p>
    <table border='1' cellpadding='6'>
      <tr><td><b>Challan No.</b></td><td>{challan.challan_number}</td></tr>
      <tr><td><b>Amount</b></td><td>₹{challan.amount:,.2f}</td></tr>
      <tr><td><b>Due Date</b></td><td>{challan.due_date.strftime('%d %b %Y') if challan.due_date else 'N/A'}</td></tr>
    </table>
    <p>Please log in to the portal to pay or raise an appeal.</p>
    """
    ok = send_email(user.email, subject, body)
    _save_notification(db, user.id, subject, body, "email", "sent" if ok else "failed")

    if user.phone:
        sms_msg = f"Traffic Challan {challan.challan_number} issued. Amount: Rs.{challan.amount:.0f}. Due: {challan.due_date.strftime('%d %b %Y') if challan.due_date else 'N/A'}."
        ok_sms = send_sms(user.phone, sms_msg)
        _save_notification(db, user.id, subject, sms_msg, "sms", "sent" if ok_sms else "failed")


def notify_appeal_update(db, user, appeal, decision: str) -> None:
    subject = f"Appeal Update - Appeal #{appeal.id}"
    body = f"""
    <h2>Appeal Decision</h2>
    <p>Dear {user.name},</p>
    <p>Your appeal (ID: <b>{appeal.id}</b>) has been <b>{decision.upper()}</b>.</p>
    <p>Please log in to the portal for more details.</p>
    """
    ok = send_email(user.email, subject, body)
    _save_notification(db, user.id, subject, body, "email", "sent" if ok else "failed")


def notify_payment_reminder(db, user, challan) -> None:
    subject = f"Payment Reminder - Challan {challan.challan_number}"
    body = f"""
    <h2>Payment Reminder</h2>
    <p>Dear {user.name},</p>
    <p>Your challan <b>{challan.challan_number}</b> of ₹{challan.amount:,.2f} is due soon.</p>
    <p>Please pay to avoid penalties.</p>
    """
    ok = send_email(user.email, subject, body)
    _save_notification(db, user.id, subject, body, "email", "sent" if ok else "failed")
