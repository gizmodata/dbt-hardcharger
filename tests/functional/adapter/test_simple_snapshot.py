from dbt.tests.adapter.simple_snapshot.new_record_check_mode import (
    BaseSnapshotNewRecordCheckMode,
)
from dbt.tests.adapter.simple_snapshot.new_record_dbt_valid_to_current import (
    BaseSnapshotNewRecordDbtValidToCurrent,
)
from dbt.tests.adapter.simple_snapshot.new_record_timestamp_mode import (
    BaseSnapshotNewRecordTimestampMode,
)
from dbt.tests.adapter.simple_snapshot.test_snapshot import (
    BaseSimpleSnapshot,
    BaseSnapshotCheck,
)
from dbt.tests.adapter.simple_snapshot.test_various_configs import (
    BaseSnapshotColumnNames,
    BaseSnapshotColumnNamesFromDbtProject,
    BaseSnapshotMultiUniqueKey,
)


class TestSimpleSnapshotHardcharger(BaseSimpleSnapshot):
    pass


class TestSnapshotCheckHardcharger(BaseSnapshotCheck):
    pass


class TestSnapshotNewRecordCheckModeHardcharger(BaseSnapshotNewRecordCheckMode):
    pass


class TestSnapshotNewRecordDbtValidToCurrentHardcharger(BaseSnapshotNewRecordDbtValidToCurrent):
    pass


class TestSnapshotNewRecordTimestampModeHardcharger(BaseSnapshotNewRecordTimestampMode):
    pass


class TestSnapshotColumnNamesHardcharger(BaseSnapshotColumnNames):
    pass


class TestSnapshotColumnNamesFromDbtProjectHardcharger(BaseSnapshotColumnNamesFromDbtProject):
    pass


class TestSnapshotMultiUniqueKeyHardcharger(BaseSnapshotMultiUniqueKey):
    pass
