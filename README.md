# Requirements

- Python 3.11
- Poetry ≥ 1.8
- Node 18+ (Vite requires modern Node; download from nodejs.org or use `nvm`)
- An OpenAI API key (`OPENAI_API_KEY`) for the live agent

## Backend (FastAPI + pydantic-ai)

```bash
cd backend
poetry install
OPENAI_API_KEY=your_openai_api_key_here poetry run uvicorn agent_backend.server:app --reload
```

The backend listens on `http://localhost:8000` by default. The agent is configured to use `openai:gpt-4o-mini`; if the API key is missing the process exits immediately so configuration issues are surfaced.

## Frontend (React + Vite + assistant-ui)

```bash
cd frontend
npm install
VITE_BACKEND_URL=http://localhost:8000 npm run dev
```

The UI expects `files/__init__.py` to exist. On load it reads that file via the backend and renders it in Monaco. All chat interactions and UI saves go through the same HTTP file store.

## Project Layout

```
backend/    # FastAPI app + pydantic-ai agent (Poetry project)
frontend/   # React + Vite app (npm project)
files/      # Workspace served to the agent (currently __init__.py)
```

## HTTP File Store (mounted at /files)

- POST /files/read { path, encoding? } → { path, content, etag }
- POST /files/write { path, content, encoding? } → { path, content, etag }
- GET /files/list → { files: string[] }
- DELETE /files/delete?path=... → { path, deleted }

### Environment

- FILE_STORE_URL (default http://localhost:8000/files)
- CHAOS_INTERVAL (default 30)
- CHAOS_PROTECT (default files/example.py) # optional; Chaos Monkey only
