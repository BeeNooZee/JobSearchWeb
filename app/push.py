"""Notifications Web Push (VAPID). Les abonnements périmés sont nettoyés."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import PushSubscription

logger = logging.getLogger("alternance.push")


def notify(db: Session, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Envoie une notification à tous les appareils abonnés. Ne lève jamais."""
    if not settings.push_enabled:
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except Exception:  # pragma: no cover
        logger.warning("pywebpush indisponible — notification ignorée.")
        return 0

    subs = db.scalars(select(PushSubscription)).all()
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or "alt"})
    sent = 0
    stale: list[PushSubscription] = []
    for s in subs:
        try:
            webpush(
                subscription_info={"endpoint": s.endpoint,
                                   "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY_FILE,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                timeout=10,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                stale.append(s)
            else:
                logger.warning("Échec push (%s…): %s", s.endpoint[:40], e)
        except Exception as e:  # pragma: no cover
            logger.warning("Erreur push inattendue: %s", e)

    if stale:
        for s in stale:
            db.delete(s)
        db.commit()
        logger.info("Push: %d abonnement(s) périmé(s) supprimé(s).", len(stale))
    return sent
