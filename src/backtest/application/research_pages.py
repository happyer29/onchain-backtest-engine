"""Opaque bounded cursors scoped to one immutable research view and pair."""

import base64
import binascii
import json

# Cursor serialization uses core validation, with no access to artifacts or the catalog.
from backtest.application.research import ResearchError, ResearchTable, exact_object, integer
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import ArtifactId


def page_cursor(artifact: ArtifactId, table: ResearchTable, pair: int | None, after: int) -> str:
    """A cursor is a location, never executable input or authorization."""

    document = {
        "schema": "research-cursor/v1",
        "artifact": artifact.hex,
        "table": table.value,
        "pair": pair,
        # The exclusive ordinal locates the next row within this exact view scope.
        "after": after,
    }
    return base64.urlsafe_b64encode(canonical_json_bytes(document)).decode("ascii")


# Parsing is shared by CLI and HTTP so the same cursor has one interpretation.
def cursor_after(
    cursor: str | None, artifact: ArtifactId, table: ResearchTable, pair: int | None
) -> int:
    """Reject cursor reuse across snapshots, result tables or evidence pairs."""

    if cursor is None:
        return -1
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024:
        raise ResearchError("RESEARCH_INVALID_CURSOR")
    # Strict decoding and exact re-encoding reject aliases and malformed cursor documents.
    try:
        raw = base64.b64decode(cursor, altchars=b"-_", validate=True)
        value = exact_object(json.loads(raw), {"schema", "artifact", "table", "pair", "after"})
        after = integer(value["after"])
        # Canonical re-encoding also checks every identity/scope field in the envelope.
        if page_cursor(artifact, table, pair, after) != cursor:
            raise ResearchError("RESEARCH_INVALID_CURSOR")
    except (ValueError, TypeError, binascii.Error):
        raise ResearchError("RESEARCH_INVALID_CURSOR") from None
    return after
