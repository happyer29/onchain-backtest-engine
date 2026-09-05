"""Operational identity for one acquired single-host controller instance."""

from __future__ import annotations

from pathlib import Path

from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ContentDigest

CONTROL_PLANE_IDENTITY_SCHEMA = "backtest.control-plane-identity/v1"


# Define control plane identity as one focused operation with an explicit boundary.
def control_plane_identity(data_root: Path, controller_instance_id: str) -> ContentDigest:
    """Bind a loopback API to one resolved data root and held lock instance.

    The raw path and instance identifier remain local. Only this operational
    digest crosses HTTP, and it never participates in run or artifact identity.
    """

    resolved = data_root.resolve()
    if not resolved.is_absolute():  # pragma: no cover - Path.resolve guarantees this
        raise ValueError("data root must resolve to an absolute path")
    if (
        not isinstance(controller_instance_id, str)
        or not 1 <= len(controller_instance_id) <= 128
        or controller_instance_id != controller_instance_id.strip()
        # Keep any visible while evaluating the controller instance id, isinstance and
        # strip guard.
        or any(ord(character) < 33 or ord(character) > 126 for character in controller_instance_id)
    ):
        raise ValueError("controller instance identity is invalid")
    return domain_digest(
        "backtest.control-plane-identity",
        # Open the control-plane-identity and controller instance id payload explicitly
        # for domain_digest within control plane identity.
        {
            "controller_instance_id": controller_instance_id,
            "resolved_data_root": str(resolved),
            "schema": CONTROL_PLANE_IDENTITY_SCHEMA,
        },
        # Complete domain_digest only after its control-plane-identity and controller instance
        # id inputs are visible in control plane identity.
    )


__all__ = ["CONTROL_PLANE_IDENTITY_SCHEMA", "control_plane_identity"]
