FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    git \
    libffi-dev \
    ffmpeg \
    fonts-dejavu-core \
    curl \
    unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"
RUN deno --version

COPY requirements.txt /app/
RUN pip install --no-cache-dir -U -r requirements.txt

COPY . /app

# config_defaults holds the bundled defaults. The real config/ is a volume mount.
# entrypoint.sh copies defaults into the volume on first run.
RUN cp -r /app/config /app/config_defaults

RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
