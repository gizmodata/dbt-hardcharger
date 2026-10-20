"""Shared fixtures.

The functional tests run against real ``hardcharger-server`` processes started from
``DBT_HARDCHARGER_TEST_SERVER_BINARY`` on free loopback ports (CI copies the binary out of
``ghcr.io/gizmodata/hardcharger:main``). Without the variable they fail; they never skip.

The main server serves TLS with a certificate from a throwaway CA, as a production server
would, so the suite runs over the adapter's default (TLS on, certificate verified). Its admin
password is random and contains ``:`` and ``@``. The servers get a clean environment: no
``HARDCHARGER_*`` variable from the shell running the tests reaches them, and their HOME is a
temporary directory, so a developer's real settings, credentials or DuckDB secrets can't leak
in.
"""

from __future__ import annotations

import dataclasses
import datetime
import ipaddress
import os
import secrets
import signal
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import pytest

pytest_plugins = ["dbt.tests.fixtures.project"]

SERVER_BINARY_ENV = "DBT_HARDCHARGER_TEST_SERVER_BINARY"
USERNAME = "dbt"
#: The main server's database file is dbt.duckdb, so its catalog is "dbt".
DATABASE = "dbt"


@dataclasses.dataclass
class Server:
    host: str
    port: int
    password: str
    process: subprocess.Popen
    workdir: Path
    log: Path
    certs: dict[str, Path] = dataclasses.field(default_factory=dict)

    @property
    def tls(self) -> bool:
        return "cert" in self.certs

    @property
    def username(self) -> str:
        return USERNAME

    @property
    def base_url(self) -> str:
        return f"{'https' if self.tls else 'http'}://{self.host}:{self.port}"

    @property
    def uri(self) -> str:
        """The server's hardcharger:// URI (plain HTTP unless it serves TLS)."""
        if self.tls:
            return f"hardcharger://{self.host}:{self.port}"
        return f"hardcharger://{self.host}:{self.port}?tls=false"

    def log_tail(self, lines: int = 40) -> str:
        try:
            return "\n".join(self.log.read_text(errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def profile(self, **overrides) -> dict:
        """A dbt profile target for this server, signed in as the admin with a password."""
        target = {
            "type": "hardcharger",
            "threads": 1,
            "host": self.host,
            "port": self.port,
            "user": self.username,
            "password": self.password,
            "database": DATABASE,
        }
        if self.tls:
            target["tls_root_certs"] = str(self.certs["ca"])
        else:
            target["tls"] = False
        target.update(overrides)
        return {key: value for key, value in target.items() if value is not None}

    def connect(self, **kwargs):
        """A DB-API connection to this server as its admin."""
        from adbc_driver_hardcharger import dbapi as hardcharger

        options = {"uri": self.uri, "username": self.username, "password": self.password}
        if self.tls:
            options["tls_root_certs"] = str(self.certs["ca"])
        options.update(kwargs)
        return hardcharger.connect(**options)


def free_port() -> int:
    with socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def server_binary() -> str:
    binary = os.environ.get(SERVER_BINARY_ENV)
    if not binary:
        pytest.fail(
            reason=f"set {SERVER_BINARY_ENV} to a hardcharger-server binary to run the "
            "functional tests (scripts/test-in-docker.sh does it for you)"
        )
    if not os.access(path=binary, mode=os.X_OK):
        pytest.fail(reason=f"{SERVER_BINARY_ENV}={binary} is not an executable")
    return binary


def clean_environment(home: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("HARDCHARGER_")}
    env["HOME"] = str(home)
    return env


def _wait_up(server: Server, timeout: float = 30) -> None:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        if server.process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url=f"{server.base_url}/warp", timeout=2, context=context):
                return
        except (urllib.error.URLError, OSError) as error:
            if "CERTIFICATE_REQUIRED" in str(error):
                return  # it requires client certificates and answered the handshake
            last_error = error
        time.sleep(0.1)
    stop_server(server=server)
    pytest.fail(
        reason=f"hardcharger-server did not answer at {server.base_url}/warp "
        f"({last_error}); its log:\n{server.log_tail()}"
    )


def start_server(
    workdir: Path,
    home: Path,
    extra_args: Optional[list[str]] = None,
    certs: Optional[dict[str, Path]] = None,
    database: str = ":memory:",
    port: Optional[int] = None,
) -> Server:
    """Start hardcharger-server in ``workdir`` on a free port (or ``port``); with ``certs``
    (from make_certificates) it serves TLS. ``{base_url}`` in an extra argument becomes the
    server's own base URL (at 127.0.0.1)."""
    binary = server_binary()
    certs = dict(certs or {})
    port = port or free_port()
    scheme = "https" if "cert" in certs else "http"
    args = [arg.replace("{base_url}", f"{scheme}://127.0.0.1:{port}") for arg in extra_args or []]
    if "cert" in certs:
        args += ["--tls-cert", str(certs["cert"]), "--tls-key", str(certs["key"])]
    workdir.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(nbytes=12) + ":p@ss:word"
    log = workdir / "hardcharger-server.log"
    with log.open(mode="ab") as out:
        process = subprocess.Popen(
            args=[
                binary,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--health-port",
                "0",
                "--database",
                database,
                "--admin-username",
                USERNAME,
                *args,
            ],
            env={**clean_environment(home=home), "HARDCHARGER_ADMIN_PASSWORD": password},
            cwd=workdir,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    server = Server(
        host="127.0.0.1",
        port=port,
        password=password,
        process=process,
        workdir=workdir,
        log=log,
        certs=certs,
    )
    _wait_up(server=server)
    return server


def stop_server(server: Server) -> None:
    if server.process.poll() is not None:
        return
    server.process.send_signal(signal.SIGTERM)
    server.process.send_signal(signal.SIGTERM)  # the second signal stops without draining
    try:
        server.process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        server.process.kill()


@pytest.fixture(scope="session")
def server_home(tmp_path_factory) -> Path:
    """HOME for every test server: DuckDB installs extensions under it (once per run), and
    finds no secrets of the developer's there."""
    return tmp_path_factory.mktemp("server-home")


@pytest.fixture(scope="session")
def certificates(tmp_path_factory) -> dict[str, Path]:
    """A throwaway CA, a server certificate for 127.0.0.1/localhost, and a client
    certificate each for analyst@example.com and stranger@example.com (``analyst``,
    ``analyst-key``, ``stranger``, ``stranger-key``)."""
    return make_certificates(
        out_dir=tmp_path_factory.mktemp("certs"),
        clients={"analyst": "analyst@example.com", "stranger": "stranger@example.com"},
    )


@pytest.fixture(scope="session")
def hardcharger_server(tmp_path_factory, server_home, certificates):
    """The TLS server most tests share; its database file is dbt.duckdb (catalog "dbt")."""
    server = start_server(
        workdir=tmp_path_factory.mktemp("server"),
        home=server_home,
        certs=certificates,
        database=f"{DATABASE}.duckdb",
    )
    yield server
    stop_server(server=server)


@pytest.fixture(scope="class")
def dbt_profile_target(hardcharger_server):
    return hardcharger_server.profile()


def make_certificates(out_dir: Path, clients: Optional[dict[str, str]] = None) -> dict[str, Path]:
    """A throwaway CA, and a server certificate for 127.0.0.1/localhost it signed.

    ``clients`` maps a name to an e-mail address: for each, a client certificate whose identity
    is that e-mail SAN, at ``paths[name]`` with its key at ``paths[name + "-key"]``.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(tz=datetime.timezone.utc)

    def name(common_name: str) -> x509.Name:
        return x509.Name(
            attributes=[x509.NameAttribute(oid=NameOID.COMMON_NAME, value=common_name)]
        )

    def pem_key(key) -> bytes:
        return key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    ca_key = ec.generate_private_key(curve=ec.SECP256R1())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name=name(common_name="dbt-hardcharger test CA"))
        .issuer_name(name=name(common_name="dbt-hardcharger test CA"))
        .public_key(key=ca_key.public_key())
        .serial_number(number=x509.random_serial_number())
        .not_valid_before(time=now - datetime.timedelta(minutes=5))
        .not_valid_after(time=now + datetime.timedelta(days=1))
        .add_extension(extval=x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            extval=x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            extval=x509.SubjectKeyIdentifier.from_public_key(public_key=ca_key.public_key()),
            critical=False,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )
    server_key = ec.generate_private_key(curve=ec.SECP256R1())
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(name=name(common_name="localhost"))
        .issuer_name(name=ca_cert.subject)
        .public_key(key=server_key.public_key())
        .serial_number(number=x509.random_serial_number())
        .not_valid_before(time=now - datetime.timedelta(minutes=5))
        .not_valid_after(time=now + datetime.timedelta(days=1))
        .add_extension(
            extval=x509.SubjectAlternativeName(
                general_names=[
                    x509.DNSName(value="localhost"),
                    x509.IPAddress(value=ipaddress.ip_address(address="127.0.0.1")),
                ]
            ),
            critical=False,
        )
        # Python 3.13+ verifies strictly (VERIFY_X509_STRICT), which needs the AKI.
        .add_extension(
            extval=x509.AuthorityKeyIdentifier.from_issuer_public_key(
                public_key=ca_key.public_key()
            ),
            critical=False,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )
    paths = {
        "ca": out_dir / "ca.pem",
        "cert": out_dir / "server.pem",
        "key": out_dir / "server-key.pem",
    }
    paths["ca"].write_bytes(data=ca_cert.public_bytes(encoding=serialization.Encoding.PEM))
    paths["cert"].write_bytes(data=server_cert.public_bytes(encoding=serialization.Encoding.PEM))
    paths["key"].write_bytes(data=pem_key(key=server_key))
    for client, email in (clients or {}).items():
        client_key = ec.generate_private_key(curve=ec.SECP256R1())
        client_cert = (
            x509.CertificateBuilder()
            .subject_name(name=name(common_name=client))
            .issuer_name(name=ca_cert.subject)
            .public_key(key=client_key.public_key())
            .serial_number(number=x509.random_serial_number())
            .not_valid_before(time=now - datetime.timedelta(minutes=5))
            .not_valid_after(time=now + datetime.timedelta(days=1))
            .add_extension(
                extval=x509.SubjectAlternativeName(general_names=[x509.RFC822Name(value=email)]),
                critical=False,
            )
            .add_extension(
                extval=x509.ExtendedKeyUsage(usages=[ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .add_extension(
                extval=x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    public_key=ca_key.public_key()
                ),
                critical=False,
            )
            .sign(private_key=ca_key, algorithm=hashes.SHA256())
        )
        paths[client] = out_dir / f"{client}.pem"
        paths[client + "-key"] = out_dir / f"{client}-key.pem"
        paths[client].write_bytes(
            data=client_cert.public_bytes(encoding=serialization.Encoding.PEM)
        )
        paths[client + "-key"].write_bytes(data=pem_key(key=client_key))
    return paths
