# Web tier for deployment mode 2 in container form (see README "Deployment"
# and deploy/docker-compose.preview.yml): Vite's preview server serves the
# UNBAKED bundle and proxies /api, /ws, and vault-asset fetches to wherever
# VITE_BACKEND_HOST points at RUNTIME — the same image redeploys against any
# backend location with just an env change, no rebuild.
#
# VITE_BACKEND_HOST must NOT be set during `npm run build` here — that would
# bake it (mode 3) instead of proxying. Build context is the REPO ROOT:
#
#   docker build -f deploy/preview.Dockerfile -t mdshards-web-preview .

FROM node:22-alpine

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

EXPOSE 4173

# `--host` binds all interfaces — inside a container, localhost-only would be
# unreachable through the published port.
CMD ["npm", "run", "preview", "--", "--port", "4173", "--host"]
