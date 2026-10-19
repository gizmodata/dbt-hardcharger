from dbt.tests.adapter.hooks.test_model_hooks import (
    BaseDuplicateHooksInConfigs,
    BaseHooksRefsOnSeeds,
    BasePrePostModelHooksOnSeeds,
    BasePrePostModelHooksOnSeedsPlusPrefixed,
    BasePrePostModelHooksOnSeedsPlusPrefixedWhitespace,
    BasePrePostModelHooksOnSnapshots,
    BasePrePostSnapshotHooksInConfigKwargs,
)


class TestPrePostModelHooksOnSeedsHardcharger(BasePrePostModelHooksOnSeeds):
    pass


class TestHooksRefsOnSeedsHardcharger(BaseHooksRefsOnSeeds):
    pass


class TestPrePostModelHooksOnSeedsPlusPrefixedHardcharger(BasePrePostModelHooksOnSeedsPlusPrefixed):
    pass


class TestPrePostModelHooksOnSeedsPlusPrefixedWhitespaceHardcharger(
    BasePrePostModelHooksOnSeedsPlusPrefixedWhitespace
):
    pass


class TestPrePostModelHooksOnSnapshotsHardcharger(BasePrePostModelHooksOnSnapshots):
    pass


class TestPrePostSnapshotHooksInConfigKwargsHardcharger(BasePrePostSnapshotHooksInConfigKwargs):
    pass


class TestDuplicateHooksInConfigsHardcharger(BaseDuplicateHooksInConfigs):
    pass
