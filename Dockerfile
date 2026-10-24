# Stage 1: the DWG converter (acad-ts, MIT) with its Node runtime
FROM node:22-slim AS dwg
WORKDIR /dwg
COPY dwg/package.json dwg/package-lock.json ./
RUN npm ci --omit=dev
COPY dwg/dxf2dwg.mjs dwg/patch-acad.mjs ./
RUN node patch-acad.mjs

# Stage 2: the Python worker
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 FILES_DIR=/data/files \
    NODE_BIN=/usr/local/bin/node DWG_SCRIPT=/app/dwg/dxf2dwg.mjs
WORKDIR /app
# the Node binary links against libstdc++
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY --from=dwg /usr/local/bin/node /usr/local/bin/node
COPY --from=dwg /dwg ./dwg
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
RUN mkdir -p /data/files && node --version
EXPOSE 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=*"]
