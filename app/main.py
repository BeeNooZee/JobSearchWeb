"""Application « Ma recherche d'alternance » : FastAPI + SQLite + Jinja2, PWA + push."""
import datetime
import logging
import mimetypes
import os
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import (Application, Contact, Document, Interview, PushSubscription,
                     Reminder, STATUS_KEYS, STATUS_LABELS, STATUSES, Setting)
from . import push as push_mod
from . import reminders as reminders_mod
from . import security as sec

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alternance")

app = FastAPI(title=settings.APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)

BASE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")

# Chemins accessibles sans être connecté.
PUBLIC_PATHS = {"/login", "/setup", "/sw.js", "/manifest.webmanifest",
                "/push/public-key", "/healthz", "/favicon.ico"}


def _local_now() -> datetime.datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(settings.TZ)).replace(tzinfo=None)
    except Exception:
        return datetime.datetime.now()


# --- Filtres & globals Jinja ------------------------------------------------
def _fmt_date(s, fmt="%d/%m/%Y"):
    if not s:
        return ""
    try:
        return datetime.date.fromisoformat(str(s)[:10]).strftime(fmt)
    except ValueError:
        return s


def _fmt_dt(s):
    if not s:
        return ""
    try:
        return datetime.datetime.fromisoformat(str(s)).strftime("%d/%m/%Y à %H:%M")
    except ValueError:
        return s


def _fmt_size(n):
    n = int(n or 0)
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} Ko"
    return f"{n / 1024 / 1024:.1f} Mo"


templates.env.filters["date"] = _fmt_date
templates.env.filters["datetime"] = _fmt_dt
templates.env.filters["size"] = _fmt_size
templates.env.globals.update(STATUSES=STATUSES, STATUS_LABELS=STATUS_LABELS, APP_NAME=settings.APP_NAME)


# --- Authentification (middleware) ------------------------------------------
@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if (path in PUBLIC_PATHS or path.startswith("/static/")):
        return await call_next(request)
    token = request.cookies.get(sec.COOKIE_NAME)
    if sec.valid_token(token):
        return await call_next(request)
    # Pas connecté : redirige les pages, refuse les actions.
    if request.method == "GET" and request.headers.get("accept", "").find("text/html") >= 0:
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"error": "non authentifié"}, status_code=401)


def _ctx(request: Request, **kw):
    kw["request"] = request
    kw.setdefault("push_enabled", settings.push_enabled)
    return kw


