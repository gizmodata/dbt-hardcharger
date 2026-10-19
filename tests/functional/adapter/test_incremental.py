from dbt.tests.adapter.incremental.test_incremental_on_schema_change import (
    BaseIncrementalOnSchemaChange,
)
from dbt.tests.adapter.incremental.test_incremental_predicates import (
    BaseIncrementalPredicates,
)
from dbt.tests.adapter.incremental.test_incremental_unique_id import (
    BaseIncrementalUniqueKey,
)


class TestIncrementalUniqueKeyHardcharger(BaseIncrementalUniqueKey):
    pass


class TestIncrementalPredicatesHardcharger(BaseIncrementalPredicates):
    pass


class TestIncrementalOnSchemaChangeHardcharger(BaseIncrementalOnSchemaChange):
    pass
