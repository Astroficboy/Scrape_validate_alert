"""Sends the daily digest to WhatsApp via Twilio.

Two modes:
- Sandbox / within a 24h session: freeform `body` works (used automatically
  when TWILIO_CONTENT_SID is unset).
- Production, unattended daily send: WhatsApp requires a pre-approved
  message template outside the 24h customer-initiated window. Create one in
  the Twilio Console (Messaging -> Content Template Builder) with a single
  {{1}} variable for the digest text, then set TWILIO_CONTENT_SID so this
  sends via the Content API instead of a freeform body.
"""

from __future__ import annotations

import logging

from src.config import Secrets

logger = logging.getLogger(__name__)

# WhatsApp message length is generous but very long digests still get
# truncated by clients; keep well under the ~1600 char practical limit.
MAX_BODY_LENGTH = 1500


def send_whatsapp(secrets: Secrets, text: str) -> bool:
    if not secrets.whatsapp_available:
        logger.warning("[whatsapp] skipped — TWILIO_ACCOUNT_SID/AUTH_TOKEN/TO not set")
        return False

    try:
        from twilio.rest import Client
    except ImportError:
        logger.error("[whatsapp] skipped — install the 'twilio' package (see requirements.txt)")
        return False

    if len(text) > MAX_BODY_LENGTH:
        text = text[: MAX_BODY_LENGTH - 20].rsplit("\n", 1)[0] + "\n… (truncated, see email)"

    try:
        client = Client(secrets.twilio_account_sid, secrets.twilio_auth_token)
        kwargs = dict(from_=secrets.twilio_whatsapp_from, to=secrets.twilio_whatsapp_to)

        if secrets.twilio_content_sid:
            message = client.messages.create(
                content_sid=secrets.twilio_content_sid,
                content_variables=f'{{"1":"{text}"}}',
                **kwargs,
            )
        else:
            message = client.messages.create(body=text, **kwargs)

        logger.info("[whatsapp] sent, sid=%s", message.sid)
        return True
    except Exception:
        logger.exception("[whatsapp] send failed")
        return False
