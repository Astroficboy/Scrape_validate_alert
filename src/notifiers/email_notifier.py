"""Sends the daily digest by email via Gmail SMTP (App Password auth)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config import Secrets

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_email(secrets: Secrets, subject: str, html_body: str) -> bool:
    if not secrets.email_available:
        logger.warning("[email] skipped — EMAIL_ADDRESS/EMAIL_APP_PASSWORD/EMAIL_TO not set")
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = secrets.email_address
    message["To"] = secrets.email_to
    message.attach(MIMEText("This email requires HTML support to view.", "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=20) as server:
            server.login(secrets.email_address, secrets.email_app_password)
            server.sendmail(secrets.email_address, [secrets.email_to], message.as_string())
        logger.info("[email] sent to %s", secrets.email_to)
        return True
    except Exception:
        logger.exception("[email] send failed")
        return False
