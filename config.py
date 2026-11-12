import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///telentregas.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CENTRAL_WHATSAPP = os.getenv("CENTRAL_WHATSAPP", "")
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "")
