from dbt.tests.adapter.caching.test_caching import (
    BaseCachingLowercaseModel,
    BaseCachingSelectedSchemaOnly,
    BaseNoPopulateCache,
)


class TestCachingLowercaseModelHardcharger(BaseCachingLowercaseModel):
    pass


class TestCachingSelectedSchemaOnlyHardcharger(BaseCachingSelectedSchemaOnly):
    pass


class TestNoPopulateCacheHardcharger(BaseNoPopulateCache):
    pass
