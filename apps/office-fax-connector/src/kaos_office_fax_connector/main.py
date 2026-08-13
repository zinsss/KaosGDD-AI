from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
import logging

from .server import ConnectorConfig, ConnectorHandler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8098)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = ConnectorConfig.from_env()
    ConnectorHandler.config = config
    server = ThreadingHTTPServer((args.host, args.port), ConnectorHandler)
    logging.getLogger(__name__).info("Office fax connector listening on %s:%s", args.host, args.port)
    server.serve_forever()
