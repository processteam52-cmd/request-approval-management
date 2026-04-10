# BNR Approval System

Production-ready minimal setup for a FastAPI + MySQL backend and single-file HTML frontend.

## Project Structure

- `backend/main.py` — FastAPI application and API routes
- `backend/requirements.txt` — Python dependencies
- `backend/.env.example` — environment variable template
- `backend/render.yaml` — Render deployment blueprint
- `backend/Procfile` — Railway/Render fallback start command
- `frontend/index.html` — single-file UI (HTML/CSS/Vanilla JS)
- `frontend/netlify.toml` — Netlify config

## Local Run

### 1) Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your MySQL/JWT values
set -a && source .env && set +a
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 2) Frontend

Open `frontend/index.html` in a browser (or serve it):

```bash
cd frontend
python -m http.server 5500
```

Set backend URL in UI to `http://127.0.0.1:8000`.

## Environment Variables

Use `backend/.env.example` as baseline.

Required in production:

- `DB_HOST`
- `DB_PORT`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `JWT_SECRET`
- `CORS_ORIGINS` (include frontend origin)

## API Endpoints

- `GET /`
- `GET /db-test`
- `POST /register`
- `POST /login`
- `POST /requests` (auth required)
- `GET /requests` (auth required)
- `PATCH /requests/{request_id}/decision` (admin only)

## Deployment

### Backend on Render

1. Create a new Web Service from repository.
2. Set root directory to `backend`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables from `.env.example`.
6. Provision a MySQL database and copy connection values into env vars.

### Backend on Railway

1. Deploy repo.
2. Service root: `backend`.
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Configure all environment variables.

### Frontend on Netlify

1. Create site from repo.
2. Set base directory to `frontend`.
3. Publish directory: `.`
4. No build command required.
5. After deploy, open app and set Backend Base URL to your backend URL.

### Frontend on Vercel

1. Import repo.
2. Set project root to `frontend`.
3. Framework preset: Other.
4. Output directory: `.`

## Android APK Wrapper Readiness

Because frontend uses a configurable base URL and plain JS fetch calls, this can be wrapped later in WebView-based tools (Capacitor/Cordova/WebView wrappers) without changing API logic.
