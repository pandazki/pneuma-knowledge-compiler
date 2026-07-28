# pneuma-knowledge web UI — Vite SPA built with pnpm, served by nginx.
#
# nginx also reverse-proxies /v1 and /healthz to the API service, which reproduces the
# dev-time vite proxy. That keeps VITE_API_BASE empty (same-origin relative calls), so
# the SPA needs no build-time API URL and there is no CORS surface at all.
FROM node:22-alpine AS build
RUN corepack enable pnpm
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml* ./
RUN pnpm install --no-frozen-lockfile
COPY apps/web/ ./
RUN pnpm run build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
