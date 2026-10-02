# Infosphere — production container.
#   docker build -t infosphere .
#   docker run -p 8000:8000 -v infosphere-data:/data --env-file .env infosphere
# Put it behind an HTTPS reverse proxy / platform load balancer (TLS ends there).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INFOSPHERE_ENV=production \
    INFOSPHERE_INSTANCE=/data \
    TRUST_PROXY=1 \
    HOST=0.0.0.0 \
    PORT=8000

# ffmpeg: voice-input conversion. espeak-ng: offline fallback voice (optional).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 infosphere \
 && mkdir -p /data \
 && chown -R infosphere /data /app/data/qa
USER infosphere

EXPOSE 8000
VOLUME ["/data"]
# First start downloads the speech model and trains the chatbot — give it time.
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

CMD ["python", "app.py"]
