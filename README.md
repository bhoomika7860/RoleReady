# RoleReady — Your AI Job-Readiness Coach

RoleReady answers one question for students and early-career applicants: **"What is stopping me from being ready
for this specific job, and what should I do next?"** It connects a target job description, your resume, a diagnostic
assessment, practice, typed mock interviews and checkpoint re-assessments into one evidence loop. Every score,
gap and recommendation is traceable to stored evidence and a published formula.

Built for Fetch-A-Thon 3.0 from `docs/RoleReady_SRS.pdf`.

---

## What's in the box

| Area | Highlights |
|---|---|
| Login | Identifier-only **demo** login (username or email), server-side sessions in HttpOnly cookies, CSRF header, rate limits |
| Target job | 4 roles (Backend, Frontend, Software Engineer, Data Analyst), 40-skill closed taxonomy, NVIDIA-powered JD extraction with deterministic keyword fallback, editable requirement checklist |
| Resume Studio | Text-PDF upload (validated, never stored), paste text, build from scratch, AI structuring with near-verbatim checks, versioned edits, deterministic requirement coverage, **fact-guarded** bullet rewrites with diff + clarifying questions |
| Assessment | 15-question role-weighted diagnostic, 6-question checkpoints, autosave/resume, code-scored objective items, rubric-scored short answers with verified quotes |
| Gaps | Six gap types, `P = min(100, round(100 × I × S × C) + B)`, resume evidence kept separate from demonstrated ability |
| Plan | Deterministic, deadline- and minutes-aware planner, auto-completing tasks, missed-task rollover, replan on new evidence |
| Practice / Interview | Curated question bank (239 items, provenance-labelled), typed mock interviews with a 5-dimension rubric, retries with like-for-like deltas |
| Dashboard | Deterministic next-best-action engine, readiness dimensions with confidence, honest progress (deltas only for comparable attempts) |

Stack: React 18 + TypeScript + Vite + Tailwind + React Router + TanStack Query + RHF/Zod + Recharts ·
FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic + psycopg 3 · Supabase PostgreSQL · NVIDIA hosted LLM.

```
frontend/   React SPA (built into frontend/dist, served by FastAPI in production)
backend/    FastAPI app (app/), Alembic migrations, seed content (app/seed), tests (tests/)
docs/       RoleReady SRS
```

---

## 1. Create the Supabase database

1. Create a project at <https://supabase.com> (pick the region closest to where you'll deploy the app).
2. **Project → Connect → Connection string → "Session pooler"** (port **5432**). Copy the URI and insert your
   database password. Use the session pooler, not the transaction pooler (6543).
3. That string is your `DATABASE_URL`. It stays on the server only.

**Database access strategy.** The browser never talks to Supabase. Only the FastAPI backend connects (as the table
owner) and enforces per-user ownership in every query (`WHERE id = :id AND user_id = :uid`; foreign IDs return 404).
Migration `0002`/`0003` enables **Row Level Security on every table with no policies** and revokes privileges from the
`anon`/`authenticated` roles, so Supabase's public REST/GraphQL Data API cannot read or write app data even with the
anon key. RLS is never disabled.

## 2. Configure the NVIDIA API

1. Get an API key at <https://build.nvidia.com> (key starts with `nvapi-`).
2. Pick a chat model available to your key and set `NVIDIA_MODEL` to its id (developed and live-tested with
   `nvidia/nemotron-3.5-super-vl-120b-a12b`).
3. The backend calls `POST {NVIDIA_BASE_URL}/chat/completions` (OpenAI-compatible, `Authorization: Bearer`). It uses
   JSON mode plus a schema description in the prompt, then validates every response with Pydantic (one repair retry,
   two transient retries). In testing, NVIDIA's schema-constrained mode returned intermittent HTTP 500s and could drop
   resume sections, so it is opt-in (`NVIDIA_STRUCTURED_OUTPUT=json_schema`).

If the key is missing, the app still runs: deterministic features (targets, keyword JD fallback, heuristic resume
split, objective scoring, gaps, plans, recommendations) keep working and AI features say they are unavailable. No
response is ever faked.

## 3. Configure the environment

```bash
cp .env.example .env      # then edit .env — never commit it (it's git-ignored)
python3 -c "import secrets; print(secrets.token_hex(32))"   # paste as SESSION_SECRET
```

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Supabase session-pooler URI |
| `SESSION_SECRET` | yes | ≥ 32 chars; signs session tokens (startup fails clearly without it) |
| `NVIDIA_API_KEY` | for AI | Server-side only — never in frontend code or `VITE_*` vars |
| `NVIDIA_BASE_URL` | no | Default `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_MODEL` | for AI | Model id |
| `APP_ENV` | no | `development` / `production` (production enables Secure cookies + HSTS, hides API docs, refuses the fake AI provider) |
| others | no | Limits and toggles — see `.env.example` |

