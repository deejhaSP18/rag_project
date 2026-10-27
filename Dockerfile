# syntax=docker/dockerfile:1

# ---- 1. build the React app --------------------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. the app: FastAPI serving the API and the built UI --------------------------------
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    RAG_MODEL_CACHE=/opt/rag-models
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Bake the re-ranker model into the image so the first start works offline.
# Keep this name in step with RERANK_MODEL in src/config.py.
ARG RERANK_MODEL=Xenova/ms-marco-MiniLM-L-6-v2
RUN python -c "from fastembed.rerank.cross_encoder import TextCrossEncoder as T; T('${RERANK_MODEL}', cache_dir='/opt/rag-models')"

COPY src ./src
COPY scripts ./scripts
COPY --from=web /web/dist ./frontend/dist

# Documents and the index live in volumes mounted at /app/data and /app/storage.
RUN useradd --create-home --uid 1000 rag \
    && mkdir -p /app/data /app/storage \
    && chown -R rag:rag /app /opt/rag-models
USER rag

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
