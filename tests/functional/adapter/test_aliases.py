from dbt.tests.adapter.aliases.test_aliases import (
    BaseAliasErrors,
    BaseAliases,
    BaseSameAliasDifferentDatabases,
    BaseSameAliasDifferentSchemas,
)


class TestAliasesHardcharger(BaseAliases):
    pass


class TestAliasErrorsHardcharger(BaseAliasErrors):
    pass


class TestSameAliasDifferentSchemasHardcharger(BaseSameAliasDifferentSchemas):
    pass


class TestSameAliasDifferentDatabasesHardcharger(BaseSameAliasDifferentDatabases):
    pass
