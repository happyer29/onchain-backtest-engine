"""Allowlisted exact source bundle graph for the checked-in reference stack."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from hashlib import sha256

# Import pathlib at the visible module dependency boundary.
from pathlib import Path
from typing import Final, Self, cast

from backtest.application.canonical_json import canonicalize_job_payload
from backtest.application.code_bundles import (
    CodeBundleDependency,
    # Include code bundle integrity error so the code bundles dependency remains explicit.
    CodeBundleIntegrityError,
    CodeSourceFile,
    ExactCodeBundleClosure,
    ExactCodeBundleManifest,
)
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_UNIVERSE_POLICY_ID

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import ContentDigest

_PACKAGE_ROOT: Final = Path(__file__).resolve().parents[1]
_PACKAGE_NAME: Final = "local-backtest/reference"

_DOMAIN_SOURCES: Final = (
    # Keep the domain init py component named inside the domain sources contract.
    "domain/__init__.py",
    "domain/event_hashing.py",
    "domain/execution.py",
    "domain/fidelity.py",
    "domain/hashing.py",
    # Keep the domain identifiers py component named inside the domain sources contract.
    "domain/identifiers.py",
    "domain/intents.py",
    "domain/ledger.py",
    "domain/market_events.py",
    "domain/time.py",
    # Complete the domain sources group only after its semantic components are visible.
)
_ENGINE_SOURCES: Final = (
    "engine/__init__.py",
    "engine/audit.py",
    "engine/causal_data.py",
    # Keep the engine contracts py component named inside the engine sources contract.
    "engine/contracts.py",
    "engine/portfolio.py",
    "engine/reference.py",
    "engine/replay.py",
    "engine/rng.py",
    # Keep the engine scheduler py component named inside the engine sources contract.
    "engine/scheduler.py",
    "engine/state.py",
)

_SNIPING_DOMAIN_SOURCES: Final = (
    "domain/__init__.py",
    "domain/account_requirements.py",
    # Keep the domain chain py component named inside the sniping domain sources contract.
    "domain/chain.py",
    "domain/event_hashing.py",
    "domain/execution.py",
    "domain/fidelity.py",
    "domain/hashing.py",
    # Keep the domain identifiers py component named inside the sniping domain sources
    # contract.
    "domain/identifiers.py",
    "domain/intents.py",
    "domain/ledger.py",
    "domain/market_events.py",
    "domain/roundtrips.py",
    # Keep the domain time py component named inside the sniping domain sources contract.
    "domain/time.py",
)
_SNIPING_ENGINE_SOURCES: Final = (
    "engine/__init__.py",
    "engine/audit.py",
    # Keep the engine portfolio py component named inside the sniping engine sources
    # contract.
    "engine/portfolio.py",
    "engine/replay.py",
    "engine/rng.py",
    "engine/scheduler.py",
    "engine/sniping.py",
    # Keep the engine sniping contracts py component named inside the sniping engine
    # sources contract.
    "engine/sniping_contracts.py",
    "engine/transaction_clock.py",
    "engine/wallet_accounts.py",
)


class ReferenceBundleIntegrityError(RuntimeError):
    """The installed reference source tree does not match an exact bundle graph."""


@dataclass(frozen=True, slots=True)
class ReferenceBundleDeclaration:
    """Composition-owned allowlist entry; new roles need an explicit declaration."""

    role: str
    api_version: int
    package_name: str
    canonical_contract: bytes
    source_paths: tuple[str, ...]
    # Declare dependency roles explicitly in the reference bundle declaration contract.
    dependency_roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Execute the reference bundle declaration post init workflow in explicit,
        # reviewable steps.
        if not self.role or self.role != self.role.strip() or "\x00" in self.role:
            raise ValueError("reference bundle role must be non-empty and trimmed")
        if self.api_version <= 0:
            raise ValueError("reference bundle API version must be positive")
        if not self.package_name or self.package_name != self.package_name.strip():
            # Fail the reference bundle declaration post init path with ValueError for
            # reference bundle package name must be non-empty and trimmed when package
            # name and strip is true; do not continue ambiguously.
            raise ValueError("reference bundle package name must be non-empty and trimmed")
        if canonicalize_job_payload(self.canonical_contract) != self.canonical_contract:
            raise ValueError("reference bundle contract must be canonical JSON")
        if not self.source_paths or self.source_paths != tuple(sorted(set(self.source_paths))):
            raise ValueError("reference bundle source paths must be sorted, unique and non-empty")
        # Traverse self.source_paths explicitly so each reference bundle declaration post
        # init iteration remains traceable.
        for path in self.source_paths:
            CodeSourceFile(path, ContentDigest("0" * 64), 0)
        if self.dependency_roles != tuple(sorted(set(self.dependency_roles))):
            raise ValueError("reference bundle dependencies must be sorted and unique")
        if self.role in self.dependency_roles:
            # Fail the reference bundle declaration post init path with ValueError for
            # reference bundle cannot depend on itself when role and dependency roles is
            # true; do not continue ambiguously.
            raise ValueError("reference bundle cannot depend on itself")

    @classmethod
    def create(
        cls,
        *,
        # Keep the role input explicit in the create contract.
        role: str,
        contract: dict[str, object],
        source_paths: tuple[str, ...],
        dependency_roles: tuple[str, ...] = (),
        api_version: int = 1,
        # Keep the package name input explicit in the create contract.
        package_name: str | None = None,
    ) -> Self:
        # Execute the reference bundle declaration create workflow in explicit, reviewable
        # steps.
        return cls(
            role=role,
            api_version=api_version,
            package_name=package_name or f"{_PACKAGE_NAME}/{role}",
            canonical_contract=canonicalize_job_payload(canonical_json_bytes(contract)),
            # Include source paths in the completed reference bundle declaration create
            # result.
            source_paths=tuple(sorted(source_paths)),
            dependency_roles=tuple(sorted(dependency_roles)),
        )

    @property
    def contract_digest(self) -> ContentDigest:
        # Execute the reference bundle declaration contract digest workflow in explicit,
        # reviewable steps.
        return domain_digest(
            "backtest.reference-bundle-contract.v1",
            cast(dict[str, object], json.loads(self.canonical_contract)),
        )


def _declaration(
    # Keep the role input explicit in the declaration contract.
    role: str,
    contract: dict[str, object],
    source_paths: tuple[str, ...],
    dependencies: tuple[str, ...] = (),
) -> ReferenceBundleDeclaration:
    # Execute the declaration workflow in explicit, reviewable steps.
    return ReferenceBundleDeclaration.create(
        role=role,
        contract=contract,
        source_paths=source_paths,
        dependency_roles=dependencies,
        # Complete create only after its role and contract inputs are visible in declaration.
    )


REFERENCE_BUNDLE_DECLARATIONS: Final = (
    _declaration(
        "clock",
        {"duration_mapping": "ceil-to-next-boundary-v1"},
        # Open the clock and duration mapping payload explicitly for _declaration within
        # module.
        ("engine/scheduler.py",),
    ),
    _declaration(
        "engine",
        {
            # Keep arithmetic named so the engine and arithmetic payload passed to
            # _declaration remains self-describing within module.
            "arithmetic": "checked-integer-v1",
            "audit": "canonical-stream-v1",
            "group_policy": "atomic-v1",
            "scheduler": "canonical-phases-v1",
        },
        # Pass domain sources explicitly so _declaration receives a reviewable engine and
        # arithmetic input in module.
        _DOMAIN_SOURCES + _ENGINE_SOURCES,
        (
            "clock",
            "execution",
            "inference",
            # Pass latency explicitly so _declaration receives a reviewable engine and
            # arithmetic input in module.
            "latency",
            "protocol:reference_amm",
            "risk",
            "scheduler",
            "strategy",
            # Pass universe explicitly so _declaration receives a reviewable engine and
            # arithmetic input in module.
            "universe",
            "valuation:price_source",
        ),
    ),
    _declaration(
        # Pass execution explicitly so _declaration receives a reviewable execution and
        # arithmetic input in module.
        "execution",
        {"arithmetic": "checked-integer-floor-v1", "contract": "constant-product-v1"},
        ("plugins/execution/constant_product.py",),
        ("protocol:reference_amm",),
    ),
    # Register inference through _declaration so the reference bundle declarations table
    # remains scannable.
    _declaration(
        "inference",
        {
            "arithmetic": "checked-python-integer-floor-int64-output-v1",
            "availability": "max-feature-selected-model-fitted-inference-completion-v1",
            # Keep completion named so the inference and arithmetic payload passed to
            # _declaration remains self-describing within module.
            "completion": "max-input-availability-plus-delay-boundaries-v1",
            "gap_policy": "reject-uncovered-or-use-explicit-hashed-fallback-v1",
            "modes": ["DISABLED", "EMBEDDED_BATCH", "FROZEN"],
            "model_kind": "exact-rational-linear-v1",
            "precompute": "bounded-temporary-mmap-before-hot-loop-v1",
            # Close the inference and arithmetic payload only after all module fields are
            # present.
        },
        (
            "adapters/ml/numpy/embedded.py",
            "adapters/ml/numpy/layout.py",
            "adapters/ml/numpy/overlays.py",
            # Pass adapters ml numpy pipelines explicitly so _declaration receives a
            # reviewable inference and arithmetic input in module.
            "adapters/ml/numpy/pipelines.py",
            "adapters/ml/numpy/publisher.py",
            "adapters/ml/numpy/reader.py",
            "application/ml_artifacts.py",
            "application/ml_contracts.py",
            # Pass application ports runs py explicitly so _declaration receives a
            # reviewable inference and arithmetic input in module.
            "application/ports/runs.py",
            "application/run_drafts.py",
            "application/run_specs.py",
            "application/use_cases/run_backtest.py",
            "engine/causal_data.py",
            # Complete _declaration only after its inference and arithmetic inputs are visible
            # in module.
        ),
        ("scheduler",),
    ),
    _declaration(
        "latency",
        # Open the latency and rounding payload explicitly for _declaration within module.
        {"rounding": "ceil-to-first-real-boundary-v1", "unit": "slot"},
        ("engine/reference.py", "engine/scheduler.py"),
        ("clock", "scheduler"),
    ),
    _declaration(
        # Pass protocol:reference amm explicitly so _declaration receives a reviewable
        # protocol:reference amm and canonical projection input in module.
        "protocol:reference_amm",
        {"canonical_projection": "reference-amm-v2", "protocol_version": 1},
        ("plugins/protocols/reference/projector.py",),
    ),
    _declaration(
        # Pass risk explicitly so _declaration receives a reviewable risk and policy input
        # in module.
        "risk",
        {"policy": "maximum-input-and-available-balance-v1"},
        ("plugins/risk/static.py",),
    ),
    _declaration(
        # Pass scheduler explicitly so _declaration receives a reviewable scheduler and
        # key input in module.
        "scheduler",
        {"key": "canonical-v1", "phase_table": "canonical-v1"},
        ("engine/rng.py", "engine/scheduler.py"),
        ("clock",),
    ),
    # Register strategy through _declaration so the reference bundle declarations table
    # remains scannable.
    _declaration(
        "strategy",
        {
            "contract": "first-observed-swap-exact-in-v1",
            "fidelity_contract": "first-swap-minimum-fidelity-v1",
            # Close the strategy and contract payload only after all module fields are
            # present.
        },
        ("plugins/strategies/first_swap.py",),
        ("protocol:reference_amm", "universe"),
    ),
    _declaration(
        # Pass universe explicitly so _declaration receives a reviewable universe and
        # policy input in module.
        "universe",
        {"policy": "point-in-time-observed-assets-v1"},
        ("engine/state.py",),
        ("protocol:reference_amm",),
    ),
    # Register valuation:price source through _declaration so the reference bundle
    # declarations table remains scannable.
    _declaration(
        "valuation:price_source",
        {"policy": "none-v1"},
        ("engine/portfolio.py",),
    ),
    # Complete the reference bundle declarations group only after its semantic components are
    # visible.
)


PUMPFUN_SNIPING_BUNDLE_DECLARATIONS: Final = (
    _declaration(
        "clock",
        {
            # Keep block time resolution named so the clock and block time resolution
            # payload passed to _declaration remains self-describing within module.
            "block_time_resolution": "seconds-v1",
            "duration_mapping": "first-future-nonempty-block-v1",
            "transaction_mapping": "global-transaction-prefix-v1",
        },
        ("domain/chain.py", "engine/transaction_clock.py"),
        # Complete _declaration only after its clock and block time resolution inputs are
        # visible in module.
    ),
    _declaration(
        "engine",
        {
            "arithmetic": "checked-integer-v1",
            # Keep audit named so the engine and arithmetic payload passed to _declaration
            # remains self-describing within module.
            "audit": "canonical-sniping-streams-v2",
            "backend": "reference-pumpfun-sniping-v1",
            "execution_modes": [
                "EXOGENOUS_REPLAY",
                "EXOGENOUS_VIRTUAL_SETTLEMENT",
            ],
            # Atomic historical grouping remains identical in both settlement modes.
            "group_policy": "atomic-v1",
            "scheduler": "historical-synthetic-two-way-merge-v1",
            # Close the engine and arithmetic payload only after all module fields are
            # present.
        },
        _SNIPING_DOMAIN_SOURCES + _SNIPING_ENGINE_SOURCES,
        (
            "clock",
            "execution",
            # Pass inference explicitly so _declaration receives a reviewable engine and
            # arithmetic input in module.
            "inference",
            "latency",
            "network:solana",
            "protocol:pumpfun",
            "risk",
            # Pass scheduler explicitly so _declaration receives a reviewable engine and
            # arithmetic input in module.
            "scheduler",
            "strategy",
            "universe",
            "valuation:price_source",
        ),
        # Complete _declaration only after its engine and arithmetic inputs are visible in
        # module.
    ),
    _declaration(
        "execution",
        {
            "account_lifecycle": "pumpfun-solana-wallet-account-profile-v2",
            # Keep contract named so the execution and account lifecycle payload passed to
            # _declaration remains self-describing within module.
            "contract": "pumpfun-roundtrip-exogenous-settlement-v2",
            "ledger": "correlated-integer-double-entry-v2",
            # Both sell-funding policies are explicit members of the exact code bundle.
            "sell_settlement_policies": [
                "real-reserve-capped-v1",
                "virtual-reserve-output-with-explicit-synthetic-shortfall-v1",
            ],
            # Successful synthetic proceeds are explicitly reusable by the wallet.
            "synthetic_proceeds_policy": "spendable-synthetic-proceeds-v1",
        },
        (
            "domain/ledger.py",
            "domain/account_requirements.py",
            # Pass engine portfolio py explicitly so _declaration receives a reviewable
            # execution and account lifecycle input in module.
            "engine/portfolio.py",
            "engine/sniping.py",
            "engine/sniping_contracts.py",
            "engine/wallet_accounts.py",
        ),
        ("network:solana", "protocol:pumpfun"),
        # Complete _declaration only after its execution and account lifecycle inputs are
        # visible in module.
    ),
    _declaration(
        "inference",
        {"mode": "DISABLED", "policy": "no-feature-or-model-input-v1"},
        ("application/ml_contracts.py",),
        # Complete _declaration only after its inference and mode inputs are visible in
        # module.
    ),
    _declaration(
        "latency",
        {
            "buy_transactions": 500,
            # Keep sell decision seconds named so the latency and buy transactions payload
            # passed to _declaration remains self-describing within module.
            "sell_decision_seconds": 2,
            "sell_transactions": "resolved-positive-integer",
        },
        (
            "domain/intents.py",
            # Pass engine sniping py explicitly so _declaration receives a reviewable
            # latency and buy transactions input in module.
            "engine/sniping.py",
            "engine/transaction_clock.py",
        ),
        ("clock", "scheduler"),
    ),
    # Register network:solana through _declaration so the pumpfun sniping bundle
    # declarations table remains scannable.
    _declaration(
        "network:solana",
        {
            "account_costs": "effective-dated-component-deposit-v2",
            "fee_formula": "base-plus-ceil-priority-v1",
            # Keep jito tip named so the network:solana and account costs payload passed
            # to _declaration remains self-describing within module.
            "jito_tip": "excluded",
        },
        (
            "plugins/networks/solana/costs.py",
            "plugins/networks/solana/sniping.py",
            # Complete _declaration only after its network:solana and account costs inputs are
            # visible in module.
        ),
    ),
    _declaration(
        "protocol:pumpfun",
        {
            # Keep curve state named so the protocol:pumpfun and curve state payload
            # passed to _declaration remains self-describing within module.
            "curve_state": "pump-curve-state-v1",
            "execution": "bonding-curve-only-v1",
            "sell_settlement_policies": [
                "real-reserve-capped-v1",
                "virtual-reserve-output-with-explicit-synthetic-shortfall-v1",
            ],
            # Existing launch, lifecycle, and trade payload schemas remain unchanged.
            "payloads": [
                "pump-launch-state-v1",
                "pump-lifecycle-state-v1",
                # Pass pump-trade-state-v1 explicitly so _declaration receives a
                # reviewable protocol:pumpfun and curve state input in module.
                "pump-trade-state-v1",
            ],
        },
        (
            "plugins/protocols/pumpfun/model.py",
            "plugins/protocols/pumpfun/accounts.py",
            # Pass plugins protocols pumpfun sniping explicitly so _declaration receives a
            # reviewable protocol:pumpfun and curve state input in module.
            "plugins/protocols/pumpfun/sniping.py",
        ),
    ),
    _declaration(
        "risk",
        # Open the risk and reservation payload explicitly for _declaration within module.
        {
            "reservation": "shared-wallet-ata-uva-v2",
            "sell_fee_reservation": "forbidden",
        },
        ("engine/portfolio.py", "engine/sniping.py", "engine/wallet_accounts.py"),
        # Complete _declaration only after its risk and reservation inputs are visible in
        # module.
    ),
    _declaration(
        "scheduler",
        {
            "key": "release-phase-creator-stable-id-v1",
            # Keep phase table named so the scheduler and key payload passed to
            # _declaration remains self-describing within module.
            "phase_table": "canonical-v1",
        },
        ("engine/scheduler.py", "engine/sniping.py"),
        ("clock",),
    ),
    # Register strategy through _declaration so the pumpfun sniping bundle declarations
    # table remains scannable.
    _declaration(
        "strategy",
        {
            "contract": "pumpfun-sniping-roundtrip-v4",
            "cooldown_seconds": 600,
            # Keep developer identity named so the strategy and contract payload passed to
            # _declaration remains self-describing within module.
            "developer_identity": "immutable-create-event-creator-v1",
        },
        # Strategy identity depends on both the generic mode and emitted intent contract.
        (
            "domain/execution.py",
            "domain/intents.py",
            "plugins/strategies/pumpfun_sniping.py",
        ),
        ("protocol:pumpfun", "universe"),
    ),
    # Register universe through _declaration so the pumpfun sniping bundle declarations
    # table remains scannable.
    _declaration(
        "universe",
        {"policy": PUMPFUN_SNIPING_UNIVERSE_POLICY_ID},
        ("engine/sniping.py",),
        ("protocol:pumpfun",),
        # Complete _declaration only after its universe and policy inputs are visible in
        # module.
    ),
    _declaration(
        "valuation:price_source",
        {"policy": "pump-last-active-net-liquidation-v1"},
        ("engine/sniping.py", "plugins/protocols/pumpfun/sniping.py"),
        # Open the valuation:price source and policy payload explicitly for _declaration
        # within module.
        ("network:solana", "protocol:pumpfun"),
    ),
)


class ReferenceBundleRegistry:
    """Rebuild and verify the allowlisted graph from installed source bytes."""

    def __init__(
        self,
        package_root: Path | None = None,
        *,
        declarations: tuple[ReferenceBundleDeclaration, ...] = REFERENCE_BUNDLE_DECLARATIONS,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the reference bundle registry init workflow in explicit, reviewable
        # steps.
        root = _PACKAGE_ROOT if package_root is None else package_root
        self._package_root = root.resolve(strict=True)
        ordered = tuple(sorted(declarations, key=lambda item: item.role))
        if not ordered or len({item.role for item in ordered}) != len(ordered):
            raise ValueError("reference bundle declarations must be non-empty and unique")
        # Assemble self declarations once so the reference bundle registry init workflow
        # shares one value.
        self._declarations = ordered

    @property
    def package_root(self) -> Path:
        return self._package_root

    @property
    # Define reference bundle registry declarations as one focused operation with an
    # explicit boundary.
    def declarations(self) -> tuple[ReferenceBundleDeclaration, ...]:
        return self._declarations

    def snapshot(self) -> ExactCodeBundleClosure:
        # Execute the reference bundle registry snapshot workflow in explicit, reviewable
        # steps.
        by_role = {item.role: item for item in self._declarations}
        missing = sorted(
            {
                dependency
                for declaration in self._declarations
                # Pass dependency explicitly so sorted receives a reviewable declarations
                # and dependency roles input in reference bundle registry snapshot.
                for dependency in declaration.dependency_roles
                if dependency not in by_role
            }
        )
        if missing:
            # Handle the reference bundle registry snapshot missing branch as a distinct
            # logical block.
            raise ReferenceBundleIntegrityError(
                f"reference bundle declarations have unresolved roles: {missing}"
            )
        manifests: dict[str, ExactCodeBundleManifest] = {}
        visiting: set[str] = set()
        # Assemble source cache once so the reference bundle registry snapshot workflow
        # shares one value.
        source_cache: dict[str, CodeSourceFile] = {}

        def resolve(role: str) -> ExactCodeBundleManifest:
            # Execute the reference bundle registry resolve workflow in explicit,
            # reviewable steps.
            existing = manifests.get(role)
            if existing is not None:
                return existing
            if role in visiting:
                raise ReferenceBundleIntegrityError("reference bundle graph contains a cycle")
            # Invoke add for role as a visible reference bundle registry resolve step.
            visiting.add(role)
            declaration = by_role[role]
            dependencies = tuple(
                CodeBundleDependency(
                    dependency_role,
                    # Keep the dependency role resolve step visible while building
                    # dependencies.
                    resolve(dependency_role).bundle_id,
                    by_role[dependency_role].api_version,
                )
                for dependency_role in declaration.dependency_roles
            )
            # Assemble files once so the reference bundle registry resolve workflow shares
            # one value.
            files = tuple(
                source_cache.setdefault(path, self._read_source(path))
                for path in declaration.source_paths
            )
            manifest = ExactCodeBundleManifest.create(
                # Pass role explicitly so create receives a reviewable api version and
                # package name input in reference bundle registry resolve.
                role=role,
                api_version=declaration.api_version,
                package_name=declaration.package_name,
                contract_digest=declaration.contract_digest,
                source_files=files,
                # Pass direct dependencies explicitly so create receives a reviewable api
                # version and package name input in reference bundle registry resolve.
                direct_dependencies=dependencies,
            )
            visiting.remove(role)
            manifests[role] = manifest
            return manifest

        # Keep expected failures inside the reference bundle registry snapshot error
        # boundary.
        try:
            # Perform the protected reference bundle registry snapshot operation before
            # explicit failure handling.
            closure = ExactCodeBundleClosure(
                tuple(sorted((resolve(role) for role in by_role), key=lambda item: item.role))
            )
        except CodeBundleIntegrityError as error:
            # Translate the CodeBundleIntegrityError failure through the reference bundle
            # registry snapshot boundary.
            raise ReferenceBundleIntegrityError(
                "reference bundle closure failed exact verification"
            ) from error
        return closure

    def _read_source(self, relative_path: str) -> CodeSourceFile:
        # Execute the reference bundle registry read source workflow in explicit,
        # reviewable steps.
        candidate = self._package_root.joinpath(*relative_path.split("/"))
        try:
            # Perform the protected reference bundle registry read source operation before
            # explicit failure handling.
            if candidate.is_symlink():
                # Handle the reference bundle registry read source candidate.is_symlink()
                # branch as a distinct logical block.
                raise ReferenceBundleIntegrityError(
                    f"reference bundle source is a symlink: {relative_path}"
                )
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(self._package_root):
                # Handle the reference bundle registry read source is relative to, package
                # root and resolved condition as a distinct block.
                raise ReferenceBundleIntegrityError(
                    f"reference bundle source escapes package root: {relative_path}"
                )
            before = resolved.stat()
            if not stat.S_ISREG(before.st_mode):
                # Handle the reference bundle registry read source not
                # stat.S_ISREG(before.st_mode) branch as a distinct logical block.
                raise ReferenceBundleIntegrityError(
                    f"reference bundle source is not a regular file: {relative_path}"
                )
            payload = resolved.read_bytes()
            after = resolved.stat()
        # Translate reference bundle integrity error through the reference bundle registry
        # read source boundary without hiding other errors.
        except ReferenceBundleIntegrityError:
            raise
        except OSError as error:
            # Translate the OSError failure through the reference bundle registry read
            # source boundary.
            raise ReferenceBundleIntegrityError(
                f"reference bundle source is unavailable: {relative_path}"
            ) from error
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        # Evaluate the complete reference bundle registry read source before identity,
        # after identity and st size condition before guarded effects.
        if before_identity != after_identity or len(payload) != after.st_size:
            # Handle the reference bundle registry read source before identity, after
            # identity and st size condition as a distinct block.
            raise ReferenceBundleIntegrityError(
                f"reference bundle source changed while hashing: {relative_path}"
            )
        return CodeSourceFile(
            relative_path,
            # Include content digest in the completed reference bundle registry read
            # source result.
            ContentDigest(sha256(payload).hexdigest()),
            len(payload),
        )


class PumpfunSnipingBundleRegistry(ReferenceBundleRegistry):
    """Exact checked-in semantic closure for Pump.fun Sniping v3 only."""

    def __init__(self, package_root: Path | None = None) -> None:
        # Execute the pumpfun sniping bundle registry init workflow in explicit,
        # reviewable steps.
        super().__init__(
            package_root,
            declarations=PUMPFUN_SNIPING_BUNDLE_DECLARATIONS,
        )


__all__ = [
    # Keep the pumpfun sniping bundle declarations component named inside the all
    # contract.
    "PUMPFUN_SNIPING_BUNDLE_DECLARATIONS",
    "REFERENCE_BUNDLE_DECLARATIONS",
    "PumpfunSnipingBundleRegistry",
    "ReferenceBundleDeclaration",
    "ReferenceBundleIntegrityError",
    # Keep the reference bundle registry component named inside the all contract.
    "ReferenceBundleRegistry",
]
