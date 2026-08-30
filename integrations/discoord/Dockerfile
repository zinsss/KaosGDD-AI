FROM python:3.12-slim AS build
WORKDIR /build
COPY apps/governor ./governor
RUN python -m pip install --no-cache-dir --prefix=/install ./governor
COPY integrations/discoord ./discoord
RUN PYTHONPATH=/install/lib/python3.12/site-packages python -m pip install --no-cache-dir --prefix=/install ./discoord

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
    && apt-get install --no-install-recommends --yes fonts-dejavu-core libtiff-tools \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 kaos \
    && useradd --uid 10001 --gid kaos --no-create-home --shell /usr/sbin/nologin kaos
COPY --from=build /install /usr/local
COPY apps/governor/migrations /usr/local/share/kaos-governor/migrations
COPY apps/family-portal/fonts/SymbolsNerdFontMono-Regular.ttf /usr/local/share/kaos-governor/fonts/SymbolsNerdFontMono-Regular.ttf
RUN chmod -R a=rX /usr/local/share/kaos-governor/migrations
USER 10001:10001
EXPOSE 8097
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8097/health', timeout=3)"]
ENTRYPOINT ["kaosdiscoord"]

FROM build AS test
ENV PYTHONPATH=/install/lib/python3.12/site-packages
COPY apps/governor/tests /tests/governor
COPY apps/governor/migrations /tests/governor/migrations
COPY apps/calendar-adapter /tests/calendar-adapter
COPY integrations/discoord/tests /tests/discoord
CMD ["sh", "-c", "python -m unittest discover -s /tests/governor -v && python -m unittest discover -s /tests/discoord -v"]
