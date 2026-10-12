FROM python:3.11-slim

WORKDIR /app

COPY gamedb /app/gamedb
COPY data/reference /app/data/reference

CMD ["python", "-m", "gamedb", "--help"]
