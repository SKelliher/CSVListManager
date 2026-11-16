"""Command-line entry point for CSVListManager."""

from __future__ import annotations

import argparse

from .app import Application
from .errors import CSVListManagerError
from .server import make_server


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Local CSVListManager service")
    result.add_argument("--config", default="config.yaml", help="application YAML configuration")
    result.add_argument("--host", default="127.0.0.1", help="IPv4 loopback address (default: 127.0.0.1)")
    result.add_argument("--port", type=int, default=8765, help="listening port (default: 8765; 0 selects a free port)")
    result.add_argument("--check", action="store_true", help="validate all configuration and data, then exit")
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        application = Application.from_config(arguments.config)
        if arguments.check:
            print(f"Configuration valid: {len(application.config.repositories)} repositories")
            return 0
        server = make_server(application, arguments.host, arguments.port)
    except CSVListManagerError as error:
        parser().error(error.message)
    host, port = server.server_address
    print(f"CSVListManager listening at http://{host}:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping CSVListManager")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
