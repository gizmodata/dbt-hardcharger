"""The tests' HTTP API root on servers from before and after the protocol's rename, against
stand-in servers that answer discovery the way each one does."""

from __future__ import annotations

import http.server
import json
import ssl
import threading

import pytest

from tests.support.legacy_protocol import api_root


def stand_in(documents: dict[str, dict]):
    """An HTTP server on a free loopback port answering GET ``path`` with ``documents[path]``,
    and 404 for every other path."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            document = documents.get(self.path)
            body = json.dumps(obj=document or {"status": 404}).encode()
            self.send_response(code=200 if document else 404)
            self.send_header(keyword="Content-Type", value="application/json")
            self.send_header(keyword="Content-Length", value=str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = http.server.ThreadingHTTPServer(
        server_address=("127.0.0.1", 0), RequestHandlerClass=Handler
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def serve():
    servers = []

    def start(documents: dict[str, dict]) -> str:
        servers.append(stand_in(documents=documents))
        return f"http://127.0.0.1:{servers[-1].server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_current_server(serve):
    base_url = serve(documents={"/chargewire": {"protocol": "chargewire"}})
    assert api_root(base_url=base_url, context=ssl.create_default_context()) == "/chargewire/v1"


def test_server_from_before_the_rename(serve):
    """Hardcharger 2.2.0 and older: 404 at /chargewire, discovery under the old root."""
    base_url = serve(documents={"/warp": {"protocol": "warp-sql"}})
    assert api_root(base_url=base_url, context=ssl.create_default_context()) == "/warp/v1"


def test_not_a_chargewire_server(serve):
    base_url = serve(documents={})
    with pytest.raises(AssertionError, match="does not serve the Chargewire protocol"):
        api_root(base_url=base_url, context=ssl.create_default_context())
