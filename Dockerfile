FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

EXPOSE 8000
# Load posts.csv into Postgres and Elasticsearch (only on the first start), then serve the API.
CMD ["sh", "-c", "python -m app.loader && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
