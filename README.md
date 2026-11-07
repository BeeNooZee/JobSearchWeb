# Ma recherche d'alternance

Webapp personnelle de suivi de candidatures d'alternance : pipeline Kanban,
relances & rappels, entretiens, contacts et documents. **PWA installable** avec
**notifications push** (relances et entretiens à venir).

## Stack
- **Backend** : FastAPI + SQLAlchemy + SQLite
- **Front** : pages rendues serveur (Jinja2) + un peu de JS — **aucun build Node**
- **PWA / Push** : manifest + service worker + Web Push (VAPID, `pywebpush`)
- **Service** : `uvicorn` derrière systemd ; HTTPS fourni par un reverse-proxy (NPM)

## Arborescence
```
app/
  main.py          routes + middleware d'auth
  models.py        candidatures, contacts, entretiens, rappels, documents
  reminders.py     tâche de fond (push des relances/entretiens)
  push.py          envoi Web Push
  security.py      auth mono-utilisateur (argon2 + cookie signé)
  templates/       pages Jinja2
  static/          style.css, app.js, sw.js, icônes
deploy/
  first-setup.sh   provisionne une VM neuve (paquets, venv, VAPID, .env, service)
  deploy.sh        déploie le code vers /opt/alternance sans toucher aux données
  setup-runner.sh  installe le runner GitHub Actions auto-hébergé
.github/workflows/deploy.yml   CI/CD : push sur main → déploiement auto
```

## Déploiement (CI/CD)
Le site tourne sur une VM en réseau privé ; le déploiement se fait donc via un
**runner GitHub Actions auto-hébergé** sur la VM (pas d'exposition SSH publique).

**Mise en place (une fois) :**
1. Provisionner la VM : `sudo bash deploy/first-setup.sh`
2. Installer le runner : récupérer le jeton dans *repo → Settings → Actions →
   Runners → New self-hosted runner*, puis
   `sudo bash deploy/setup-runner.sh <JETON>`

**Ensuite :** chaque `git push` sur `main` déclenche `.github/workflows/deploy.yml`,
qui lance `deploy/deploy.sh` sur la VM (sync du code, `pip install`, redémarrage,
vérification `healthz`). Déploiement manuel aussi possible : onglet *Actions →
Déploiement → Run workflow*, ou en SSH `sudo bash deploy/deploy.sh`.

Les données d'exécution (`.env`, `alternance.db`, `keys/`, `uploads/`) ne sont
**jamais** versionnées ni écrasées par un déploiement.

## Notifications push
Nécessitent un contexte **HTTPS** (donc le domaine public via le reverse-proxy).
Mettre alors `PUBLIC_URL=https://<domaine>` dans `/opt/alternance/.env` et
redémarrer. Activation côté appareil : *Paramètres → Activer sur cet appareil*.

## Configuration (`.env`)
`SECRET_KEY`, `PUBLIC_URL`, `DB_PATH`, `UPLOAD_DIR`, `TZ`,
`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY_FILE`, `VAPID_SUBJECT`.
Le premier accès (depuis le réseau local) permet de créer le mot de passe.
