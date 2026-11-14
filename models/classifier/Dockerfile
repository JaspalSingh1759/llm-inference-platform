FROM python:3.11-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# No model in the image: the init container (fetch_model.py) downloads a published version at startup.
COPY server.py fetch_model.py ./
ENV MODEL_DIR=/model

# Non-root user with a fixed numeric ID, so Kubernetes can verify runAsNonRoot.
RUN useradd --uid 10001 --no-create-home app
USER 10001

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
