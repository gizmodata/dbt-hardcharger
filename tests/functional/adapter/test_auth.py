"""Every way to sign in and to reach the server, against real servers: TLS (the default,
verified against a CA), plain HTTP (``tls: false``), a password, an access token, a client
certificate (mutual TLS) and the server's browser sign-in. Each refusal test checks the
reason the server or driver gives, and has a twin that signs in."""

import json
import pathlib
import ssl
import subprocess
import sys
import urllib.request

import pytest
from dbt.adapters.contracts.connection import Connection
from dbt.adapters.exceptions import FailedToConnectError
from dbt.tests.util import relation_from_name, run_dbt

from dbt.adapters.hardcharger.connections import (
    HardchargerConnectionManager,
    HardchargerCredentials,
)
from tests.conftest import start_server, stop_server
from tests.support.legacy_protocol import api_root

WHOAMI_SQL = """
{{ config(materialized='table') }}
select HARDCHARGER_USER() as signed_in_as, current_database() as catalog_name
"""

SUPPORT = pathlib.Path(__file__).resolve().parents[2] / "support"


def signed_in_as(project) -> tuple:
    relation = relation_from_name(adapter=project.adapter, name="whoami")
    return project.run_sql(sql=f"select signed_in_as, catalog_name from {relation}", fetch="one")


def open_connection(**credentials) -> Connection:
    connection = Connection(
        type="hardcharger",
        name="auth-test",
        credentials=HardchargerCredentials(**credentials),
    )
    return HardchargerConnectionManager.open(connection=connection)


