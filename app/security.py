"""Authentification mono-utilisateur : mot de passe haché (argon2) + cookie signé."""
import ipaddress

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Setting

_ph = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="alternance-session")
COOKIE_NAME = "alt_session"
MAX_AGE = 60 * 60 * 24 * 30  # 30 jours


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def has_password(db: Session) -> bool:
    return bool(get_setting(db, "password_hash"))


def set_password(db: Session, password: str) -> None:
    set_setting(db, "password_hash", _ph.hash(password))


def verify_password(db: Session, password: str) -> bool:
    h = get_setting(db, "password_hash")
    if not h:
        return False
    try:
        _ph.verify(h, password)
    except VerifyMismatchError:
        return False
    # Ré-encode si les paramètres argon2 ont changé.
    if _ph.check_needs_rehash(h):
        set_setting(db, "password_hash", _ph.hash(password))
    return True


def make_token() -> str:
    return _serializer.dumps({"ok": True})


def valid_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        _serializer.loads(token, max_age=MAX_AGE)
        return True
    except BadSignature:
        return False


def is_private_ip(host: str | None) -> bool:
    """Vrai si la requête vient du réseau local (utilisé pour autoriser la 1ʳᵉ config)."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback
