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

# The editor is served by the API at /editor (EDITOR_DIR) — same origin as
# the API, so the editor works with zero CORS configuration.
COPY editor /app/editor

RUN useradd -m appuser && chown -R appuser /app
USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
