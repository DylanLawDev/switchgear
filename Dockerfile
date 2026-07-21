FROM node:22-slim AS webbuild
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite outDir is ../src/switchgear/web/static/app → lands in /build/src/... in this stage
RUN npm run build

FROM python:3.12-slim AS runtime
ARG VERSION=0.1.0
LABEL org.opencontainers.image.title="switchgear" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/your-owner/switchgear"
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY skills ./skills
COPY workflows ./workflows
COPY resources ./resources
COPY channels ./channels
COPY --from=webbuild /build/src/switchgear/web/static/app ./src/switchgear/web/static/app
RUN uv sync --frozen --no-dev
RUN groupadd --system --gid 10001 switchgear && useradd --system --uid 10001 --gid switchgear switchgear \
    && mkdir -p /data && chown switchgear:switchgear /data
ENV PORT=8080 SWITCHGEAR_STATE_DIR=/data PYTHONUNBUFFERED=1 SWITCHGEAR_VERSION=${VERSION} \
    PATH="/app/.venv/bin:${PATH}" UV_NO_SYNC=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
VOLUME ["/data"]
USER switchgear
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["sh", "-c", "exec uvicorn switchgear.main:app --host 0.0.0.0 --port ${PORT}"]

FROM runtime AS browser
USER root
RUN uv sync --no-dev --extra browser && uv run playwright install --with-deps chromium
USER switchgear

FROM runtime AS full
USER root
RUN uv sync --frozen --no-dev --extra full && uv run playwright install --with-deps chromium
USER switchgear

FROM runtime AS default
