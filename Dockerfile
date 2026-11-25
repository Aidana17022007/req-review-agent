FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 reqlens
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=reqlens:reqlens . .
USER reqlens
# Документ и отчёт монтируются в /work: docker run --rm -v "$PWD:/work" --env-file .env reqlens docs/requirements.md reports/report.md
WORKDIR /work
ENTRYPOINT ["python", "/app/review.py"]
