FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS pi-cli
ARG PI_CODING_AGENT_VERSION=0.78.1
RUN npm install --prefix /opt/pi-cli "@earendil-works/pi-coding-agent@${PI_CODING_AGENT_VERSION}"

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    ULTRA_FAST_RAG_DATA_ROOT=/app/data \
    SCRAPE_PLANNER_DATA_ROOT=/app/data \
    SCRAPE_PLANNER_DATA_ROOT_STRICT=1 \
    PI_CODING_AGENT_DIR=/app/data/pi-agent \
    PI_CODING_AGENT_SESSION_DIR=/app/data/pi-agent/sessions \
    PI_OFFLINE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    WEBAPP_RELOAD=0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    tmux \
    zsh \
    && rm -rf /var/lib/apt/lists/*

COPY --from=pi-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=pi-cli /opt/pi-cli /opt/pi-cli
RUN ln -s /opt/pi-cli/node_modules/@earendil-works/pi-coding-agent/dist/cli.js /usr/local/bin/pi

COPY requirements.txt requirements-pdf.txt requirements-mcp.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
      -r requirements.txt \
      -r requirements-pdf.txt \
      -r requirements-mcp.txt

COPY . /app
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

RUN mkdir -p /app/data/sites

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "src.scrape_planner.webapp.api:app", "--host", "0.0.0.0", "--port", "8000"]
