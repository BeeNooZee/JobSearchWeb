"""Tâche de fond : rappels push (entretiens, relances) toutes les 60 s."""
from __future__ import annotations

import datetime
import logging
import threading
import time

from sqlalchemy import select

from .database import SessionLocal
from .models import Application, Interview, Reminder, STATUS_LABELS
from .push import notify

logger = logging.getLogger("alternance.reminders")


def _local_now() -> datetime.datetime:
    try:
        from zoneinfo import ZoneInfo
        from .config import settings
        return datetime.datetime.now(ZoneInfo(settings.TZ)).replace(tzinfo=None)
    except Exception:
        return datetime.datetime.now()


def _parse_dt(s: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def scan_once() -> int:
    """Parcourt entretiens/relances dus et envoie les notifications. Renvoie le nb envoyé."""
    db = SessionLocal()
    sent = 0
    try:
        now = _local_now()
        today = now.date().isoformat()

        # --- Entretiens à venir ---
        for iv in db.scalars(select(Interview).where(Interview.done == False)).all():  # noqa: E712
            start = _parse_dt(iv.when_at)
            if start is None:
                continue
            delta = start - now
            app = iv.application
            who = (app.company or "une entreprise") if app else "une entreprise"
            hhmm = start.strftime("%H:%M")
            # Rappel la veille / le jour même (fenêtre : 0 à 24 h avant).
            if not iv.reminded_day and datetime.timedelta(0) <= delta <= datetime.timedelta(hours=24):
                when = "aujourd'hui" if start.date() == now.date() else "demain"
                sent += notify(db, "📅 Entretien bientôt",
                               f"Entretien {who} {when} à {hhmm}.",
                               url=f"/candidature/{app.id}" if app else "/", tag="entretien")
                iv.reminded_day = True
            # Rappel « dans moins d'une heure ».
            if not iv.reminded_soon and datetime.timedelta(0) <= delta <= datetime.timedelta(minutes=60):
                sent += notify(db, "⏰ Entretien dans 1 h",
                               f"Entretien {who} à {hhmm}. Prépare-toi !",
                               url=f"/candidature/{app.id}" if app else "/", tag="entretien")
                iv.reminded_soon = True

        # --- Relances / rappels manuels dus ---
        for r in db.scalars(
                select(Reminder).where(Reminder.done == False, Reminder.reminded == False)).all():  # noqa: E712
            if r.due and r.due <= today:
                app = r.application
                suffix = f" — {app.company}" if app and app.company else ""
                sent += notify(db, "🔔 Rappel", f"{r.label or 'Rappel'}{suffix}",
                               url=f"/candidature/{app.id}" if app else "/rappels", tag="rappel")
                r.reminded = True

        # --- Date de relance posée sur une candidature ---
        for app in db.scalars(
                select(Application).where(Application.na_reminded == False)).all():  # noqa: E712
            if app.next_action and app.next_action <= today:
                sent += notify(db, "🔁 Relance à faire",
                               f"Relancer {app.company or 'cette candidature'} "
                               f"({STATUS_LABELS.get(app.status, app.status)}).",
                               url=f"/candidature/{app.id}", tag="relance")
                app.na_reminded = True

        db.commit()
    except Exception as e:  # pragma: no cover
        logger.warning("Erreur scan rappels: %s", e)
    finally:
        db.close()
    return sent


_started = False


def start_worker() -> None:
    """Démarre le thread de fond une seule fois."""
    global _started
    if _started:
        return
    _started = True

    def _loop():
        # Petit délai au démarrage pour laisser l'app se mettre en place.
        time.sleep(10)
        while True:
            scan_once()
            time.sleep(60)

    threading.Thread(target=_loop, daemon=True, name="reminders").start()
    logger.info("Tâche de rappels démarrée.")
