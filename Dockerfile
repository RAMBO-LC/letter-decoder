FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build
COPY app/package*.json ./
RUN npm ci
COPY app/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ENGINE_MODE=mock \
    OLLAMA_HOST=http://ollama:11434
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    libgl1 \
    libglib2.0-0 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY --from=frontend-build /build/dist ./dev-ui/
COPY pyproject.toml ./
COPY api/ ./api/
COPY engine/ ./engine/
COPY contract/ ./contract/
COPY notices/ ./notices/
COPY templates/ ./templates/
RUN pip install --upgrade pip && pip install \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "pydantic>=2.10.0" \
    "pydantic-settings>=2.7.0" \
    "python-multipart>=0.0.12" \
    "python-magic>=0.4.27" \
    "pillow>=11.0.0" \
    "opencv-python-headless>=4.10.0" \
    "pytesseract>=0.3.10" \
    "dateparser>=1.2.0" \
    "regex>=2024.11.0" \
    "pyyaml>=6.0.2" \
    "httpx>=0.28.0" \
    "ollama>=0.4.0" \
    "sqlalchemy>=2.0.35" \
    "cryptography>=43.0.0" \
    "jsonschema>=4.23.0" \
    "rich>=13.9.0" \
    "typer>=0.15.0" \
    "PyMuPDF" \
    "eval_type_backport"
RUN mkdir -p data/uploads dev-ui
EXPOSE 8000
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
