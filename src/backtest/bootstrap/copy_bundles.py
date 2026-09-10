"""Allowlisted copy-only bundle closure over shared Pump math and new execution code."""

from pathlib import Path

from backtest.application.copy_run_contract import COPY_RUN_CONTRACT
from backtest.bootstrap.reference_bundles import (
    PUMPFUN_SNIPING_BUNDLE_DECLARATIONS,
    # Copy bundles reuse explicit dependency roles without claiming Sniping run semantics.
    ReferenceBundleDeclaration,
    ReferenceBundleRegistry,
)

# These explicit source paths extend the shared pure arithmetic without code discovery.
_COPY_SOURCES = (
    "application/copy_run_contract.py",
    "application/run_drafts.py",
    "bootstrap/copy_bundles.py",
    "bootstrap/copy_runtime.py",
    # The configured source/evidence contract is rechecked before each execution.
    "application/copy_source.py",
    "application/copy_source_contracts.py",
    "application/source_evidence.py",
    "bootstrap/sniping_runtime.py",
    "domain/copytrading.py",
    # Scheduler, financial reducer and immutable outputs are all execution dependencies.
    "engine/copytrading.py",
    "engine/copytrading_contracts.py",
    "engine/copytrading_execution.py",
    "engine/copytrading_results.py",
    "engine/copytrading_run.py",
    # A new actor-bearing codec cannot inherit an older signerless payload identity.
    "engine/copytrading_state.py",
    "plugins/protocols/pumpfun/copybuy.py",
    "plugins/protocols/pumpfun/copybuy_payload.py",
    "plugins/strategies/pumpfun_copybuy.py",
)


def _declarations() -> tuple[ReferenceBundleDeclaration, ...]:
    """Share a dependency topology, while every copy role gets its own contract identity."""
    values = []
    for shared in PUMPFUN_SNIPING_BUNDLE_DECLARATIONS:
        values.append(
            ReferenceBundleDeclaration.create(
                role=shared.role,
                # Every role is separately named under the copy run contract.
                contract={"contract": COPY_RUN_CONTRACT, "role": shared.role},
                # Pin the full transitive copy source closure plus the existing shared math.
                source_paths=tuple(sorted(set(shared.source_paths + _COPY_SOURCES))),
                dependency_roles=shared.dependency_roles,
                package_name=f"local-backtest/pumpfun-copy-buy/{shared.role}",
            )
        )
    # The immutable declaration tuple preserves the canonical role order.
    return tuple(values)


class PumpfunCopyBuyBundleRegistry(ReferenceBundleRegistry):
    """Rebuild exact identities from installed immutable source bytes before resolving."""

    def __init__(self, package_root: Path | None = None) -> None:
        super().__init__(package_root, declarations=_declarations())
