from dbt.adapters.base.relation import BaseRelation, Policy


class HardchargerIncludePolicy(Policy):
    database: bool = True
    schema: bool = True
    identifier: bool = True


class HardchargerQuotePolicy(Policy):
    database: bool = True
    schema: bool = True
    identifier: bool = True


class HardchargerRelation(BaseRelation):
    include_policy = HardchargerIncludePolicy()
    quote_policy = HardchargerQuotePolicy()
