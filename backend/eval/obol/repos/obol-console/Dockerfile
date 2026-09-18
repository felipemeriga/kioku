# ---------------------------------------------------------------------------
# obol-console — multi-stage build.
# Stage 1 builds the web SPA and the BFF. Stage 2 ships a slim runtime that
# serves the built SPA as static assets from the Express BFF.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

# Install workspace deps (root + shared + bff + web) using the lockfile.
COPY package.json package-lock.json* ./
COPY shared/package.json ./shared/
COPY bff/package.json ./bff/
COPY web/package.json ./web/
RUN npm install

# Copy sources and build every workspace.
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production

# Only ship what the BFF needs at runtime: its compiled output, the shared
# contracts, the built SPA, and production node_modules.
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/bff/dist ./bff/dist
COPY --from=build /app/bff/package.json ./bff/package.json
COPY --from=build /app/shared/dist ./shared/dist
COPY --from=build /app/web/dist ./web/dist

EXPOSE 8787
ENV STATIC_DIR=/app/web/dist
CMD ["node", "bff/dist/server.js"]
