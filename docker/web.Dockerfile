FROM node:22-slim AS build
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json ./
COPY packages/core ./packages/core
COPY apps/web-demo ./apps/web-demo
RUN pnpm install --frozen-lockfile
ARG VITE_API_URL=http://127.0.0.1:8000
ENV VITE_API_URL=$VITE_API_URL
RUN pnpm --filter @strandbeest/web-demo build

FROM nginx:alpine
COPY --from=build /app/apps/web-demo/dist /usr/share/nginx/html
EXPOSE 80
