import os
import re

from dbt.tests.adapter.ephemeral.test_ephemeral import (
    BaseEphemeralErrorHandling,
    BaseEphemeralMulti,
)
from dbt.tests.util import check_relations_equal, run_dbt


class TestEphemeralErrorHandlingHardcharger(BaseEphemeralErrorHandling):
    pass


class TestEphemeralMultiHardcharger(BaseEphemeralMulti):
    def test_ephemeral_multi(self, project):
        run_dbt(args=["seed"])
        results = run_dbt(args=["run"])
        assert len(results) == 3

        check_relations_equal(adapter=project.adapter, relation_names=["seed", "dependent"])
        check_relations_equal(adapter=project.adapter, relation_names=["seed", "double_dependent"])
        check_relations_equal(adapter=project.adapter, relation_names=["seed", "super_dependent"])
        assert os.path.exists(path="./target/run/test/models/double_dependent.sql")
        with open(file="./target/run/test/models/double_dependent.sql", mode="r") as fp:
            sql_file = fp.read()

        sql_file = re.sub(pattern=r"\d+", repl="", string=sql_file)
        # Hardcharger uses "dbt" as the database name (from DATABASE_FILENAME=dbt.db)
        expected_sql = (
            'create view "dbt"."test_test_ephemeral"."double_dependent__dbt_tmp" as ('
            "with __dbt__cte__base as ("
            "select * from test_test_ephemeral.seed"
            "),  __dbt__cte__base_copy as ("
            "select * from __dbt__cte__base"
            ")-- base_copy just pulls from base. Make sure the listed"
            "-- graph of CTEs all share the same dbt_cte__base cte"
            "select * from __dbt__cte__base"
            " where gender = 'Male'"
            "union all"
            "select * from __dbt__cte__base_copy"
            " where gender = 'Female');"
        )
        sql_file = "".join(sql_file.split())
        expected_sql = "".join(expected_sql.split())
        assert sql_file == expected_sql
