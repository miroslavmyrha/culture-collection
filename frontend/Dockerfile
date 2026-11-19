# The production proxy (#178): the built SPA served by nginx, which also terminates TLS and
# passes /api, /static and the admin to the backend. Base images by version and digest, bumped
# together (Dependabot, .github/dependabot.yml). Run it read-only with tmpfs on /tmp and
# /etc/nginx/conf.d (the entrypoint renders the config there), as deploy/compose.yaml does.

FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# The source maps are for an error tracker (vite.config.ts): none is served.
RUN npm run build && find dist -name '*.map' -delete

FROM nginxinc/nginx-unprivileged:1.29.8-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
# No packaged default site: the rendered template is the only server.
USER root
RUN rm -f /etc/nginx/conf.d/default.conf
USER nginx
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/snippets /etc/nginx/snippets
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080 8443
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/nginx-health || exit 1
