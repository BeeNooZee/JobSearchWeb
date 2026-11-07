"""Modèles de données : candidatures, contacts, entretiens, rappels, documents."""
import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# Étapes du pipeline (colonnes du tableau Kanban), dans l'ordre.
STATUSES = [
    ("a_postuler", "À postuler"),
    ("envoyee", "Candidature envoyée"),
    ("relance", "Relancée"),
    ("entretien", "Entretien"),
    ("offre", "Offre reçue"),
    ("acceptee", "Acceptée"),
    ("refusee", "Refusée / sans suite"),
]
STATUS_KEYS = [k for k, _ in STATUSES]
STATUS_LABELS = dict(STATUSES)


class Setting(Base):
    """Petit magasin clé→valeur (mot de passe, préférences)."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Application(Base):
    """Une candidature / piste d'alternance."""
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(160), default="")       # poste
    location: Mapped[str] = mapped_column(String(120), default="")   # lieu
    source: Mapped[str] = mapped_column(String(80), default="")      # LinkedIn, site, cooptation…
    url: Mapped[str] = mapped_column(String(500), default="")        # lien de l'offre
    salary: Mapped[str] = mapped_column(String(80), default="")      # rémunération
    contract: Mapped[str] = mapped_column(String(40), default="")    # apprentissage / pro
    rhythm: Mapped[str] = mapped_column(String(80), default="")      # rythme d'alternance
    start_date: Mapped[str] = mapped_column(String(32), default="")  # date de début souhaitée
    duration: Mapped[str] = mapped_column(String(40), default="")    # durée
    status: Mapped[str] = mapped_column(String(24), default="a_postuler", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)         # 0 normal, 1 favori
    next_action: Mapped[str] = mapped_column(String(32), default="")  # date de relance (YYYY-MM-DD)
    na_reminded: Mapped[bool] = mapped_column(Boolean, default=False)  # relance déjà notifiée
    notes: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)         # ordre dans la colonne
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin")
    interviews: Mapped[list["Interview"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin")
    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin")


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(120), default="")   # fonction (RH, manager…)
    email: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    linkedin: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped["Application"] = relationship(back_populates="contacts")


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    when_at: Mapped[str] = mapped_column(String(32), default="")  # "YYYY-MM-DDTHH:MM"
    kind: Mapped[str] = mapped_column(String(24), default="visio")  # visio / présentiel / téléphone
    place: Mapped[str] = mapped_column(String(300), default="")   # lieu ou lien
    notes: Mapped[str] = mapped_column(Text, default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_day: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_soon: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped["Application"] = relationship(back_populates="interviews")


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    due: Mapped[str] = mapped_column(String(32), default="", index=True)  # "YYYY-MM-DD"
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped["Application"] = relationship(back_populates="reminders")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(24), default="CV")  # CV / LM / autre
    stored: Mapped[str] = mapped_column(String(80), default="")  # nom sur disque (si fichier)
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    link: Mapped[str] = mapped_column(String(500), default="")   # lien externe (si pas de fichier)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped["Application"] = relationship(back_populates="documents")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, default="")
    auth: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
