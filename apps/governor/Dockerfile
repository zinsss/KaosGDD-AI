FROM python:3.12-slim AS build
WORKDIR /build
COPY apps/governor ./governor
RUN python -m pip install --no-cache-dir --prefix=/install ./governor

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
    && apt-get install --no-install-recommends --yes libtiff-tools \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 kaos \
    && useradd --uid 10001 --gid kaos --no-create-home --shell /usr/sbin/nologin kaos
COPY --from=build /install /usr/local
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 CMD ["kaos-governor-worker", "--check"]
ENTRYPOINT ["kaos-governor-worker"]
