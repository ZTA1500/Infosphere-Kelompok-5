# Infosphere

A campus navigation kiosk for BINUS University: interactive floor maps, room search with walking directions, and a voice/text assistant in Indonesian, English and Mandarin.

## Features

- Floor maps (Lantai 1–4) with smooth pan & zoom — drag, mouse-wheel/trackpad, pinch, double-tap, zoom buttons
- Room search with instant results and walking directions, across floors via the lift
- Voice or text assistant (local Q&A model, speech-to-text, spoken answers)
- Area status: admins mark rooms or drawn areas as *Closed* / *Under construction*; visitors see them darkened and hatched on the map, with a warning when a route touches them
- Feedback form and in-chat 👍/👎, viewable in the admin inbox
- Admin dashboard: visits, chatbot analytics, unanswered questions, retraining
- Hardened for hosting: hashed admin password, server-side sessions, CSRF, CSP and security headers, rate limits, HTTPS redirect

## Tech stack

Python 3.10+ · Flask 3 · waitress · SQLite · scikit-learn (TF-IDF Q&A model) · faster-whisper · edge-tts / pyttsx3 · plain HTML/CSS/JavaScript (no build step) · Docker (optional)

## Setup

```bash
git clone <repo-url> infosphere && cd infosphere
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                    # Windows: copy .env.example .env
python scripts/set_admin_password.py    # first admin account (see below)
python app.py                           # http://127.0.0.1:5000
```

On Windows you can instead double-click **`Start Infosphere.bat`**: it sets everything up on first run and opens the browser when the server is ready. Don't open the `.html` files directly — the pages only work when served by `app.py`.

The first start downloads the speech model and trains the chatbot (about a minute).

## Environment variables

| Name | What it's for |
|---|---|
| `INFOSPHERE_ENV` | `production` turns on the HTTPS redirect, Secure cookies and HSTS, and requires `SECRET_KEY` |
| `SECRET_KEY` | Signs the session cookie (long random string) |
| `ADMIN_USER` | Admin username |
| `ADMIN_PASSWORD_HASH` | scrypt hash of the admin password (never the password itself) |
| `VISITOR_SALT` | Key for anonymising visitor statistics |
| `TRUST_PROXY` | `1` behind a reverse proxy / load balancer, so the real client IP and HTTPS are seen |
| `INFOSPHERE_INSTANCE` | Folder for runtime data (database, logs, model cache). Use a persistent volume when hosting |
| `ADMIN_ALLOW_REMOTE` | `1` allows the admin pages from other devices over plain http (not advised) |
| `PORT`, `HOST`, `THREADS` | Server address and worker threads |
| `WHISPER_MODEL` | Speech-to-text model size: `tiny` (default), `base`, `small` |
| `CHAT_TIMEOUT_SEC`, `MATCH_THRESHOLD` | Chatbot timeout and answer confidence threshold |
| `AI_VOICE_LIVE`, `AI_VOICE_ID/EN/ZH` | Natural voice generation on/off, and the voices to use |

See `.env.example` for every option.

## First admin account

```bash
python scripts/set_admin_password.py              # asks for a password (12+ characters)
python scripts/set_admin_password.py --generate   # or: generate a strong one
```

This writes the hash plus `SECRET_KEY` and `VISITOR_SALT` to `.env`. On a hosting platform that uses environment variables instead, run it with `--print --generate` and paste the printed values into the platform's settings. Sign in at `/admin/login`. Run the script again to change the password; it also signs out every existing session.

## Build & deploy

There is no build step. Before deploying:

```bash
pip install -r requirements-dev.txt
python scripts/validate_data.py    # dataset checks
pytest                             # tests
ruff check .                       # lint
pip-audit                          # known-vulnerable packages
```

**Docker:** `docker build -t infosphere .` then
`docker run -p 8000:8000 -v infosphere-data:/data --env-file .env infosphere`.
The image runs in production mode. Put it behind HTTPS (a reverse proxy, Cloudflare Tunnel, or a platform such as Render/Railway/Fly), and keep the `/data` volume so feedback and closures survive restarts. The health check is `/healthz`.

**Without Docker:** set `INFOSPHERE_ENV=production` and `TRUST_PROXY=1`, then run `python app.py` behind an HTTPS reverse proxy.

New floor plan? Put the original image in `scripts/source-maps/lantai-N.png`, add the floor and its rooms to `data/rooms.json`, then run `python scripts/build_maps.py`.

## Folder structure

```
app.py                 entry point: pages, chat, voice, feedback, admin routes
server/                closures API, security, database, dataset checks, chatbot model
templates/             HTML pages (kiosk, landing, about, feedback, admin)
static/
  css/ js/             styles; map (panzoom, floor-map, routing) and admin scripts
  maps/                floor plans: lantai-N.webp/.png + route grids
  img/ audio/ brand/   images, recorded answers, logos
data/
  rooms.json           floors and rooms (validated by rooms.schema.json)
  qa/                  chatbot Q&A datasets (.xlsx/.csv)
scripts/               validate_data, build_maps, set_admin_password, generate_location_dataset
tests/                 pytest: dataset validation, closures API auth & validation, security
instance/              runtime data — git-ignored (database, logs, model cache)
```
