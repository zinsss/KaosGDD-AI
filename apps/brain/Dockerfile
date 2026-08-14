FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY apps/brain/pyproject.toml /tmp/brain/pyproject.toml
COPY apps/brain/src /tmp/brain/src
RUN pip install --no-cache-dir /tmp/brain

FROM base AS test
COPY apps/brain/tests /tmp/brain/tests
CMD ["python", "-m", "unittest", "discover", "-s", "/tmp/brain/tests"]

FROM base AS runtime
USER nobody
CMD ["kaos-brain"]
