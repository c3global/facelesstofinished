FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY cloudrun/requirements-dispatcher.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt
COPY backend/render_dispatch.py /app/render_dispatch.py
COPY cloudrun/dispatcher/app.py /app/dispatcher_app.py

CMD ["sh", "-c", "uvicorn dispatcher_app:app --host 0.0.0.0 --port ${PORT:-8080}"]
