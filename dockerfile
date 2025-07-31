FROM python:3.9-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install system dependencies including git
RUN apt-get update && \
    apt-get install -y git libffi-dev ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "bot.py"]
