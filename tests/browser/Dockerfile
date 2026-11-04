# Fixed Debian 12 / Node 22 base; test-browser.sh uses amd64 on every host.
FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da
WORKDIR /work
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/beest-browsers
# Playwright 1.64.1 pins Chromium 156.0.8078.4, headless-shell revision 1248.
# Install only Chromium's shell, not three complete browser distributions.
RUN npm install --no-save --no-package-lock @playwright/test@1.64.1 \
    && npx playwright install --with-deps --only-shell chromium \
    && apt-get install -y --no-install-recommends \
       fonts-noto-cjk=1:20220127+repack1-1 fonts-liberation=1:1.07.4-11 \
    && dpkg-query -W > /opt/beest-browser-packages.txt \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/work/node_modules/.bin/playwright"]
