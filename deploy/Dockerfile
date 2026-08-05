# Backend image: API, RQ workers, outbox and lifecycle all run this image
# with different commands. Build context is the REPO ROOT (see compose file).
FROM python:3.12-slim

# ghostscript: the optional CMYK conversion stage for print PDFs
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/scripts ./scripts
# Editable install keeps the source tree (incl. the repo-pinned render fonts)
# exactly as laid out here.
RUN pip install --no-cache-dir -e .

# The whole frontend ships in the image and is served by the API — the
# editor at /editor (EDITOR_DIR) and the marketing site, all five language
# versions, at / (SITE_DIR). One origin, zero CORS configuration.
COPY editor /app/editor
COPY index.html /app/site/index.html
COPY assets /app/site/assets
COPY ru /app/site/ru
COPY uz /app/site/uz
COPY uz-cyrl /app/site/uz-cyrl
COPY kaa /app/site/kaa

RUN useradd -m appuser && chown -R appuser /app
USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
