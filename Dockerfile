FROM python:3.11-slim AS postgres-runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app


FROM postgres-runtime AS deriver

COPY requirements-derive.txt /app/requirements-derive.txt
RUN pip install --no-cache-dir -r /app/requirements-derive.txt

COPY gamedb/__init__.py gamedb/config.py gamedb/database.py /app/gamedb/
COPY gamedb/derive /app/gamedb/derive
COPY reference /app/reference
COPY derive.yml /app/derive.yml

CMD ["python", "-m", "gamedb.derive", "--plan"]


FROM postgres-runtime AS catalog-builder

COPY requirements-catalog.txt /app/requirements-catalog.txt
RUN pip install --no-cache-dir -r /app/requirements-catalog.txt

COPY gamedb/__init__.py gamedb/config.py /app/gamedb/
COPY gamedb/catalog /app/gamedb/catalog
COPY sql/layers/catalog /app/sql/layers/catalog
COPY sql/layers/facts /app/sql/layers/facts
COPY sql/layers/identity /app/sql/layers/identity
COPY sql/layers/scoring /app/sql/layers/scoring
COPY pipeline.yml /app/pipeline.yml

CMD ["python", "-m", "gamedb.catalog", "rebuild", "--plan"]


FROM postgres-runtime AS explorer

COPY gamedb/__init__.py gamedb/config.py /app/gamedb/
COPY gamedb/explorer /app/gamedb/explorer
COPY sql/queries /app/sql/queries

EXPOSE 8000
CMD ["python", "-m", "gamedb.explorer", "--host", "0.0.0.0", "--port", "8000"]
