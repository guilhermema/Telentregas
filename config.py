import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///telentregas.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CENTRAL_WHATSAPP = os.getenv("CENTRAL_WHATSAPP", "")
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "").strip()