def issue_token(server) -> str:
    """An access token from the server's password grant (Chargewire's /chargewire/v1/auth/token)."""
    context = ssl.create_default_context(cafile=str(server.certs["ca"]))
    root = api_root(base_url=server.base_url, context=context)
    request = urllib.request.Request(
        url=f"{server.base_url}{root}/auth/token",
        data=json.dumps(
            obj={
                "grant_type": "password",
                "username": server.username,
                "password": server.password,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(url=request, context=context, timeout=10) as response:
        return json.load(fp=response)["access_token"]


class WhoAmI:
    @pytest.fixture(scope="class")
    def models(self):
        return {"whoami.sql": WHOAMI_SQL}


# --- TLS, the default ------------------------------------------------------------------------


class TestTlsVerifiedByDefault(WhoAmI):
    """The suite's own profile: TLS on (not set), the server's certificate verified against
    tls_root_certs, signed in with a password containing ':' and '@'."""

    def test_password_over_tls(self, project, hardcharger_server):
        assert ":" in hardcharger_server.password and "@" in hardcharger_server.password
        run_dbt(args=["run"])
        assert signed_in_as(project=project) == ("dbt", "dbt")


def test_an_untrusted_server_certificate_is_refused(hardcharger_server):
    # The twin of TestTlsVerifiedByDefault: the same server, without its CA.
    with pytest.raises(expected_exception=FailedToConnectError) as error:
        open_connection(
            host=hardcharger_server.host,
            port=hardcharger_server.port,
            username=hardcharger_server.username,
            password=hardcharger_server.password,
            database="dbt",
        )
    # Go's wording: Linux (CI), macOS.
    reasons = ("certificate signed by unknown authority", "certificate is not trusted")
    assert any(reason in str(error.value) for reason in reasons), str(error.value)


def test_tls_skip_verify_connects_without_the_ca(hardcharger_server):
    connection = open_connection(
        host=hardcharger_server.host,
        port=hardcharger_server.port,
        username=hardcharger_server.username,
        password=hardcharger_server.password,
        database="dbt",
        tls_skip_verify=True,
    )
    connection.handle.close()


def test_a_wrong_password_is_refused(hardcharger_server):
    with pytest.raises(expected_exception=FailedToConnectError) as error:
        open_connection(
            host=hardcharger_server.host,
            port=hardcharger_server.port,
            username=hardcharger_server.username,
            password="not-the-password",
            database="dbt",
            tls_root_certs=str(hardcharger_server.certs["ca"]),
        )
    assert "the user name or password is not correct (invalid_credentials" in str(error.value)


# --- plain HTTP (tls: false) -------------------------------------------------------------------


@pytest.fixture(scope="module")
def plain_server(tmp_path_factory, server_home):
    server = start_server(workdir=tmp_path_factory.mktemp("plain"), home=server_home)
    yield server
    stop_server(server=server)


class TestPlainHttp(WhoAmI):
    @pytest.fixture(scope="class")
    def dbt_profile_target(self, plain_server):
        # No database: the adapter asks the server for its current catalog ("memory").
        return plain_server.profile(database=None)

    def test_password_over_plain_http(self, project):
        run_dbt(args=["run"])
        assert signed_in_as(project=project) == ("dbt", "memory")


def test_tls_against_a_plain_http_server_is_refused(plain_server):
    # The twin of TestPlainHttp: TLS is the default, and the driver never falls back.
    with pytest.raises(expected_exception=FailedToConnectError) as error:
        open_connection(
            host=plain_server.host,
            port=plain_server.port,
            username=plain_server.username,
            password=plain_server.password,
            database="memory",
        )
    assert "speaks plain HTTP, not TLS. Add ?tls=false" in str(error.value)


# --- an access token -----------------------------------------------------------------------------


class TestToken(WhoAmI):
    @pytest.fixture(scope="class")
    def dbt_profile_target(self, hardcharger_server):
        return hardcharger_server.profile(
            user=None, password=None, auth_type="token", token=issue_token(hardcharger_server)
        )

    def test_token_sign_in(self, project):
        run_dbt(args=["run"])
        assert signed_in_as(project=project) == ("dbt", "dbt")


def test_a_bad_token_is_refused(hardcharger_server):
    with pytest.raises(expected_exception=FailedToConnectError) as error:
        open_connection(
            host=hardcharger_server.host,
            port=hardcharger_server.port,
            token="not-a-token",
            database="dbt",
            tls_root_certs=str(hardcharger_server.certs["ca"]),
        )
    assert "invalid_token" in str(error.value)


# --- a client certificate (mutual TLS) ---------------------------------------------------------


@pytest.fixture(scope="module")
def mtls_server(tmp_path_factory, server_home, certificates):
    server = start_server(
        workdir=tmp_path_factory.mktemp("mtls"),
        home=server_home,
        certs=certificates,
        extra_args=[
            "--mtls-ca-cert",
            str(certificates["ca"]),
            "--mtls-certificate-sign-in",
            "--mtls-admin-identities",
            "analyst@example.com",
        ],
    )
    yield server
    stop_server(server=server)


class TestClientCertificate(WhoAmI):
    @pytest.fixture(scope="class")
    def dbt_profile_target(self, mtls_server, certificates):
        return mtls_server.profile(
            user=None,
            password=None,
            database=None,
            auth_type="client_certificate",
            tls_client_cert=str(certificates["analyst"]),
            tls_client_key=str(certificates["analyst-key"]),
        )

    def test_client_certificate_sign_in(self, project):
        run_dbt(args=["run"])
        assert signed_in_as(project=project) == ("analyst@example.com", "memory")


def test_a_certificate_of_an_unknown_identity_is_refused(mtls_server, certificates):
    # The twin of TestClientCertificate: a certificate from the same CA, for an identity that
    # is neither an admin identity nor a user the server knows.
    with pytest.raises(expected_exception=FailedToConnectError) as error:
        open_connection(
            host=mtls_server.host,
            port=mtls_server.port,
            auth_type="client_certificate",
            database="memory",
            tls_root_certs=str(certificates["ca"]),
            tls_client_cert=str(certificates["stranger"]),
            tls_client_key=str(certificates["stranger-key"]),
        )
    assert "unknown_certificate_identity" in str(error.value)
    assert "stranger@example.com" in str(error.value)


# --- the server's browser sign-in (auth_type: external) -----------------------------------------

AUDIENCE = "dbt-hardcharger-test"
CLIENT_ID = "dbt-hardcharger-client"
CLIENT_SECRET = "dbt-hardcharger-secret"


@pytest.fixture(scope="module")
def idp_issuer():
    process = subprocess.Popen(
        args=[sys.executable, str(SUPPORT / "mock_idp.py"), AUDIENCE, CLIENT_ID, CLIENT_SECRET],
        stdout=subprocess.PIPE,
        text=True,
    )
    issuer = process.stdout.readline().strip()
    if not issuer.startswith("http://127.0.0.1:"):
        process.kill()
        pytest.fail(reason=f"the mock identity provider did not start: {issuer!r}")
    yield issuer
    process.kill()
    process.wait()


@pytest.fixture(scope="module")
def oauth_server(tmp_path_factory, server_home, idp_issuer):
    server = start_server(
        workdir=tmp_path_factory.mktemp("oauth"),
        home=server_home,
        extra_args=[
            "--token-allowed-issuer",
            idp_issuer,
            "--token-allowed-audience",
            AUDIENCE,
            "--token-default-role",
            "admin",
            "--token-authorized-emails",
            "*@example.com",
            "--oauth-client-id",
            CLIENT_ID,
            "--oauth-client-secret",
            CLIENT_SECRET,
            # Browser sign-in runs on the server's own port (Chargewire §4.3); the redirect URI
            # names 127.0.0.1, where the tests dial it.
            "--oauth-base-url",
            "{base_url}",
        ],
    )
    yield server
    stop_server(server=server)


def fake_browser(code: str, sign_in_log: pathlib.Path) -> str:
    return f"{sys.executable} {SUPPORT / 'fake_browser.py'} {sign_in_log} {code}"


class TestBrowserSignIn(WhoAmI):
    @pytest.fixture(scope="class")
    def sign_in_log(self, tmp_path_factory) -> pathlib.Path:
        return tmp_path_factory.mktemp("browser") / "sign-ins.log"

    @pytest.fixture(scope="class")
    def dbt_profile_target(self, oauth_server, sign_in_log):
        return oauth_server.profile(
            user=None,
            password=None,
            schema="main",
            database="memory",
            auth_type="external",
            oauth_browser=fake_browser(code="code-ok", sign_in_log=sign_in_log),
        )

    def test_browser_sign_in(self, project, sign_in_log):
        run_dbt(args=["run"])
        assert signed_in_as(project=project) == ("analyst@example.com", "memory")
        # One browser sign-in for the whole run, not one per connection dbt opens.
        assert sign_in_log.read_text().count("sign-in") == 1


def test_a_rejected_browser_sign_in_is_refused(oauth_server, tmp_path):
    with pytest.raises(expected_exception=FailedToConnectError) as error:
        open_connection(
            host=oauth_server.host,
            port=oauth_server.port,
            tls=False,
            database="memory",
            auth_type="external",
            oauth_browser=fake_browser(code="code-bad", sign_in_log=tmp_path / "log"),
        )
    assert "invalid_grant" in str(error.value)
