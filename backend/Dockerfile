# Build context must be the repo root (EMIOS/EMIOS), not backend/, e.g.:
#   podman build -f backend/Dockerfile -t emios-backend .
# This is required so the image can also embed ../frontend - main.py mounts
# frontend/dist via StaticFiles at startup and crashes immediately if it's missing.

# --- Python builder stage ---
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .

RUN pip install --no-cache-dir --user -r requirements.txt

# --- Frontend builder stage: compiles the Vite/React SPA to static assets.
# main.py serves frontend/dist, not the raw TSX sources (which browsers can't
# execute unbuilt) - this stage is what produces that dist/ directory.
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build

# --- Production stage ---
FROM python:3.11-slim AS production

WORKDIR /app

# Copy installed site-packages from builder
COPY --from=builder /root/.local /root/.local
COPY backend/ /app
# main.py resolves this as ../frontend/dist relative to itself (i.e. /frontend/dist
# in the image) - must be present or the StaticFiles mount at the bottom of
# main.py raises at startup.
COPY --from=frontend-builder /frontend/dist /frontend/dist

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "main.py"]
