# Not wired into infra/docker-compose.yml's default services on purpose — for day-to-day
# development, `npm run dev` (hot reload) is faster than rebuilding a container on every
# change. This Dockerfile is what Phase 7's CI/CD (docs/ROADMAP.md) builds and ships.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/public ./public
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json

EXPOSE 3000
CMD ["npm", "start"]
