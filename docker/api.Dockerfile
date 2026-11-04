FROM rust:1.95.0-slim-bookworm AS rust-toolchain

FROM python:3.12-slim-bookworm AS kernel-build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY crates/beest-kernel ./crates/beest-kernel
# Compile the native extension for the same Python/glibc as the runtime image.
# Read-only mounts avoid duplicating the toolchain into extra image layers.
RUN --mount=from=rust-toolchain,source=/usr/local/cargo,target=/usr/local/cargo,ro \
    --mount=from=rust-toolchain,source=/usr/local/rustup,target=/usr/local/rustup,ro \
    CARGO_HOME=/tmp/beest-cargo RUSTUP_HOME=/usr/local/rustup PATH=/usr/local/cargo/bin:$PATH \
    pip wheel --no-cache-dir --no-deps --wheel-dir /wheels ./crates/beest-kernel \
    && rm -rf /tmp/beest-cargo /build/target

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=kernel-build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY schemas ./schemas
COPY contracts ./contracts
COPY packages/common ./packages/common
COPY packages/sim ./packages/sim
COPY packages/fab ./packages/fab
COPY packages/calib ./packages/calib
COPY packages/rig ./packages/rig
COPY packages/opt ./packages/opt
COPY apps/api ./apps/api
COPY scripts/smoke-installed.py ./scripts/smoke-installed.py
# editable installs: strandbeest_common finds ./schemas by walking up from its source file
RUN pip install --no-cache-dir -e packages/common -e packages/sim -e packages/fab -e packages/calib -e packages/rig -e packages/opt -e apps/api
ARG GIT_SHA=unknown
ENV STRANDBEEST_CODE_VERSION=$GIT_SHA
ENV STRANDBEEST_DATA=/data STRANDBEEST_HOST=0.0.0.0 STRANDBEEST_PORT=8000
VOLUME /data
EXPOSE 8000
CMD ["strandbeest-api"]
