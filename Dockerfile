FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for sound libs are heavy; skip audio in container unless needed.
# If you need voice_router, you may need to install extra system packages.

COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

# Create a non-root user
RUN useradd -ms /bin/bash appuser
USER appuser

EXPOSE 8000

# Default tokens dir; mount your tokens into /app/tokens in production
ENV GOOGLE_TOKENS_DIR=/app/tokens \
    DOWNLOAD_DIR=/app/downloads

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

