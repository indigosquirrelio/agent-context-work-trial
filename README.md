# Requirements

- Python 3.11
- Poetry ≥ 1.8
- Node 18+ (Vite requires modern Node; download from nodejs.org or use `nvm`)
- An OpenAI API key (`OPENAI_API_KEY`) for the live agent

## Backend (FastAPI + pydantic-ai)

```bash
cd backend
poetry install
OPENAI_API_KEY=sk-... poetry run uvicorn agent_backend.server:app --reload
```

The backend listens on `http://localhost:8000` by default. The agent is configured to use `openai:gpt-4o-mini`; if the API key is missing the process exits immediately so configuration issues are surfaced.

## Frontend (React + Vite + assistant-ui)

```bash
cd frontend
npm install
VITE_BACKEND_URL=http://localhost:8000 npm run dev
```

The UI expects `files/example.py` to exist in the repository root. On load it reads that file via the backend and renders it in a read-only Monaco editor. All chat interactions mutate the same file through the agent tools.

## Project Layout

```
backend/    # FastAPI app + pydantic-ai agent (Poetry project)
frontend/   # React + Vite app (npm project)
files/      # Workspace served to the agent (currently example.py)
```