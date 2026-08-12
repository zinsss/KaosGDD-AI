FROM python:3.12-slim AS build
WORKDIR /build
COPY apps/governor ./governor
RUN python -m pip install --no-cache-dir --prefix=/install ./governor
COPY integrations/discord ./discord
RUN PYTHONPATH=/install/lib/python3.12/site-packages python -m pip install --no-cache-dir --prefix=/install ./discord

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 10001 kaos && useradd --uid 10001 --gid kaos --no-create-home --shell /usr/sbin/nologin kaos
COPY --from=build /install /usr/local
USER 10001:10001
EXPOSE 8097
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8097/health', timeout=3)"]
ENTRYPOINT ["kaos-governor-discord"]

FROM build AS test
ENV PYTHONPATH=/install/lib/python3.12/site-packages
COPY apps/governor/tests /tests/governor
COPY integrations/discord/tests /tests/discord
CMD ["sh", "-c", "python -m unittest discover -s /tests/governor -v && python -m unittest discover -s /tests/discord -v"]
