# Frontend

React 18 + TypeScript + Vite UI for the Infrastructure Asset Health & Predictive Maintenance Tracker.
It consumes the backend HTTP/JSON API under `/api/v1` (health check at `/healthz`).

- Install: `npm install`
- Dev server: `npm run dev -- --host 0.0.0.0 --port 3000`
- Build: `npm run build`; Lint: `npm run lint`; Test: `npm test`
- Configuration: copy `.env.example` to `.env` and set `VITE_API_BASE_URL` to the backend URL (manifest `BACKEND_URL`).
