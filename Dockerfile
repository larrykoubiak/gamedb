FROM python:3.11-slim AS postgres-runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app


FROM postgres-runtime AS loader

COPY requirements-load.txt /app/requirements-load.txt
RUN pip install --no-cache-dir -r /app/requirements-load.txt

COPY gamedb/__init__.py gamedb/config.py /app/gamedb/
COPY gamedb/load /app/gamedb/load
COPY data/reference /app/data/reference
COPY sql/layers /app/sql/layers
COPY pipeline.yml /app/pipeline.yml

CMD ["python", "-m", "gamedb.load", "rebuild", "--plan"]


FROM postgres-runtime AS explorer

COPY gamedb/__init__.py gamedb/config.py /app/gamedb/
COPY gamedb/explorer /app/gamedb/explorer
COPY sql/queries /app/sql/queries

EXPOSE 8000
CMD ["python", "-m", "gamedb.explorer", "--host", "0.0.0.0", "--port", "8000"]
