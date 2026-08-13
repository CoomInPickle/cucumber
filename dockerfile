FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . /app

# Runtime config is mounted separately by Docker Compose. Only safe defaults
# are bundled into the image; credentials/cookies must never be baked in.
RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
