FROM python:3.12-slim
WORKDIR /app
COPY schemas ./schemas
COPY packages/common ./packages/common
COPY packages/sim ./packages/sim
COPY packages/fab ./packages/fab
COPY packages/calib ./packages/calib
COPY packages/rig ./packages/rig
COPY apps/api ./apps/api
# editable installs: strandbeest_common finds ./schemas by walking up from its source file
RUN pip install --no-cache-dir -e packages/common -e packages/sim -e packages/fab -e packages/calib -e packages/rig -e apps/api
ARG GIT_SHA=unknown
ENV STRANDBEEST_CODE_VERSION=$GIT_SHA
ENV STRANDBEEST_DATA=/data STRANDBEEST_HOST=0.0.0.0 STRANDBEEST_PORT=8000
VOLUME /data
EXPOSE 8000
CMD ["strandbeest-api"]
