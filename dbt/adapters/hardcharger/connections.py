import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

if TYPE_CHECKING:
    import agate

import adbc_driver_manager
import dbt.adapters.exceptions
import dbt.exceptions  # noqa: F401
from adbc_driver_hardcharger import dbapi as hardcharger
from dbt.adapters.base.connections import AdapterResponse
from dbt.adapters.contracts.connection import Connection, ConnectionState, Credentials
from dbt.adapters.events.logging import AdapterLogger
from dbt.adapters.sql import SQLConnectionManager
from dbt_common.exceptions import DbtConfigError, DbtRuntimeError

logger = AdapterLogger("Hardcharger")

#: The ways to sign in. "password" (the default), "token" (an access token obtained
#: elsewhere), "client_certificate" (mutual TLS: the certificate is the credential) and
#: "external" (the server's browser sign-in through its identity provider).
AUTH_TYPES = ("password", "token", "client_certificate", "external")

#: The vendor name a Hardcharger server reports in ADBC GetInfo.
HARDCHARGER_VENDOR_NAME = "Hardcharger"


DUCKLAKE_METADATA_TIMEOUT_HINT = """

Hint: this looks like a DuckLake catalog whose Postgres metadata connection was
closed mid-transaction. DuckLake keeps its metadata transaction open -- and the
Postgres session idle -- for the whole of a write, so a write that runs longer
than the metadata server's idle_in_transaction_session_timeout is killed at
commit. Either raise that timeout for the DuckLake catalog (server/parameter
group setting, or per role:
  ALTER ROLE <catalog_role> SET idle_in_transaction_session_timeout = '2h';
then have Hardcharger reconnect), or shorten the write -- e.g. have a Python model
return cursor.fetch_arrow_table() instead of streaming from a slow source."""


def with_ducklake_metadata_hint(message: str) -> str:
    """Append an explanation to errors caused by a DuckLake Postgres metadata
    connection dying mid-transaction (typically idle_in_transaction_session_timeout),
    which otherwise surface as e.g. `Failed to commit: Failed to execute query
    "ROLLBACK": ` with an empty Postgres error."""
    # The quote may be JSON-escaped (\") when the error is relayed by the server
    if "Failed to commit" in message and re.search(
        pattern=r'Failed to execute query \\?"', string=message
    ):
        return message + DUCKLAKE_METADATA_TIMEOUT_HINT
    return message


# One signed-in driver database per browser sign-in profile, shared by every connection
# this process opens with it: the driver signs in when a database opens its first
# connection, and later connections from the same database share that sign-in. Without it
# each dbt connection would open its own browser sign-in (five for a one-model `dbt run`).
_browser_sign_ins: Dict[Tuple[Tuple[str, Any], ...], Any] = {}
_browser_sign_ins_lock = threading.Lock()


def connect(credentials: "HardchargerCredentials") -> "hardcharger.Connection":
    """A DB-API connection (autocommit on) for a profile's credentials."""
    kwargs = credentials.connect_kwargs(autocommit=True)
    if credentials.effective_auth_type != "external":
        return hardcharger.connect(**kwargs)
    # The catalog is a connection option, not the database's: leave it out of the key.
    key = tuple(sorted((k, v) for k, v in kwargs.items() if k != "catalog"))
    with _browser_sign_ins_lock:
        shared = _browser_sign_ins.get(key)
        if shared is None:
            connection = hardcharger.connect(**kwargs)
            # Keep a reference to its database (adbc_driver_manager's reference-counted
            # holder) for the connections opened after it.
            _browser_sign_ins[key] = connection._db.clone()
            return connection
    conn_kwargs = {}
    if credentials.database:
        conn_kwargs[adbc_driver_manager.ConnectionOptions.CURRENT_CATALOG.value] = (
            credentials.database
        )
    return hardcharger.Connection(
        db=shared,
        conn=adbc_driver_manager.AdbcConnection(database=shared._db, **conn_kwargs),
        autocommit=True,
    )


