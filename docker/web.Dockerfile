FROM rust:1.95.0-slim-bookworm AS kernel-build
RUN rustup target add wasm32-unknown-unknown
RUN --mount=type=tmpfs,target=/tmp \
    cargo install --locked --version 0.2.105 --jobs 2 --target-dir /tmp/beest-cli-build wasm-bindgen-cli \
    && rm -rf /usr/local/cargo/registry
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY crates/beest-kernel ./crates/beest-kernel
COPY scripts/build-kernel-wasm.sh ./scripts/build-kernel-wasm.sh
RUN ./scripts/build-kernel-wasm.sh

FROM node:22-slim AS build
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json ./
COPY packages/core ./packages/core
COPY packages/sim-web ./packages/sim-web
COPY --from=kernel-build /app/crates/beest-kernel/generated ./crates/beest-kernel/generated
# the front end imports the schemas and the contract corpora (examples, scenes) directly
COPY schemas ./schemas
COPY contracts ./contracts
COPY apps/web-demo ./apps/web-demo
RUN pnpm install --frozen-lockfile
ARG VITE_API_URL=http://127.0.0.1:8000
ENV VITE_API_URL=$VITE_API_URL
RUN pnpm --filter @strandbeest/web-demo build

FROM nginx:alpine
COPY --from=build /app/apps/web-demo/dist /usr/share/nginx/html
EXPOSE 80
