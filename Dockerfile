# One container: the FastAPI backend serves both the API and the built website.
# Works on Render, Hugging Face Spaces (Docker), Railway, Fly.io or any Docker host.
#   docker build -t docuflow-ai .
#   docker run -p 8000:8000 -e OPENAI_API_KEY=... -e EXTRACTOR=openai docuflow-ai

# ---- 1. build the website (static files) ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- 2. python app ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FRONTEND_DIR=/app/frontend/out \
    SEED_DIR=/app/frontend/public/demo \
    DATABASE_URL=sqlite:////data/docuflow.db \
    STORAGE_DIR=/data/uploads
WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY samples /app/samples
COPY --from=web /web/out /app/frontend/out
COPY frontend/public/demo /app/frontend/public/demo
RUN mkdir -p /data/uploads && useradd --create-home --uid 1000 app && chown -R app /data
USER app

# Hosting platforms set PORT (Render: 10000, Hugging Face: 7860); default 8000 locally
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
