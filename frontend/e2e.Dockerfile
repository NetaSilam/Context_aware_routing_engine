FROM mcr.microsoft.com/playwright:v1.50.0-noble

WORKDIR /work
RUN npm install --global playwright@1.50.0 \
  && mkdir /work/node_modules \
  && ln -s "$(npm root -g)/playwright" /work/node_modules/playwright
COPY e2e ./e2e

CMD ["node", "/work/e2e/route-journey.mjs"]
