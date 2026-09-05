"""Canonical source-schema fingerprinting for inspection-v5.

The fingerprint belongs to the application contract rather than to a concrete
source adapter.  It deliberately excludes the logical source identifier and
inspection time: two indexers exposing the same schema and capabilities must
produce the same value.  Cut-specific proof outcomes and receipts are excluded;
the exact inspection artifact pins those separately.
"""

from __future__ import annotations

import json
from hashlib import sha256

from backtest.application.models import SourceMetadata
from backtest.domain.identifiers import ContentDigest


# Define source schema fingerprint as one focused operation with an explicit boundary.
def source_schema_fingerprint(metadata: SourceMetadata) -> ContentDigest:
    """Return the stable v5 digest of secret-free source schema metadata.

    Cut-dependent proof and fidelity promotion is deliberately excluded.  A
    preparation preflight must be able to compare fresh declarative metadata
    with the schema pinned by an evidence-bearing inspection without rerunning
    the expensive bounded evidence pass.
    """

    payload = {
        "capabilities": [
            {
                "capability_id": capability.capability_id.value,
                "columns": list(capability.columns),
                "keyset_key_is_proven": capability.keyset_key_is_proven,
                # Register mandatory columns through list so the payload table remains
                # scannable.
                "mandatory_columns": list(capability.mandatory_columns),
                "protocol": capability.protocol,
                "protocol_version": capability.protocol_version,
                "schema_version": capability.schema_version,
                "stream": capability.stream.value,
                # Register total key through list so the payload table remains scannable.
                "total_key": list(capability.total_key),
                "utc_pruning_column": capability.utc_pruning_column,
                "utc_pruning_is_proven": capability.utc_pruning_is_proven,
            }
            for capability in metadata.capabilities
            # Complete the payload group only after its semantic components are visible.
        ],
        "network_id": metadata.network_id.value,
        "position_schema_id": metadata.position_schema_id.value,
        "schema": "source-schema-fingerprint/v5",
        "query_template_digest": (
            # Keep the metadata component named inside the payload contract.
            metadata.query_template_digest.hex
            if metadata.query_template_digest is not None
            else None
        ),
        "server_version": metadata.server_version,
        # Keep the tables component named inside the payload contract.
        "tables": [
            {
                "columns": [
                    {
                        "name": column.name,
                        # Keep the nullable component named inside the payload contract.
                        "nullable": column.nullable,
                        "type_name": column.type_name,
                    }
                    for column in table.columns
                ],
                # Keep the engine component named inside the payload contract.
                "engine": table.engine,
                "name": table.name,
                "partition_key": table.partition_key,
                "sorting_key": table.sorting_key,
            }
            # Keep the table component named inside the payload contract.
            for table in metadata.tables
        ],
    }
    encoded = json.dumps(
        payload,
        # Pass ensure ascii explicitly so encode receives a reviewable utf-8 input in
        # source schema fingerprint.
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ContentDigest(sha256(encoded).hexdigest())


# Bind all once as an explicit module-level contract.
__all__ = ["source_schema_fingerprint"]
