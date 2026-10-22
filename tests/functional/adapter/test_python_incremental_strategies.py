"""Exercise Python and SQL strategy dispatch against the real server."""

from pathlib import Path

import pytest
from dbt.tests.util import get_connection, relation_from_name, run_dbt

INITIAL = [(1, "a", "old-one", "fixed-one"), (2, "a", "old-two", "fixed-two")]
UPDATED = [(2, "a", "new-two", "changed-two"), (3, "a", "new-three", "new-three")]

CASES = [
    pytest.param(({}, "merge"), id="default-with-key"),
    pytest.param(({"incremental_strategy": "merge"}, "merge"), id="explicit-merge"),
    pytest.param(({"incremental_strategy": "append"}, "append"), id="explicit-append"),
    pytest.param(({"incremental_strategy": "delete+insert"}, "delete+insert"), id="delete-insert"),
    pytest.param(({"unique_key": None}, "append"), id="default-without-key"),
    pytest.param(
        ({"unique_key": None, "incremental_strategy": "merge"}, "append"), id="merge-without-key"
    ),
    pytest.param(({"unique_key": ["Id", "region"]}, "composite"), id="composite-key"),
    pytest.param(
        ({"incremental_strategy": "merge", "merge_exclude_columns": ["label"]}, "partial"),
        id="merge-exclude-columns",
    ),
    pytest.param(
        ({"incremental_strategy": "merge", "merge_update_columns": ["value"]}, "partial"),
        id="merge-update-columns",
    ),
    pytest.param(
        (
            {
                "incremental_strategy": "merge",
                "incremental_predicates": ['DBT_INTERNAL_DEST."Id" > 2'],
            },
            "append",
        ),
        id="merge-predicates",
    ),
    pytest.param(
        ({"incremental_strategy": "delete+insert", "predicates": ['"Id" > 2']}, "append"),
        id="delete-insert-predicates",
    ),
]


class TestIncrementalStrategies:
    @pytest.fixture(scope="class", params=["python", "sql"])
    def language(self, request):
        return request.param

    @pytest.fixture(scope="class", params=CASES)
    def strategy_case(self, request):
        return request.param

    @pytest.fixture(scope="class")
    def project_root(self, tmpdir_factory, language, strategy_case):
        # dbt's default root is class-scoped; each parameter needs fresh model files.
        return tmpdir_factory.mktemp("strategy-project")

    @pytest.fixture(scope="class")
    def models(self, language, strategy_case):
        overrides, behavior = strategy_case
        config = {"materialized": "incremental", "unique_key": "Id", **overrides}
        config_args = ", ".join(f"{key}={value!r}" for key, value in config.items())
        updated = (
            UPDATED if behavior != "composite" else [(2, "b", "new-two", "changed-two"), UPDATED[1]]
        )
        if language == "python":
            return {
                "incremental_model.py": f"""
import pyarrow as pa

def model(dbt, session):
    dbt.config({config_args})
    rows = {updated!r} if dbt.is_incremental else {INITIAL!r}
    # Different column order on the second run must not scramble the values.
    names = ['Id', 'region', 'value', 'label']
    if dbt.is_incremental:
        names = list(reversed(names))
    positions = {{'Id': 0, 'region': 1, 'value': 2, 'label': 3}}
    return pa.table(data={{name: [row[positions[name]] for row in rows] for name in names}})
"""
            }
        initial_sql = " union all ".join(
            f"select {row[0]} as Id, '{row[1]}' as region, '{row[2]}' as value, '{row[3]}' as label"
            for row in INITIAL
        )
        updated_sql = " union all ".join(
            f"select '{row[3]}' as label, '{row[2]}' as value, '{row[1]}' as region, {row[0]} as Id"
            for row in updated
        )
        return {
            "incremental_model.sql": (
                "{{ config(" + config_args + ") }}\n"
                "{% if is_incremental() %}\n"
                + updated_sql
                + "\n{% else %}\n"
                + initial_sql
                + "\n{% endif %}"
            )
        }

    def test_strategy_updates_and_inserts(self, project, strategy_case, logs_dir):
        overrides, behavior = strategy_case
        run_dbt(args=["run"])
        run_dbt(args=["run"])
        relation = relation_from_name(adapter=project.adapter, name="incremental_model")
        rows = project.run_sql(
            sql=f'SELECT "Id", region, value, label FROM {relation} ORDER BY "Id", region, value',
            fetch="all",
        )
        if behavior == "append":
            expected = [*INITIAL, *UPDATED]
        elif behavior == "composite":
            expected = [*INITIAL, (2, "b", "new-two", "changed-two"), UPDATED[1]]
        elif behavior == "partial":
            expected = [INITIAL[0], (2, "a", "new-two", "fixed-two"), UPDATED[1]]
        else:
            expected = [INITIAL[0], *UPDATED]
        assert rows == sorted(expected, key=lambda row: (row[0], row[1], row[2]))

        # Verify actual executed SQL as well as the resulting rows.
        log = (Path(logs_dir) / "dbt.log").read_text().lower()
        strategy = overrides.get("incremental_strategy")
        if strategy == "merge" or (strategy is None and overrides.get("unique_key", "Id")):
            assert f"merge into {relation} as DBT_INTERNAL_DEST".lower() in log
            assert "insert by name" in log
            if behavior != "partial" and overrides.get("unique_key", "Id"):
                assert "update by name" in log
        elif strategy == "delete+insert":
            assert f"delete from {relation}".lower() in log
            assert f"insert into {relation} by name".lower() in log
        else:
            assert f"insert into {relation} by name".lower() in log

        run_dbt(args=["run", "--full-refresh"])
        assert (
            project.run_sql(
                sql=f'SELECT "Id", region, value, label FROM {relation} ORDER BY "Id"', fetch="all"
            )
            == INITIAL
        )


