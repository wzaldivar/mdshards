# Web tier for deployment mode 3's routing-trick variant (see README
# "Deployment" and deploy/docker-compose.yml). Builds the same UNBAKED Vite
# bundle as the main Dockerfile's frontend stage (no VITE_BACKEND_HOST), then
# serves it from nginx with the routing rules in deploy/nginx.conf. Build
# context is the REPO ROOT:
#
#   docker build -f deploy/nginx.Dockerfile -t mdshards-web .

FROM node:22-alpine AS frontend-builder

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-builder /build/dist /usr/share/nginx/html
