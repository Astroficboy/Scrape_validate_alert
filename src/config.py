"""Loads config/config.yaml and layers environment variables (secrets) on top."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
DATA_DIR = REPO_ROOT / "data"
SEEN_JOBS_PATH = DATA_DIR / "seen_jobs.json"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def _env(name: str, default: str = "") -> str:
    """os.getenv + strip(). GitHub Actions secrets pasted with a trailing
    newline (easy to do via copy-paste) otherwise silently corrupt request
    URLs/headers — seen in practice with a leading %0A in an Adzuna key."""
    return os.getenv(name, default).strip()


class Secrets:
    """Thin wrapper around env vars so callers can check `.available` instead
    of scattering `os.getenv` + None-checks across the codebase."""

    def __init__(self, cfg: dict[str, Any]):
        self.adzuna_app_id = _env("ADZUNA_APP_ID")
        self.adzuna_app_key = _env("ADZUNA_APP_KEY")

        self.email_address = _env("EMAIL_ADDRESS")
        self.email_app_password = _env("EMAIL_APP_PASSWORD")
        self.email_to = _env("EMAIL_TO") or cfg["candidate"]["email_to"]

        self.twilio_account_sid = _env("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = _env("TWILIO_AUTH_TOKEN")
        self.twilio_whatsapp_from = _env("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
        self.twilio_whatsapp_to_raw = _env("TWILIO_WHATSAPP_TO") or cfg["candidate"]["whatsapp_to"]
        self.twilio_content_sid = _env("TWILIO_CONTENT_SID")

        self.google_api_key = _env("GOOGLE_API_KEY")
        self.google_cse_id = _env("GOOGLE_CSE_ID")

        # IMAP reads the same dedicated inbox the digest is sent from by
        # default (the README recommends one fresh Gmail for both), but can
        # be pointed elsewhere via IMAP_USER/IMAP_PASSWORD if needed.
        self.imap_user = _env("IMAP_USER") or self.email_address
        self.imap_password = _env("IMAP_PASSWORD") or self.email_app_password

    @property
    def twilio_whatsapp_to(self) -> str:
        number = self.twilio_whatsapp_to_raw
        return number if number.startswith("whatsapp:") else f"whatsapp:{number}"

    @property
    def adzuna_available(self) -> bool:
        return bool(self.adzuna_app_id and self.adzuna_app_key)

    @property
    def email_available(self) -> bool:
        return bool(self.email_address and self.email_app_password and self.email_to)

    @property
    def whatsapp_available(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_whatsapp_to_raw)
