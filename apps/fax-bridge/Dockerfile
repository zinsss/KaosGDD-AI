FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        fonts-nanum \
        ghostscript \
        hylafax-client \
        libtiff-tools \
    && rm -rf /var/lib/apt/lists/* \
    && test -f /usr/share/fonts/truetype/nanum/NanumMyeongjo.ttf

FROM base AS test
WORKDIR /app
COPY apps/fax-bridge/src /app/src
COPY apps/fax-bridge/tests /app/tests
ENV PYTHONPATH=/app/src
RUN python -m unittest discover -s /app/tests

FROM base AS runtime
RUN useradd --system --uid 10002 --gid users --home /nonexistent --shell /usr/sbin/nologin faxbridge
WORKDIR /app
COPY apps/fax-bridge/src /app/src
ENV PYTHONPATH=/app/src
USER faxbridge
CMD ["python", "-m", "kaos_fax_bridge.main"]
