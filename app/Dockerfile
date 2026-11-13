FROM python:3.11-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistant/ assistant/
COPY prompts/ prompts/
COPY policies.yaml .

RUN useradd --uid 10001 --no-create-home app
USER 10001

ENV APP_DIR=/srv
EXPOSE 8000
CMD ["uvicorn", "assistant.main:app", "--host", "0.0.0.0", "--port", "8000"]
