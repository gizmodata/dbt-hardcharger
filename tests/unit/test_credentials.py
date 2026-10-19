"""Profile settings: the URI and driver arguments they turn into, and the contradictions refused
before anything is sent. (database and schema are given, so nothing connects.)"""

import pytest
from dbt_common.exceptions import DbtConfigError

from dbt.adapters.hardcharger.connections import HardchargerCredentials


def credentials(**settings) -> HardchargerCredentials:
    return HardchargerCredentials(
        **{"host": "db.example.com", "database": "analytics", "schema": "main", **settings}
    )


def test_tls_and_port_31337_are_the_defaults():
    creds = credentials(username="joe", password="secret")
    assert creds.uri == "hardcharger://db.example.com:31337"
    assert creds.connect_kwargs(autocommit=True) == {
        "uri": "hardcharger://db.example.com:31337",
        "autocommit": True,
        "auth_type": "password",
        "catalog": "analytics",
        "username": "joe",
        "password": "secret",
    }


def test_plain_http_and_ipv6():
    assert (
        credentials(username="joe", tls=False).uri == "hardcharger://db.example.com:31337?tls=false"
    )
    assert credentials(host="::1", port=4000, username="joe").uri == "hardcharger://[::1]:4000"


def test_token():
    creds = credentials(token="t0ken")
    assert creds.effective_auth_type == "token"
    kwargs = creds.connect_kwargs(autocommit=True)
    assert kwargs["access_token"] == "t0ken"
    assert kwargs["auth_type"] == "password"  # the driver's: a token is used as is
    assert "username" not in kwargs and "password" not in kwargs


def test_client_certificate_and_tls_files():
    kwargs = credentials(
        auth_type="client_certificate",
        tls_root_certs="ca.pem",
        tls_client_cert="me.pem",
        tls_client_key="me-key.pem",
    ).connect_kwargs(autocommit=True)
    assert kwargs["auth_type"] == "client_certificate"
    assert (kwargs["tls_root_certs"], kwargs["tls_client_cert"], kwargs["tls_client_key"]) == (
        "ca.pem",
        "me.pem",
        "me-key.pem",
    )


def test_browser_sign_in():
    kwargs = credentials(
        auth_type="external", oauth_port=4443, oauth_browser="none"
    ).connect_kwargs(autocommit=True)
    assert kwargs["auth_type"] == "external"
    assert kwargs["oauth_port"] == 4443
    assert kwargs["open_browser"] is False
    kwargs = credentials(auth_type="external", oauth_browser="firefox").connect_kwargs(
        autocommit=True
    )
    assert kwargs["open_browser"] == "firefox"


@pytest.mark.parametrize(
    argnames=("settings", "message"),
    argvalues=[
        ({"auth_type": "kerberos", "username": "joe"}, "auth_type 'kerberos' is not one of"),
        ({}, "auth_type 'password' needs a user"),
        ({"auth_type": "token", "token": "t", "username": "joe"}, "remove user and password"),
        ({"auth_type": "token"}, "auth_type 'token' needs a token"),
        (
            {"username": "joe", "password": "p", "auth_type": "password", "token": "t"},
            "takes no token",
        ),
        (
            {"auth_type": "client_certificate", "tls_client_cert": "me.pem"},
            "needs tls_client_cert and tls_client_key",
        ),
        ({"username": "joe", "tls_client_key": "me-key.pem"}, "go together"),
        ({"username": "joe", "tls": False, "tls_root_certs": "ca.pem"}, "tls: false is plain HTTP"),
        ({"username": "joe", "oauth_port": 4443}, "are for auth_type 'external'"),
        ({"auth_type": "external", "username": "joe"}, "remove user and password"),
    ],
)
def test_contradictions_are_refused(settings, message):
    with pytest.raises(expected_exception=DbtConfigError, match=message):
        credentials(**settings)
