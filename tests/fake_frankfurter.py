"""A local HTTP server that answers like the Frankfurter /v2/rates endpoint."""

import json
import threading
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_RATES = {"IDR": 105.0, "THB": 0.23}


def rate_for(quote: str, day: date) -> float:
    """A deterministic rate that drifts by day, so revisions and gaps are visible in tests."""
    return round(BASE_RATES[quote] * (1 + (day.toordinal() % 10) / 1000), 5)


class FakeFrankfurter:
    """Publishes a rate for every weekday up to today, like the ECB feed behind the real API."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                params = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                outer.requests.append(params)
                start = date.fromisoformat(params["from"])
                end = min(date.fromisoformat(params["to"]), datetime.now(UTC).date())
                rows = []
                day = start
                while day <= end:
                    if day.weekday() < 5:
                        for quote in params["quotes"].split(","):
                            rows.append(
                                {
                                    "date": day.isoformat(),
                                    "base": params["base"],
                                    "quote": quote,
                                    "rate": rate_for(quote, day),
                                }
                            )
                    day += timedelta(days=1)
                body = json.dumps(rows).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/v2/rates"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