# --- Démarrage --------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    reminders_mod.start_worker()
    logger.info("Alternance prêt. Push=%s", settings.push_enabled)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# --- Connexion / configuration initiale ------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if not sec.has_password(db):
        # Première utilisation : config autorisée seulement depuis le réseau local.
        if sec.is_private_ip(request.client.host if request.client else None):
            return templates.TemplateResponse("setup.html", _ctx(request))
        return templates.TemplateResponse(
            "login.html", _ctx(request, msg="Configuration initiale à faire depuis le réseau local."))
    if sec.valid_token(request.cookies.get(sec.COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", _ctx(request))


@app.post("/login")
def login(request: Request, password: str = Form(""), db: Session = Depends(get_db)):
    if not sec.verify_password(db, password):
        return templates.TemplateResponse(
            "login.html", _ctx(request, msg="Mot de passe incorrect."), status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(sec.COOKIE_NAME, sec.make_token(), max_age=sec.MAX_AGE,
                    httponly=True, samesite="lax", secure=settings.PUBLIC_URL.startswith("https"))
    return resp


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    if sec.has_password(db):
        return RedirectResponse("/login", status_code=303)
    if not sec.is_private_ip(request.client.host if request.client else None):
        raise HTTPException(403, "Configuration autorisée uniquement depuis le réseau local.")
    return templates.TemplateResponse("setup.html", _ctx(request))


@app.post("/setup")
def setup(request: Request, password: str = Form(""), confirm: str = Form(""),
          db: Session = Depends(get_db)):
    if sec.has_password(db):
        return RedirectResponse("/login", status_code=303)
    if not sec.is_private_ip(request.client.host if request.client else None):
        raise HTTPException(403, "Configuration autorisée uniquement depuis le réseau local.")
    if len(password) < 6:
        return templates.TemplateResponse(
            "setup.html", _ctx(request, msg="Le mot de passe doit faire au moins 6 caractères."))
    if password != confirm:
        return templates.TemplateResponse(
            "setup.html", _ctx(request, msg="Les deux mots de passe ne correspondent pas."))
    sec.set_password(db, password)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(sec.COOKIE_NAME, sec.make_token(), max_age=sec.MAX_AGE,
                    httponly=True, samesite="lax", secure=settings.PUBLIC_URL.startswith("https"))
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(sec.COOKIE_NAME)
    return resp


# --- Tableau de bord --------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    apps = db.scalars(select(Application)).all()
    counts = {k: 0 for k in STATUS_KEYS}
    for a in apps:
        counts[a.status] = counts.get(a.status, 0) + 1
    active = [a for a in apps if a.status not in ("refusee",)]
    today = _local_now().date().isoformat()
    soon = (_local_now() + datetime.timedelta(days=14)).date().isoformat()

    # Entretiens à venir.
    interviews = []
    for iv in db.scalars(select(Interview).where(Interview.done == False)).all():  # noqa: E712
        if iv.when_at and iv.when_at[:10] >= today:
            interviews.append(iv)
    interviews.sort(key=lambda x: x.when_at)

    # Relances / rappels en cours (dus ou à venir sous 14 j), + candidatures à relancer.
    rem = []
    for r in db.scalars(select(Reminder).where(Reminder.done == False)).all():  # noqa: E712
        if r.due and r.due <= soon:
            rem.append(("rappel", r.due, r.label, r.application_id, r.id, r.due < today))
    for a in apps:
        if a.next_action and a.next_action <= soon and a.status not in ("acceptee", "refusee"):
            rem.append(("relance", a.next_action, f"Relancer {a.company}", a.id, None, a.next_action < today))
    rem.sort(key=lambda x: x[1])

    total = len(apps)
    return templates.TemplateResponse("dashboard.html", _ctx(
        request, counts=counts, total=total, active=len(active),
        interviews=interviews[:8], reminders=rem[:12], today=today,
        recent=sorted(apps, key=lambda a: a.updated_at or a.created_at, reverse=True)[:6]))


# --- Tableau Kanban ---------------------------------------------------------
@app.get("/tableau", response_class=HTMLResponse)
def board(request: Request, q: str = "", db: Session = Depends(get_db)):
    stmt = select(Application)
    rows = db.scalars(stmt).all()
    needle = q.strip().lower()
    if needle:
        rows = [a for a in rows if needle in (a.company or "").lower()
                or needle in (a.role or "").lower() or needle in (a.location or "").lower()]
    cols = {k: [] for k in STATUS_KEYS}
    for a in rows:
        cols.setdefault(a.status, cols.get(a.status, [])).append(a)
    for k in cols:
        cols[k].sort(key=lambda a: (a.position, -(a.priority or 0), a.id))
    return templates.TemplateResponse("board.html", _ctx(request, cols=cols, q=q))


# --- Détail candidature -----------------------------------------------------
@app.get("/candidature/{aid}", response_class=HTMLResponse)
def application_detail(aid: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if a is None:
        raise HTTPException(404, "Candidature introuvable")
    a.interviews.sort(key=lambda x: x.when_at or "")
    a.reminders.sort(key=lambda x: x.due or "")
    return templates.TemplateResponse("application.html", _ctx(request, a=a))


def _apply_form(a: Application, f: dict):
    a.company = (f.get("company") or "").strip()[:160]
    a.role = (f.get("role") or "").strip()[:160]
    a.location = (f.get("location") or "").strip()[:120]
    a.source = (f.get("source") or "").strip()[:80]
    a.url = (f.get("url") or "").strip()[:500]
    a.salary = (f.get("salary") or "").strip()[:80]
    a.contract = (f.get("contract") or "").strip()[:40]
    a.rhythm = (f.get("rhythm") or "").strip()[:80]
    a.start_date = (f.get("start_date") or "").strip()[:32]
    a.duration = (f.get("duration") or "").strip()[:40]
    a.notes = (f.get("notes") or "").strip()
    new_na = (f.get("next_action") or "").strip()[:32]
    if new_na != a.next_action:
        a.next_action = new_na
        a.na_reminded = False  # nouvelle date de relance → re-notifiable
    status = (f.get("status") or "a_postuler").strip()
    if status in STATUS_KEYS:
        a.status = status
    a.priority = 1 if f.get("priority") else 0


@app.post("/candidatures")
async def create_application(request: Request, db: Session = Depends(get_db)):
    f = dict(await request.form())
    if not (f.get("company") or "").strip():
        raise HTTPException(400, "Le nom de l'entreprise est requis")
    a = Application()
    _apply_form(a, f)
    db.add(a)
    db.commit()
    return RedirectResponse(f"/candidature/{a.id}", status_code=303)


@app.post("/candidature/{aid}")
async def update_application(aid: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if a is None:
        raise HTTPException(404, "Candidature introuvable")
    _apply_form(a, dict(await request.form()))
    db.commit()
    return RedirectResponse(f"/candidature/{a.id}", status_code=303)


@app.post("/candidature/{aid}/supprimer")
def delete_application(aid: int, db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if a:
        db.delete(a)
        db.commit()
    return RedirectResponse("/tableau", status_code=303)


@app.post("/candidature/{aid}/statut")
async def set_status(aid: int, request: Request, db: Session = Depends(get_db)):
    """Changement de statut depuis le glisser-déposer du tableau (JSON)."""
    a = db.get(Application, aid)
    if a is None:
        raise HTTPException(404, "Candidature introuvable")
    data = await request.json()
    status = (data.get("status") or "").strip()
    if status not in STATUS_KEYS:
        raise HTTPException(400, "Statut invalide")
    a.status = status
    if "position" in data:
        try:
            a.position = int(data["position"])
        except (TypeError, ValueError):
            pass
    db.commit()
    return {"ok": True}


# --- Contacts ---------------------------------------------------------------
@app.get("/contacts", response_class=HTMLResponse)
def contacts_page(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Contact).order_by(Contact.name)).all()
    apps = db.scalars(select(Application).order_by(Application.company)).all()
    return templates.TemplateResponse("contacts.html", _ctx(request, contacts=rows, apps=apps))


@app.post("/contacts")
async def create_contact(request: Request, db: Session = Depends(get_db)):
    f = dict(await request.form())
    c = Contact(
        name=(f.get("name") or "").strip()[:120], role=(f.get("role") or "").strip()[:120],
        email=(f.get("email") or "").strip()[:160], phone=(f.get("phone") or "").strip()[:40],
        linkedin=(f.get("linkedin") or "").strip()[:300], notes=(f.get("notes") or "").strip())
    aid = f.get("application_id")
    try:
        c.application_id = int(aid) if aid else None
    except ValueError:
        c.application_id = None
    db.add(c)
    db.commit()
    back = f.get("back") or "/contacts"
    return RedirectResponse(back, status_code=303)


@app.post("/contact/{cid}/supprimer")
async def delete_contact(cid: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(Contact, cid)
    back = dict(await request.form()).get("back") or "/contacts"
    if c:
        db.delete(c)
        db.commit()
    return RedirectResponse(back, status_code=303)


# --- Entretiens -------------------------------------------------------------
@app.post("/candidature/{aid}/entretien")
async def add_interview(aid: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if a is None:
        raise HTTPException(404, "Candidature introuvable")
    f = dict(await request.form())
    iv = Interview(
        application_id=a.id, when_at=(f.get("when_at") or "").strip()[:32],
        kind=(f.get("kind") or "visio").strip()[:24], place=(f.get("place") or "").strip()[:300],
        notes=(f.get("notes") or "").strip())
    db.add(iv)
    # Passer la candidature en « Entretien » si elle est en amont.
    if a.status in ("a_postuler", "envoyee", "relance"):
        a.status = "entretien"
    db.commit()
    return RedirectResponse(f"/candidature/{a.id}", status_code=303)


@app.post("/entretien/{iid}/fait")
def interview_done(iid: int, db: Session = Depends(get_db)):
    iv = db.get(Interview, iid)
    if iv:
        iv.done = not iv.done
        db.commit()
    return RedirectResponse(f"/candidature/{iv.application_id}" if iv else "/", status_code=303)


@app.post("/entretien/{iid}/supprimer")
def interview_delete(iid: int, db: Session = Depends(get_db)):
    iv = db.get(Interview, iid)
    aid = iv.application_id if iv else None
    if iv:
        db.delete(iv)
        db.commit()
    return RedirectResponse(f"/candidature/{aid}" if aid else "/", status_code=303)


# --- Rappels / relances -----------------------------------------------------
@app.get("/rappels", response_class=HTMLResponse)
def reminders_page(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Reminder).order_by(Reminder.done, Reminder.due)).all()
    apps = db.scalars(select(Application).order_by(Application.company)).all()
    return templates.TemplateResponse("reminders.html", _ctx(
        request, reminders=rows, apps=apps, today=_local_now().date().isoformat()))


@app.post("/rappels")
async def create_reminder(request: Request, db: Session = Depends(get_db)):
    f = dict(await request.form())
    r = Reminder(label=(f.get("label") or "").strip()[:200], due=(f.get("due") or "").strip()[:32])
    aid = f.get("application_id")
    try:
        r.application_id = int(aid) if aid else None
    except ValueError:
        r.application_id = None
    db.add(r)
    db.commit()
    return RedirectResponse(f.get("back") or "/rappels", status_code=303)


@app.post("/rappel/{rid}/fait")
async def reminder_done(rid: int, request: Request, db: Session = Depends(get_db)):
    r = db.get(Reminder, rid)
    back = dict(await request.form()).get("back") or "/rappels"
    if r:
        r.done = not r.done
        db.commit()
    return RedirectResponse(back, status_code=303)


@app.post("/rappel/{rid}/supprimer")
async def reminder_delete(rid: int, request: Request, db: Session = Depends(get_db)):
    r = db.get(Reminder, rid)
    back = dict(await request.form()).get("back") or "/rappels"
    if r:
        db.delete(r)
        db.commit()
    return RedirectResponse(back, status_code=303)


# --- Documents (CV, lettres de motivation) ----------------------------------
ALLOWED_EXT = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md",
               ".jpg", ".jpeg", ".png", ".webp", ".zip"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


@app.get("/documents", response_class=HTMLResponse)
def documents_page(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Document).order_by(Document.created_at.desc())).all()
    apps = db.scalars(select(Application).order_by(Application.company)).all()
    return templates.TemplateResponse("documents.html", _ctx(request, documents=rows, apps=apps))


@app.post("/documents")
async def create_document(request: Request, title: str = Form(""), kind: str = Form("CV"),
                          link: str = Form(""), application_id: str = Form(""),
                          file: UploadFile | None = File(None), db: Session = Depends(get_db)):
    d = Document(title=title.strip()[:160] or "Document", kind=(kind or "autre")[:24],
                 link=link.strip()[:500])
    try:
        d.application_id = int(application_id) if application_id else None
    except ValueError:
        d.application_id = None
    if file is not None and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(400, "Type de fichier non autorisé (PDF, Word, image, ZIP…).")
        data = await file.read()
        if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"Fichier trop volumineux (max {settings.MAX_UPLOAD_MB} Mo).")
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        d.stored = f"{uuid.uuid4().hex}{ext[:10]}"
        with open(os.path.join(settings.UPLOAD_DIR, d.stored), "wb") as fh:
            fh.write(data)
        d.filename = os.path.basename(file.filename)[:255]
        d.content_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
        d.size = len(data)
        if not title.strip():
            d.title = d.filename
    db.add(d)
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/documents", status_code=303)


@app.get("/document/{did}")
def document_get(did: int, db: Session = Depends(get_db)):
    d = db.get(Document, did)
    if d is None or not d.stored:
        raise HTTPException(404, "Document introuvable")
    path = os.path.join(settings.UPLOAD_DIR, d.stored)
    if not os.path.isfile(path):
        raise HTTPException(404, "Fichier introuvable")
    ext = os.path.splitext(d.filename)[1].lower()
    inline = ext in IMG_EXT or ext == ".pdf"
    return FileResponse(path, media_type=d.content_type or "application/octet-stream",
                        filename=d.filename,
                        content_disposition_type="inline" if inline else "attachment")


@app.post("/document/{did}/supprimer")
async def document_delete(did: int, request: Request, db: Session = Depends(get_db)):
    d = db.get(Document, did)
    back = request.headers.get("referer") or "/documents"
    if d:
        if d.stored:
            try:
                os.remove(os.path.join(settings.UPLOAD_DIR, d.stored))
            except OSError:
                pass
        db.delete(d)
        db.commit()
    return RedirectResponse(back, status_code=303)


# --- Paramètres -------------------------------------------------------------
@app.get("/parametres", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    subs = db.scalar(select(func.count()).select_from(PushSubscription)) or 0
    return templates.TemplateResponse("settings.html", _ctx(request, sub_count=subs))


@app.post("/parametres/mot-de-passe")
def change_password(request: Request, current: str = Form(""), new: str = Form(""),
                    confirm: str = Form(""), db: Session = Depends(get_db)):
    if not sec.verify_password(db, current):
        return templates.TemplateResponse("settings.html", _ctx(
            request, sub_count=db.scalar(select(func.count()).select_from(PushSubscription)) or 0,
            msg="Mot de passe actuel incorrect.", msg_ok=False))
    if len(new) < 6 or new != confirm:
        return templates.TemplateResponse("settings.html", _ctx(
            request, sub_count=db.scalar(select(func.count()).select_from(PushSubscription)) or 0,
            msg="Nouveau mot de passe invalide (≥ 6 car.) ou non confirmé.", msg_ok=False))
    sec.set_password(db, new)
    return templates.TemplateResponse("settings.html", _ctx(
        request, sub_count=db.scalar(select(func.count()).select_from(PushSubscription)) or 0,
        msg="Mot de passe mis à jour.", msg_ok=True))


# --- Push -------------------------------------------------------------------
@app.get("/push/public-key")
def push_key():
    return {"enabled": settings.push_enabled, "key": settings.VAPID_PUBLIC_KEY}


@app.post("/push/subscribe")
async def push_subscribe(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    endpoint = (data.get("endpoint") or "").strip()
    keys = data.get("keys") or {}
    if not endpoint:
        raise HTTPException(400, "Abonnement invalide")
    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if existing:
        existing.p256dh = keys.get("p256dh", "")
        existing.auth = keys.get("auth", "")
    else:
        db.add(PushSubscription(endpoint=endpoint, p256dh=keys.get("p256dh", ""),
                                auth=keys.get("auth", "")))
    db.commit()
    return {"ok": True}


@app.post("/push/unsubscribe")
async def push_unsubscribe(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    endpoint = (data.get("endpoint") or "").strip()
    s = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if s:
        db.delete(s)
        db.commit()
    return {"ok": True}


@app.post("/push/test")
def push_test(db: Session = Depends(get_db)):
    n = push_mod.notify(db, "🔔 Test réussi",
                        "Les notifications fonctionnent sur cet appareil !", url="/", tag="test")
    return {"sent": n}


# --- PWA : manifest + service worker (servis à la racine pour le scope) ------
@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse({
        "name": settings.APP_NAME, "short_name": "Alternance",
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#0f1221", "theme_color": "#4f7cff",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    path = os.path.join(BASE, "static", "sw.js")
    return FileResponse(path, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/favicon.ico")
def favicon():
    return RedirectResponse("/static/icon-192.png", status_code=307)
