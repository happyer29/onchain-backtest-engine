"""Read-only ClickHouse source adapter."""

from backtest.adapters.source.clickhouse.capability_config import (
    CAPABILITY_CONFIG_FORMAT,
    CAPABILITY_CONFIG_SCHEMA_VERSION,
    CapabilityConfigError,
    load_clickhouse_capabilities,
    # Include parse clickhouse capabilities so the capability config dependency remains
    # explicit.
    parse_clickhouse_capabilities,
)
from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import (
    PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION,
    PUMPFUN_INDEXER_V1_PROFILE,
    PUMPFUN_INDEXER_V1_PROFILE_ID,
    PUMPFUN_INDEXER_V1_SENTINEL,
    PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE,
    PumpfunIndexerV1Profile,
    PumpfunIndexerV1Query,
    PumpfunIndexerV1Sentinel,
    build_pumpfun_indexer_v1_query,
    pumpfun_indexer_v1_physical_mapping,
    pumpfun_indexer_v1_query_template_digest,
    registered_pumpfun_indexer_v1_profile,
)
from backtest.adapters.source.clickhouse.query import (
    ClickHouseCapability,
    ClickHouseQueryPolicy,
    # Include proven utc date pruning so the query dependency remains explicit.
    ProvenUtcDatePruning,
    UtcDateRange,
    build_evidence_query,
    build_scan_query,
    clickhouse_capability_mapping_digest,
    # Close the query import after its required symbols are visible.
)
from backtest.adapters.source.clickhouse.reader import (
    ClickHouseClientProtocol,
    ClickHouseSourceReader,
)

# Bind all once as an explicit module-level contract.
__all__ = [
    "CAPABILITY_CONFIG_FORMAT",
    "CAPABILITY_CONFIG_SCHEMA_VERSION",
    "PUMPFUN_INDEXER_V1_CAPABILITY_SCHEMA_VERSION",
    "PUMPFUN_INDEXER_V1_PROFILE",
    "PUMPFUN_INDEXER_V1_PROFILE_ID",
    "PUMPFUN_INDEXER_V1_SENTINEL",
    "PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE",
    "CapabilityConfigError",
    "ClickHouseCapability",
    # Keep the click house client protocol component named inside the all contract.
    "ClickHouseClientProtocol",
    "ClickHouseQueryPolicy",
    "ClickHouseSourceReader",
    "ProvenUtcDatePruning",
    "PumpfunIndexerV1Profile",
    "PumpfunIndexerV1Query",
    "PumpfunIndexerV1Sentinel",
    "UtcDateRange",
    # Keep the build evidence query component named inside the all contract.
    "build_evidence_query",
    "build_pumpfun_indexer_v1_query",
    "build_scan_query",
    "clickhouse_capability_mapping_digest",
    "load_clickhouse_capabilities",
    "parse_clickhouse_capabilities",
    "pumpfun_indexer_v1_physical_mapping",
    "pumpfun_indexer_v1_query_template_digest",
    "registered_pumpfun_indexer_v1_profile",
    # Complete the all group only after its semantic components are visible.
]
