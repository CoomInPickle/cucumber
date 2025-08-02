FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install system dependencies including fonts
RUN apt-get update && apt-get install -y \
    git \
    libffi-dev \
    ffmpeg \
    fonts-dejavu-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -U -r requirements.txt

# Copy project files
COPY . /app

CMD ["python", "main.py"]
