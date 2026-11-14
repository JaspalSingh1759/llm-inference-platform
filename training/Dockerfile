# The trainer image: every step of the training pipeline runs from it (prepare, validate, train, compare, publish).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    OMP_NUM_THREADS=2 \
    GIT_PYTHON_REFRESH=quiet
WORKDIR /app

# CPU-only PyTorch from PyTorch's own index (the default wheels can pull in GPU libraries, gigabytes we don't need).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.9.1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./
COPY tools/ ./tools/

# The commit the code came from (there is no .git folder in the image). Last, so a new commit doesn't
# invalidate the cached dependency layers above.
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

RUN useradd --uid 10001 --no-create-home trainer
USER 10001
