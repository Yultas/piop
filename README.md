# Pi'op

A self-hosted workspace for small teams, with a minimal monochrome interface. Chat, tasks, notes, documents, quizzes, files and an AI assistant, all in one Docker Compose stack.

## Features

- **Chat and tasks**: channels, threads, and a Kanban board. Turn any message into a task with one click.
- **Notes**: Markdown with Mermaid diagrams.
- **Typst**: compile documents to SVG or PDF.
- **Mind maps and whiteboard**.
- **Quizzes**: create, edit, take and delete quizzes.
- **Files**: folders, uploads, zip downloads, and a storage quota per workspace.
- **AI assistant**: works with any OpenAI-compatible API. It asks before changing anything.
- **Invite links**: each link is bound to the first device that uses it.
- English and Russian UI.

## Quick start

You need Docker with Docker Compose.

```bash
git clone https://github.com/Yultas/piop.git
cd piop
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:3000` and sign in as `admin`. If you didn't set a password in `.env`, a random one is printed on first start:

```bash
docker compose logs backend | grep "superadmin password"
```

To enable the AI assistant, open **Admin → AI settings** and enter the API URL, key and model.

## Configuration

All settings are optional and live in `.env`:

| Variable | Default | Description |
|---|---|---|
| `SUPERADMIN_USERNAME` | `admin` | Admin login. |
| `SUPERADMIN_PASSWORD` | generated | Used only when the admin account is first created. |
| `SECRET_KEY`, `FINGERPRINT_PEPPER` | generated | Server secrets. Generated values are stored in the data volume. |
| `DEFAULT_WORKSPACE_STORAGE_QUOTA_MB` | `500` | Storage quota for new workspaces. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | Session length (7 days). |
| `FRONTEND_PORT` | `3000` | Web UI port. |

Data (database, uploads, secrets) is kept in the `piop-data` Docker volume.

## Exposing it to the internet

For a private team, the safest option is a VPN such as Tailscale, Headscale, NetBird or WireGuard, with nothing exposed publicly.

If you need a public URL, put an HTTPS reverse proxy in front of port 3000. Caddy works, and so does Cloudflare Tunnel, which needs no public IP. Don't serve it over plain HTTP on the internet.

## Development

```bash
# Backend (FastAPI)
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
DATABASE_URL="sqlite+aiosqlite:///$PWD/data/app.db" UPLOAD_DIR="$PWD/data/uploads" \
  backend/.venv/bin/uvicorn backend.app.main:app --port 8080
```

```bash
# Frontend (Vue 3 + Vite), proxies /api to http://localhost:8080
cd frontend && npm install && npm run dev
```

```bash
# Tests
backend/.venv/bin/python -m pytest backend/tests -q
```
