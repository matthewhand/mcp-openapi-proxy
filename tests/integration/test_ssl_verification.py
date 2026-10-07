"""
Integration tests for SSL certificate verification using a self-signed certificate.
This test launches a simple HTTPS server with an invalid (self-signed) certificate.
It then verifies that fetching the OpenAPI spec fails when SSL verification is enabled,
and succeeds when the IGNORE_SSL_SPEC environment variable is set.
"""

import os
import ssl
import threading
import http.server
import pytest
from mcp_openapi_proxy.utils import fetch_openapi_spec


class SimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"dummy": "spec"}')


@pytest.fixture
def ssl_server(tmp_path):
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    # Generate a self-signed certificate using openssl (ensure openssl is installed)
    os.system(
        f"openssl req -x509 -newkey rsa:2048 -nodes -keyout {key_file} -out {cert_file} -days 1 -subj '/CN=localhost'"
    )
    server_address = ("localhost", 0)
    httpd = http.server.HTTPServer(server_address, SimpleHTTPRequestHandler)
    # Wrap socket in SSL with the self-signed certificate
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    port = httpd.socket.getsockname()[1]
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"https://localhost:{port}"
    httpd.shutdown()
    thread.join()


def test_fetch_openapi_spec_invalid_cert_without_ignore(ssl_server):
    # Without disabling SSL verification, fetch_openapi_spec should return an error message indicating failure.
    result = fetch_openapi_spec(ssl_server)
    assert result is None


def test_fetch_openapi_spec_invalid_cert_with_ignore(monkeypatch, ssl_server):
    # Set the environment variable to disable SSL verification.
    monkeypatch.setenv("IGNORE_SSL_SPEC", "true")
    spec = fetch_openapi_spec(ssl_server)
    # The response should contain "dummy" because our server returns {"dummy": "spec"}.
    import json

    if isinstance(spec, dict):
        spec_text = json.dumps(spec)
    else:
        spec_text = spec or ""
    assert "dummy" in spec_text
    monkeypatch.delenv("IGNORE_SSL_SPEC", raising=False)
