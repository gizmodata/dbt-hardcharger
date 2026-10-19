"""Errors from a DuckLake Postgres metadata connection dying mid-transaction
(e.g. idle_in_transaction_session_timeout) get an explanatory hint."""

import pytest
from dbt_common.exceptions import DbtRuntimeError

from dbt.adapters.hardcharger.connections import (
    DUCKLAKE_METADATA_TIMEOUT_HINT,
    HardchargerConnectionManager,
    with_ducklake_metadata_hint,
)

# As dbt-gizmosql saw it from a dbt run (a JSON-escaped quote, ADBC ingest into a DuckLake
# catalog), and in the shape the Hardcharger driver reports a failed bulk ingest
ROLLBACK_FAILURE_JSON = (
    "INVALID_ARGUMENT: DuckDB ingest failed: "
    '{"exception_type":"TransactionContext","exception_message":"Failed to commit: '
    'Failed to execute query \\"ROLLBACK\\": "}'
)
ROLLBACK_FAILURE = (
    "INVALID_ARGUMENT: [warpsql] bulk ingest into t: TransactionContext Error: "
    'Failed to commit: Failed to execute query "ROLLBACK": (sql_error, HTTP 400)'
)
# As reproduced when the metadata Postgres closed the connection before COMMIT
COMMIT_FAILURE = (
    'Failed to commit: Failed to commit: Failed to execute query "COMMIT": '
    "server closed the connection unexpectedly"
)


@pytest.mark.parametrize(
    argnames="message", argvalues=[ROLLBACK_FAILURE_JSON, ROLLBACK_FAILURE, COMMIT_FAILURE]
)
def test_metadata_commit_failures_get_hint(message):
    result = with_ducklake_metadata_hint(message=message)
    assert result.startswith(message)
    assert result.endswith(DUCKLAKE_METADATA_TIMEOUT_HINT)
    assert "idle_in_transaction_session_timeout" in result


@pytest.mark.parametrize(
    argnames="message",
    argvalues=[
        "Catalog Error: Table with name foo does not exist!",
        "Failed to commit: Constraint Error: NOT NULL constraint failed",
        'Failed to execute query "SELECT 1": some other postgres error',
    ],
)
def test_other_errors_are_unchanged(message):
    assert with_ducklake_metadata_hint(message=message) == message


def test_sql_exception_handler_adds_hint():
    # exception_handler doesn't use instance state, so no connection is needed
    with pytest.raises(expected_exception=DbtRuntimeError) as exc_info:
        with HardchargerConnectionManager.exception_handler(None, sql="insert into t select 1"):
            raise Exception(COMMIT_FAILURE)
    assert "idle_in_transaction_session_timeout" in str(exc_info.value)
