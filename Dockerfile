FROM python:3.11 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN pip install poetry
RUN poetry config virtualenvs.in-project true
COPY pyproject.toml poetry.lock ./
RUN poetry install
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y fonts-dejavu
COPY --from=builder /app/.venv .venv/
COPY . .
CMD ["/app/.venv/bin/gunicorn", "--bind", "[::]:8080", "--workers", "4", "--threads", "2", "--worker-class", "gthread", "wsgi:app"]