## 4. Install and run locally

Prerequisites: Python 3.12, Node 20+ (tested on Node 24).

```bash
# backend
cd backend
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head      # creates tables + RLS lockdown in Supabase
.venv/bin/python -m app.seed        # loads roles, skills, 239 questions, resources (idempotent)
.venv/bin/uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm ci
npm run dev                          # http://localhost:5173 (proxies /api to :8000 — same origin, no CORS)
```

Or run the production build locally from one origin:

```bash
cd frontend && npm run build && cd ../backend && .venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000
```

Health: `GET /api/v1/health` (AI enabled/disabled) and `GET /api/v1/health/ready` (DB, migrations, catalogue).

Optional: re-verify learning-resource links before a demo (only resources whose links return HTTP 2xx are shown):

```bash
cd backend && .venv/bin/python scripts/check_links.py && .venv/bin/python -m app.seed
```

## 5. Tests

```bash
cd backend && .venv/bin/python -m pytest          # 68 tests
cd frontend && npm test && npm run build          # 8 tests + typecheck + production build
```

Backend tests run against an **isolated embedded PostgreSQL** (`pgserver`), never Supabase, and inject an explicit
`FakeProvider` for every AI call (refused when `APP_ENV=production`). They cover login, invalid identifiers,
new/returning users, session expiry/revocation, CSRF, cross-user isolation on every resource endpoint, PDF validation
(fake/scanned/encrypted/oversized), AI output validation, the fact guard, objective scoring, verbatim-quote checks,
failed evaluations never counting as zero, gap priorities (SRS worked example P = 78), planner capacity/ordering,
rollover, interview score computation and answer persistence on AI failure, next-action logic, error envelopes,
seed idempotency and quotas.

## 6. Deploy (one container, one origin)

The `Dockerfile` builds the SPA, installs the backend, and on start runs `alembic upgrade head`, seeds an empty
catalogue, then serves API + SPA with Uvicorn. On Render: create a Web Service from this repo (Docker runtime, or use
`render.yaml`), set `APP_ENV=production`, `DATABASE_URL`, `SESSION_SECRET`, `NVIDIA_API_KEY`, `NVIDIA_MODEL`, health
check `/api/v1/health/ready`. Deploy the app in the same region as your Supabase project: every request makes several
database round trips, so cross-region latency dominates response times.

> Status: the Dockerfile has not been built in this environment (Docker isn't installed here), and no cloud deploy has
> been performed. Local production mode (FastAPI serving `frontend/dist`) has been run and tested end to end.

---

## Security and honesty notes

- **Demo-only authentication.** Login accepts a username or email without proving ownership; anyone typing the same
  identifier reaches the same account. Sessions themselves are sound (256-bit random tokens, only an HMAC-SHA256 stored,
  7-day sliding expiry capped at 30 days, server-side revocation, `HttpOnly; SameSite=Lax; Secure` in production,
  `X-RoleReady-Client` header required on every mutation). The `AuthMethod` boundary in
  `backend/app/modules/auth/service.py` is where email OTP / magic links would plug in. **Not production identity.**
- The NVIDIA key and database URL exist only in server environment variables; logs never include request bodies,
  resumes, answers, prompts, cookies or keys. `ai_requests` stores metadata only.
- Contact details (name, email, phone, links, addresses) are redacted before resume text is sent to the AI provider.
  Original PDFs are never stored.
- Resume text, JDs and answers are treated as untrusted input (delimited, instructions ignored, outputs constrained
  and cross-checked). Rewrites pass a deterministic fact guard and never apply without explicit acceptance.
- Questions are curated for each role; none is presented as a real company interview question. The bank was drafted
  with AI assistance and is labelled **"AI-assisted draft"** until a team member reviews it (set `reviewed_by` in the
  YAML). Readiness numbers are uncalibrated estimates, not predictions of shortlisting, interviews or offers.

## Demo flow (≈ 8 minutes)

1. Open the app → **Login** → type a new username.
2. Onboarding: name → Backend Developer + company → paste a JD (see `demo/sample_jd.txt`) → confirm requirements →
   paste or upload the sample resume (`demo/sample_resume.txt` / `.pdf`, fictional).
3. Resume Studio → **Looks right — save** → **Requirement match** (coverage, "not shown" wording) → **Improve bullets**
   (fact-guarded suggestion with diff).
4. Assessment → diagnostic (answer quickly) → **Results & gaps** (ranked gaps with formula inputs).
5. **Build my plan** (fits your daily minutes) → Practice a few SQL questions → Mock interview → retry for a delta.
6. Take an SQL checkpoint → dashboard shows the updated next action. Refresh (data persists) → log out (protected
   pages redirect to login).

A pre-filled account for a backup demo can be created with real AI calls by `python -m app.demo` (see below).
