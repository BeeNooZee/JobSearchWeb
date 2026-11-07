"""Configuration lue depuis l'environnement (fichier .env chargé par systemd)."""
import os


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "Ma recherche d'alternance")
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH: str = os.getenv("DB_PATH", os.path.join(BASE_DIR, "alternance.db"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-dev-only")
    # URL publique (sert aux liens de notification et au sujet VAPID).
    PUBLIC_URL: str = os.getenv("PUBLIC_URL", "http://192.168.1.58:8000")
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", os.path.join(BASE_DIR, "uploads"))
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
    # Fuseau horaire pour l'affichage et les rappels.
    TZ: str = os.getenv("TZ", "Europe/Paris")

    # --- Notifications push (Web Push / VAPID) ---
    VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY_FILE: str = os.getenv("VAPID_PRIVATE_KEY_FILE", "")
    VAPID_SUBJECT: str = os.getenv("VAPID_SUBJECT", "mailto:l.dalet4@gmail.com")

    @property
    def push_enabled(self) -> bool:
        return bool(self.VAPID_PUBLIC_KEY and self.VAPID_PRIVATE_KEY_FILE
                    and os.path.exists(self.VAPID_PRIVATE_KEY_FILE))


settings = Settings()
