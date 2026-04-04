FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install system dependencies (including curl + unzip for Deno)
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

# Add Deno to PATH
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

# (Optional) Verify installation
RUN deno --version

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -U -r requirements.txt

# Copy project files
COPY . /app

CMD ["python", "main.py"]