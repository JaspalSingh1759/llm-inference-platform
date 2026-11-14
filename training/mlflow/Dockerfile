# MLflow tracking server + registry. Database: PostgreSQL. Files: the S3 store (proxied, so clients
# need no S3 credentials of their own to log models).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
RUN pip install --no-cache-dir mlflow==3.1.4 sqlalchemy==2.0.36 psycopg2-binary==2.9.10 boto3==1.38.0
RUN useradd --uid 10001 --no-create-home mlflow
USER 10001
EXPOSE 5000
