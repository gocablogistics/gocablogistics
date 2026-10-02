# syntax=docker/dockerfile:1

FROM python:3.11-slim AS bas

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app


RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*


COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/production.txt


COPY . .


RUN python manage.py collectstatic --noinput --settings=Gocabservices.settings.production

EXPOSE 8000


CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "Gocabservices.asgi:application"]