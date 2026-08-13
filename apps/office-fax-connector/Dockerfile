FROM python:3.12-slim AS build
WORKDIR /build
COPY apps/office-fax-connector ./office-fax-connector
RUN python -m pip install --no-cache-dir --prefix=/install ./office-fax-connector

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
    && apt-get install --no-install-recommends --yes libtiff-tools \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 kaos \
    && useradd --uid 10001 --gid kaos --no-create-home --shell /usr/sbin/nologin kaos
COPY --from=build /install /usr/local
USER 10001:10001
EXPOSE 8098
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import os,urllib.request; token=open('/run/secrets/fax_connector_token', encoding='utf-8').read().strip(); req=urllib.request.Request('http://127.0.0.1:8098/health', headers={'Authorization':'Bearer '+token}); urllib.request.urlopen(req, timeout=3)"]
ENTRYPOINT ["kaos-office-fax-connector", "--host", "0.0.0.0", "--port", "8098"]

FROM build AS test
ENV PYTHONPATH=/install/lib/python3.12/site-packages
COPY apps/office-fax-connector/tests /tests/office-fax-connector
CMD ["python", "-m", "unittest", "discover", "-s", "/tests/office-fax-connector", "-v"]
