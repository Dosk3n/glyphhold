FROM node:22-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS dashboard

WORKDIR /dashboard

COPY dashboard-ui/package.json dashboard-ui/package-lock.json ./
RUN npm ci

COPY dashboard-ui ./
RUN npm run build

FROM node:22-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS agent_tools
WORKDIR /tools
COPY cli-tools/package.json cli-tools/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV GLYPHHOLD_DB_PATH=/data/glyphhold.sqlite
ENV CODEX_HOME=/data/advanced/codex
ENV GLYPHHOLD_WORKER_UID=10001
ENV GLYPHHOLD_WORKER_GID=10001
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

COPY --from=agent_tools /usr/local/bin/node /usr/local/bin/node
COPY --from=agent_tools /tools/node_modules /opt/glyphhold-tools/node_modules
RUN ln -s /opt/glyphhold-tools/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s /opt/glyphhold-tools/node_modules/@bitwarden/cli/build/bw.js /usr/local/bin/bw \
    && groupadd --gid 10001 ghworker \
    && useradd --uid 10001 --gid 10001 --no-create-home ghworker \
    && mkdir -p /data

COPY pyproject.toml README.md requirements.lock requirements-build.lock ./
COPY app ./app
COPY glyphhold_client ./glyphhold_client
COPY --from=dashboard /app/dashboard/static/dashboard ./app/dashboard/static/dashboard
RUN pip install --no-cache-dir --require-hashes -r requirements.lock -r requirements-build.lock \
    && pip install --no-cache-dir --no-deps --no-build-isolation . \
    && pip check \
    && pip uninstall -y pip setuptools wheel packaging

EXPOSE 5995

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5995/api/v1/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5995", "--loop", "asyncio"]