@dataclass
class HardchargerCredentials(Credentials):
    database: str = ""
    schema: str = ""

    host: str = field(kw_only=True)
    port: int = field(default=31337, kw_only=True)

    # Sign-in. See AUTH_TYPES; when auth_type is not given it is "token" if a token is,
    # "password" otherwise.
    auth_type: Optional[str] = field(default=None, kw_only=True)
    username: Optional[str] = field(default=None, kw_only=True)
    password: Optional[str] = field(default=None, kw_only=True)
    token: Optional[str] = field(default=None, kw_only=True)

    # TLS is on unless `tls: false` (plain HTTP, for development servers).
    tls: bool = field(default=True, kw_only=True)
    tls_skip_verify: bool = field(default=False, kw_only=True)
    # CA certificates to trust, a client certificate chain and its key: each a file path
    # or PEM text.
    tls_root_certs: Optional[str] = field(default=None, kw_only=True)
    tls_client_cert: Optional[str] = field(default=None, kw_only=True)
    tls_client_key: Optional[str] = field(default=None, kw_only=True)

    # Browser sign-in (auth_type: external): the sign-in server's base URL or port (the
    # server's --oauth-base-url / --oauth-port), and the command that opens the sign-in
    # page ("none" prints the URL instead of opening a browser).
    oauth_url: Optional[str] = field(default=None, kw_only=True)
    oauth_port: Optional[int] = field(default=None, kw_only=True)
    oauth_browser: Optional[str] = field(default=None, kw_only=True)

    # Root path (server-side) for external materializations that do not specify
    # their own `location`. Resolved on the Hardcharger server, so it may be a local
    # filesystem path or any cloud storage URI (s3://, gs://, etc.) its DuckDB can reach.
    external_root: str = field(default=".", kw_only=True)

    _ALIASES = {
        "catalog": "database",
        "dbname": "database",
        "pass": "password",
        "user": "username",
    }

    def __post_init__(self):
        self.check_settings()
        # Set the default database and schema if they are not set by retrieving them from
        # the server
        if not self.database or not self.schema:
            try:
                with connect(credentials=self) as conn:
                    self.database = self.database or getattr(conn, "adbc_current_catalog")
                    self.schema = self.schema or getattr(conn, "adbc_current_db_schema")
            except Exception as e:
                raise dbt.adapters.exceptions.FailedToConnectError(str(e)) from e

    @property
    def effective_auth_type(self) -> str:
        if self.auth_type:
            return self.auth_type
        return "token" if self.token else "password"

    def check_settings(self) -> None:
        """Refuse a profile whose sign-in settings contradict each other, with a message
        that says which setting to change, before anything is sent to the server."""
        auth_type = self.effective_auth_type
        if auth_type not in AUTH_TYPES:
            raise DbtConfigError(
                msg=f"auth_type {auth_type!r} is not one of {', '.join(AUTH_TYPES)}"
            )
        if auth_type == "password" and not self.username:
            raise DbtConfigError(msg="auth_type 'password' needs a user (and its password)")
        if auth_type != "password" and (self.username or self.password):
            raise DbtConfigError(
                msg=f"auth_type {auth_type!r} signs in without a user name and password: "
                "remove user and password from the profile"
            )
        if auth_type == "token" and not self.token:
            raise DbtConfigError(msg="auth_type 'token' needs a token")
        if auth_type != "token" and self.token:
            raise DbtConfigError(msg=f"auth_type {auth_type!r} takes no token")
        if auth_type == "client_certificate" and not (self.tls_client_cert and self.tls_client_key):
            raise DbtConfigError(
                msg="auth_type 'client_certificate' needs tls_client_cert and tls_client_key"
            )
        if bool(self.tls_client_cert) != bool(self.tls_client_key):
            raise DbtConfigError(msg="tls_client_cert and tls_client_key go together")
        if not self.tls and (self.tls_client_cert or self.tls_root_certs or self.tls_skip_verify):
            raise DbtConfigError(
                msg="tls: false is plain HTTP: remove the tls_* settings, or turn TLS on"
            )
        if auth_type != "external" and (self.oauth_url or self.oauth_port or self.oauth_browser):
            raise DbtConfigError(
                msg="oauth_url, oauth_port and oauth_browser are for auth_type 'external'"
            )

    @property
    def uri(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        uri = f"hardcharger://{host}:{self.port}"
        return uri if self.tls else uri + "?tls=false"

    def connect_kwargs(self, autocommit: bool) -> Dict[str, Any]:
        """Keyword arguments for adbc_driver_hardcharger.dbapi.connect()."""
        auth_type = self.effective_auth_type
        kwargs: Dict[str, Any] = {
            "uri": self.uri,
            "autocommit": autocommit,
            "auth_type": "password" if auth_type == "token" else auth_type,
        }
        if self.database:
            kwargs["catalog"] = self.database
        if auth_type == "password":
            kwargs["username"] = self.username
            kwargs["password"] = self.password or ""
        if auth_type == "token":
            kwargs["access_token"] = self.token
        if self.tls_skip_verify:
            kwargs["tls_skip_verify"] = True
        for key in ("tls_root_certs", "tls_client_cert", "tls_client_key", "oauth_url"):
            value = getattr(self, key)
            if value:
                kwargs[key] = value
        if self.oauth_port:
            kwargs["oauth_port"] = self.oauth_port
        if self.oauth_browser:
            kwargs["open_browser"] = False if self.oauth_browser == "none" else self.oauth_browser
        return kwargs

    @property
    def type(self):
        """Return name of adapter."""
        return "hardcharger"

    @property
    def unique_field(self):
        """
        Hashed and included in anonymous telemetry to track adapter adoption.
        Pick a field that can uniquely identify one team/organization building with this adapter
        """
        return self.host

    def _connection_keys(self):
        """
        List of keys to display in the `dbt debug` output.
        """
        return (
            "host",
            "port",
            "schema",
            "database",
            "user",
            "auth_type",
            "tls",
            "tls_skip_verify",
            "tls_root_certs",
            "tls_client_cert",
            "external_root",
        )


class HardchargerConnectionManager(SQLConnectionManager):
    TYPE = "hardcharger"

    @classmethod
    def open(cls, connection: Connection) -> Connection:
        if connection.state == ConnectionState.OPEN:
            logger.debug("Connection is already open, skipping open.")
            return connection

        credentials: HardchargerCredentials = connection.credentials
        handle = None
        try:
            handle = connect(credentials=credentials)
            vendor_name = handle.adbc_get_info().get("vendor_name")
            if vendor_name != HARDCHARGER_VENDOR_NAME:
                raise DbtRuntimeError(
                    msg=f"{credentials.uri} is not a Hardcharger server (its vendor name is "
                    f"{vendor_name!r})"
                )
        except Exception as e:
            logger.debug(f"Got an error when attempting to connect to Hardcharger: '{e}'")
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            # (Not connection.handle: dbt refuses reads of it while it is being opened.)
            connection.handle = None
            connection.state = ConnectionState.FAIL
            raise dbt.adapters.exceptions.FailedToConnectError(str(e))

        connection.handle = handle
        connection.state = ConnectionState.OPEN
        return connection

    def add_begin_query(self):
        """No-op: rely on autocommit so each statement commits immediately.

        Connections open with autocommit on, so every statement is its own
        transaction, as in dbt-gizmosql: the materializations here were written and
        tested for that, and dbt's adapter test suite passes on it.
        """
        pass

    def add_commit_query(self):
        """No-op: paired with add_begin_query — see docstring there."""
        pass

    def execute(
        self,
        sql: str,
        auto_begin: bool = False,
        fetch: bool = False,
        limit: Optional[int] = None,
    ) -> Tuple[AdapterResponse, "agate.Table"]:
        from dbt_common.clients.agate_helper import empty_table

        sql = self._add_query_comment(sql=sql)
        _, cursor = self.add_query(sql=sql, auto_begin=auto_begin)
        try:
            response = self.get_response(cursor=cursor)
            if fetch:
                table = self.get_result_from_cursor(cursor=cursor, limit=limit)
            else:
                table = empty_table()
            return response, table
        finally:
            cursor.close()

    def add_select_query(self, sql: str) -> Tuple[Connection, Any]:
        sql = self._add_query_comment(sql=sql)
        return self.add_query(sql=sql, auto_begin=False)

    @classmethod
    def close(cls, connection: Connection) -> Connection:
        # if the connection is in closed or init, there's nothing to do
        if connection.state in {ConnectionState.CLOSED, ConnectionState.INIT}:
            return connection

        try:
            connection.handle.adbc_cancel()
        except Exception:
            pass
        connection = super().close(connection=connection)
        return connection

    @classmethod
    def get_response(cls, cursor) -> AdapterResponse:
        message = "OK"
        return AdapterResponse(_message=message)

    def cancel(self, connection):
        """
        Gets a connection object and attempts to cancel any ongoing queries.
        """
        connection.handle.adbc_cancel()
        logger.debug(f"query cancelled on connection {connection.name}")

    @contextmanager
    def exception_handler(self, sql: str, connection_name="master"):
        try:
            yield
        except dbt.exceptions.DbtRuntimeError:
            raise
        except Exception as exc:
            logger.debug("Hardcharger error: {}".format(str(exc)))
            logger.debug("Error running SQL: {}".format(sql))
            # Keep the original error, with its full context, as the cause
            raise dbt.exceptions.DbtRuntimeError(
                msg=with_ducklake_metadata_hint(message=str(exc))
            ) from exc
