import pytest
from dbt.tests.adapter.simple_seed.test_seed import (
    BaseSeedParsing,
    BaseSeedSpecificFormats,
    BaseSeedWithEmptyDelimiter,
    BaseSeedWithWrongDelimiter,
    BaseSimpleSeedEnabledViaConfig,
    BaseTestEmptySeed,
)


@pytest.mark.skip(
    reason="DuckDB auto_detect overrides explicit delimiter; test expects syntax error"
)
class TestSeedWithWrongDelimiterHardcharger(BaseSeedWithWrongDelimiter):
    pass


class TestSeedWithEmptyDelimiterHardcharger(BaseSeedWithEmptyDelimiter):
    pass


class TestSimpleSeedEnabledViaConfigHardcharger(BaseSimpleSeedEnabledViaConfig):
    pass


class TestSeedParsingHardcharger(BaseSeedParsing):
    pass


class TestSeedSpecificFormatsHardcharger(BaseSeedSpecificFormats):
    pass


class TestEmptySeedHardcharger(BaseTestEmptySeed):
    pass
