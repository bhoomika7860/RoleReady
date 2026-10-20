# RoleReady — single container: FastAPI serves /api/v1 and the built React SPA from the same origin.

# ---- stage 1: build the frontend
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: python runtime
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    APP_ENV=production STATIC_DIR=/app/static
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/static
RUN useradd --create-home --uid 10001 roleready && chown -R roleready /app
USER roleready
EXPOSE 8000
# Migrations are forward-only and run before the app starts; the seed only runs when the catalogue is empty.
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed --if-empty && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
