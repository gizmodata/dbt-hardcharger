"""Opening connections from many threads at once must work: dbt opens one connection per
thread at the start of a run, all at the same moment, and each runs a query at once."""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from dbt.adapters.contracts.connection import Connection

from dbt.adapters.hardcharger.connections import (
    HardchargerConnectionManager,
    HardchargerCredentials,
)


@pytest.fixture()
def credentials(hardcharger_server):
    return HardchargerCredentials(
        host=hardcharger_server.host,
        port=hardcharger_server.port,
        username=hardcharger_server.username,
        password=hardcharger_server.password,
        tls_root_certs=str(hardcharger_server.certs["ca"]),
    )


def _open_connection(credentials, name="test"):
    conn = Connection(type="hardcharger", name=name, credentials=credentials)
    HardchargerConnectionManager.open(connection=conn)
    return conn


class TestConcurrentConnections:
    def test_concurrent_open(self, credentials):
        num_threads = 8
        num_iterations = 5
        errors = []

        for iteration in range(num_iterations):
            iteration_barrier = threading.Barrier(parties=num_threads)

            def open_and_query(thread_id, barrier=iteration_barrier):
                barrier.wait()
                conn = _open_connection(credentials=credentials, name=f"thread-{thread_id}")
                try:
                    cursor = conn.handle.cursor()
                    cursor.execute(operation=f"SELECT {thread_id} AS tid")
                    result = cursor.fetchall()
                    cursor.close()
                    return result
                finally:
                    conn.handle.close()

            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = {executor.submit(open_and_query, i): i for i in range(num_threads)}
                for future in as_completed(fs=futures):
                    try:
                        assert future.result() == [(futures[future],)]
                    except Exception as e:
                        errors.append(f"iteration={iteration} thread={futures[future]}: {e}")

        assert not errors, f"Got {len(errors)} errors:\n" + "\n".join(errors[:5])
