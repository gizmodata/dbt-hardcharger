"""A small OpenID Connect identity provider for the browser sign-in tests: discovery, a JWKS,
and a token endpoint that trades one authorization code for a signed ID token.

The tests run it as its own process (``python mock_idp.py AUDIENCE CLIENT_ID CLIENT_SECRET``,
which prints its issuer URL): during a browser sign-in the test process is inside the driver
library, holding the GIL, while the server exchanges the code with this provider."""

from __future__ import annotations

import base64
import datetime
import http.server
import json
import threading
import urllib.parse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes(length=(value.bit_length() + 7) // 8, byteorder="big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class MockIdP:
    """Serves on 127.0.0.1 (a free port). The server under test is configured with
    ``audience``, ``client_id`` and ``client_secret``; ``valid_code`` and ``email`` decide what
    the next token request gets."""

    def __init__(self, audience: str, client_id: str, client_secret: str):
        self.audience = audience
        self.client_id = client_id
        self.client_secret = client_secret
        self.kid = "dbt-hardcharger-test-key"
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.valid_code = "code-ok"
        self.email = "analyst@example.com"
        idp = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def reply(self, status: int, body) -> None:
                data = json.dumps(obj=body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = urllib.parse.urlparse(url=self.path).path
                if path == "/.well-known/openid-configuration":
                    self.reply(
                        status=200,
                        body={
                            "issuer": idp.issuer,
                            "jwks_uri": f"{idp.issuer}/jwks",
                            "authorization_endpoint": f"{idp.issuer}/authorize",
                            "token_endpoint": f"{idp.issuer}/token",
                        },
                    )
                elif path == "/jwks":
                    self.reply(status=200, body={"keys": [idp.jwk()]})
                else:
                    self.reply(status=404, body={"error": "not_found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                form = dict(urllib.parse.parse_qsl(qs=self.rfile.read(length).decode()))
                if urllib.parse.urlparse(url=self.path).path != "/token":
                    return self.reply(status=404, body={"error": "not_found"})
                if (
                    form.get("client_id") != idp.client_id
                    or form.get("client_secret") != idp.client_secret
                ):
                    return self.reply(status=401, body={"error": "invalid_client"})
                if form.get("code") != idp.valid_code:
                    return self.reply(
                        status=400,
                        body={
                            "error": "invalid_grant",
                            "error_description": "the code is not valid",
                        },
                    )
                self.reply(
                    status=200,
                    body={
                        "access_token": "unused",
                        "token_type": "Bearer",
                        "id_token": idp.id_token(),
                    },
                )

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.issuer = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def jwk(self) -> dict:
        public = self.key.public_key().public_numbers()
        return {
            "kty": "RSA",
            "kid": self.kid,
            "alg": "RS256",
            "use": "sig",
            "n": _b64url_uint(value=public.n),
            "e": _b64url_uint(value=public.e),
        }

    def id_token(self) -> str:
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": self.email,
            "email": self.email,
            "iat": now,
            "exp": now + datetime.timedelta(minutes=5),
        }
        return jwt.encode(
            payload=payload, key=self.key, algorithm="RS256", headers={"kid": self.kid}
        )

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


if __name__ == "__main__":
    import sys

    provider = MockIdP(audience=sys.argv[1], client_id=sys.argv[2], client_secret=sys.argv[3])
    print(provider.issuer, flush=True)
    provider.thread.join()
