# Multi-stage build: compile the Vite app, then serve the static output with nginx.
FROM node:20-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Build-time args let docker-compose / CI bake the right backend URL and key
# into the static bundle (Vite inlines import.meta.env.* at build time).
ARG VITE_API_URL=http://localhost:8000
ARG VITE_API_KEY=
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_API_KEY=${VITE_API_KEY}

RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
# Single-page app: fall back to index.html for client-side routing.
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
