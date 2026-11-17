import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "sqlite:///telentregas.db")
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ASSET_VERSION = os.getenv("ASSET_VERSION", "5")
    CENTRAL_WHATSAPP = os.getenv("CENTRAL_WHATSAPP", "")
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "").strip()
    PENDENTE_ALERTA_MIN = int(os.getenv("PENDENTE_ALERTA_MIN", "5"))
    ACEITA_ALERTA_MIN = int(os.getenv("ACEITA_ALERTA_MIN", "15"))
    COLETADA_ALERTA_MIN = int(os.getenv("COLETADA_ALERTA_MIN", "40"))
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    SESSION_COOKIE_SECURE = FLASK_ENV == "production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    DEBUG = False
