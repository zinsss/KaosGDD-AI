FROM python:3.12-slim AS build
WORKDIR /build
COPY apps/thermal-print-connector ./thermal-print-connector
RUN python -m pip install --no-cache-dir --prefix=/install ./thermal-print-connector

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
    && apt-get install --no-install-recommends --yes cups-client poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 kaos \
    && useradd --uid 10001 --gid kaos --no-create-home --shell /usr/sbin/nologin kaos
COPY --from=build /install /usr/local
USER 10001:10001
EXPOSE 8100
ENTRYPOINT ["kaos-thermal-print-connector"]

FROM build AS test
ENV PYTHONPATH=/install/lib/python3.12/site-packages
COPY apps/thermal-print-connector/tests /tests/thermal-print-connector
CMD ["python", "-m", "unittest", "discover", "-s", "/tests/thermal-print-connector", "-v"]