class TestPythonIncrementalHistoricalColumns:
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "log_model.py": """
import pyarrow as pa

def model(dbt, session):
    dbt.config(materialized='incremental', incremental_strategy='delete+insert',
               unique_key='log_date', full_refresh=False)
    if dbt.is_incremental:
        data = {'value': ['replacement', 'new'], 'log_date': [2, 3]}
    else:
        data = {'log_date': [1, 2], 'value': ['historical', 'old']}
    # Initial target: 22 columns. Later extracts: 19, in a different order.
    data.update({f'field_{i}': [i, i] for i in range(17)})
    if not dbt.is_incremental:
        data.update({f'legacy_{i}': ['retained', 'old'] for i in range(3)})
    return pa.table(data=data)
"""
        }

    def test_replaces_date_without_losing_history(self, project, logs_dir):
        run_dbt(args=["run"])
        relation = relation_from_name(adapter=project.adapter, name="log_model")
        # full_refresh=False must preserve rows no longer available at the source.
        for args in (["run"], ["run", "--full-refresh"]):
            run_dbt(args=args)
            rows = project.run_sql(
                sql=f"SELECT log_date, value, legacy_0 FROM {relation} ORDER BY log_date",
                fetch="all",
            )
            assert rows == [
                (1, "historical", "retained"),
                (2, "replacement", None),
                (3, "new", None),
            ]
        with get_connection(adapter=project.adapter):
            assert len(project.adapter.get_columns_in_relation(relation)) == 22
        log = (Path(logs_dir) / "dbt.log").read_text().lower()
        assert f"delete from {relation}".lower() in log


class TestPythonIncrementalSchemaChanges:
    @pytest.fixture(
        scope="class", params=["ignore", "append_new_columns", "sync_all_columns", "fail"]
    )
    def schema_policy(self, request):
        return request.param

    @pytest.fixture(scope="class")
    def project_root(self, tmpdir_factory, schema_policy):
        return tmpdir_factory.mktemp("schema-project")

    @pytest.fixture(scope="class")
    def models(self, schema_policy):
        return {
            "schema_model.py": f"""
import pyarrow as pa

def model(dbt, session):
    dbt.config(materialized='incremental', incremental_strategy='merge', unique_key='Id',
               on_schema_change={schema_policy!r})
    if dbt.is_incremental:
        data = {{'added': [10, 20], 'value': ['after', 'new'], 'Id': [2, 3]}}
    else:
        data = {{'Id': [1, 2], 'value': ['keep', 'before'], 'legacy': ['a', 'b']}}
    return pa.table(data=data)
"""
        }

    def test_schema_policy_is_respected(self, project, schema_policy):
        run_dbt(args=["run"])
        result = run_dbt(args=["run"], expect_pass=schema_policy != "fail")[0]
        relation = relation_from_name(adapter=project.adapter, name="schema_model")
        with get_connection(adapter=project.adapter):
            columns = {column.name for column in project.adapter.get_columns_in_relation(relation)}
        rows = project.run_sql(sql=f'SELECT "Id", value FROM {relation} ORDER BY "Id"', fetch="all")
        if schema_policy == "fail":
            assert "out of sync" in result.message
            assert rows == [(1, "keep"), (2, "before")]
            assert columns == {"Id", "value", "legacy"}
            return
        assert rows == [(1, "keep"), (2, "after"), (3, "new")]
        if schema_policy == "sync_all_columns":
            assert columns == {"Id", "value", "added"}
        else:
            # UPDATE BY NAME leaves an omitted column intact on matched rows.
            assert project.run_sql(
                sql=f'SELECT legacy FROM {relation} ORDER BY "Id"', fetch="all"
            ) == [("a",), ("b",), (None,)]
            expected_columns = {"Id", "value", "legacy"}
            if schema_policy == "append_new_columns":
                expected_columns.add("added")
            assert columns == expected_columns
        if schema_policy != "ignore":
            assert project.run_sql(
                sql=f'SELECT added FROM {relation} ORDER BY "Id"', fetch="all"
            ) == [(None,), (10,), (20,)]


class TestPythonIncrementalInvalidStrategy:
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "invalid_strategy.py": """
def model(dbt, session):
    dbt.config(materialized='incremental', incremental_strategy='insert_overwrite')
    raise AssertionError('The model must not run with an invalid strategy')
    return None
"""
        }

    def test_invalid_strategy_fails_before_extract(self, project):
        result = run_dbt(args=["run"], expect_pass=False)[0]
        assert "not valid for this adapter" in result.message.lower()
