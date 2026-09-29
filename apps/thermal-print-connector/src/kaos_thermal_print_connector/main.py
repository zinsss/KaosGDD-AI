from __future__ import annotations

from http.server import ThreadingHTTPServer
import logging
import os

from .server import ConnectorConfig, ConnectorHandler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    host = os.environ.get("THERMAL_CONNECTOR_HOST", "127.0.0.1")
    port = int(os.environ.get("THERMAL_CONNECTOR_PORT", "8100") or "8100")
    ConnectorHandler.config = ConnectorConfig.from_env()
    server = ThreadingHTTPServer((host, port), ConnectorHandler)
    logging.getLogger(__name__).info("Thermal print connector listening on %s:%s", host, port)
    server.serve_forever()
