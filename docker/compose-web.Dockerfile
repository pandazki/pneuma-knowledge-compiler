# The web UI for a project run with docker compose — the scaffold's `console` profile and
# examples/opc's `web` profile both build this image.
#
# The Vite SPA is built with pnpm and served by nginx, which also reverse-proxies /v1 and
# /healthz to the compose `api` service (docker/nginx.compose.conf). That reproduces the
# dev-time vite proxy, so VITE_API_BASE stays empty (same-origin relative calls), the SPA
# needs no build-time API URL, and there is no CORS surface at all.
#
# docker/web.Dockerfile is the cloud sibling: the same build, with an nginx config that
# resolves its upstream through kube-dns.
FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /app

# The Engine Console ships with mock fixtures so the UI could be built before the API
# existed. A project image always has the API beside it, so the real /v1/engine/* routes are
# the default here; a deployment whose api service serves no engine directory passes "true".
# Declared twice on purpose: Vite reads VITE_* from the process environment AND from
# .env.production, and which of the two wins has changed between Vite versions.
ARG VITE_ENGINE_FIXTURES=false
ENV VITE_ENGINE_FIXTURES=${VITE_ENGINE_FIXTURES}

COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web/ ./
RUN printf 'VITE_ENGINE_FIXTURES=%s\n' "$VITE_ENGINE_FIXTURES" > .env.production
RUN pnpm build

FROM nginx:1.27-alpine
COPY docker/nginx.compose.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
