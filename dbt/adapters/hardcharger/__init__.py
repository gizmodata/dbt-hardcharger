from dbt.adapters.base import AdapterPlugin

from dbt.adapters.hardcharger.connections import (
    HardchargerConnectionManager,  # noqa
    HardchargerCredentials,
)
from dbt.adapters.hardcharger.impl import HardchargerAdapter
from dbt.include import hardcharger

__version__ = "2.1.0"

Plugin = AdapterPlugin(
    adapter=HardchargerAdapter,  # type: ignore[arg-type]
    credentials=HardchargerCredentials,
    include_path=hardcharger.PACKAGE_PATH,
)
