# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

# Import code bundles at the visible module dependency boundary.
from backtest.application.code_bundles import (
    CodeBundleIntegrityError,
    ExactCodeBundleClosure,
    exact_code_bundle_manifest_from_bytes,
)

# Import ml contracts at the visible module dependency boundary.
from backtest.application.ml_contracts import ExactInferencePolicy
from backtest.application.run_specs import (
    AssetBalance,
    ReplayInputFormat,
    ResolvedComponent,
    # Include resolved replay input so the run specs dependency remains explicit.
    ResolvedReplayInput,
    ResolvedRunSpec,
)
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_UNIVERSE_POLICY_ID
from backtest.bootstrap.reference_bundles import (
    PUMPFUN_SNIPING_BUNDLE_DECLARATIONS,
    ReferenceBundleDeclaration,
    # Include reference bundle integrity error so the reference bundles dependency remains
    # explicit.
    ReferenceBundleIntegrityError,
    ReferenceBundleRegistry,
)
from backtest.bootstrap.runtime_plugins import (
    ReferenceRuntimeComponentsResolver,
    # Include runtime plugin resolution error so the runtime plugins dependency remains
    # explicit.
    RuntimePluginResolutionError,
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    # Close the chain import after its required symbols are visible.
)
from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    AssetId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    DatasetRevisionId,
    LogicalContentHash,
    RuntimeLockId,
    SnapshotId,
    # Close the identifiers import after its required symbols are visible.
)


def test_reference_bundle_manifests_round_trip_and_reject_tampering() -> None:
    # Execute the test reference bundle manifests round trip and reject tampering workflow
    # in explicit, reviewable steps.
    closure = ReferenceBundleRegistry().snapshot()

    assert tuple(item.role for item in closure.manifests) == (
        "clock",
        "engine",
        "execution",
        # Keep the inference expectation tied to clock, engine and execution in this
        # scenario.
        "inference",
        "latency",
        "protocol:reference_amm",
        "risk",
        "scheduler",
        # Keep the strategy expectation tied to clock, engine and execution in this
        # scenario.
        "strategy",
        "universe",
        "valuation:price_source",
    )
    for manifest in closure.manifests:
        # Process closure.manifests inside the bounded test reference bundle manifests
        # round trip and reject tampering loop.
        assert exact_code_bundle_manifest_from_bytes(manifest.manifest_bytes()) == manifest
        assert all(not Path(item.path).is_absolute() for item in manifest.source_files)

    strategy = closure.manifest_for("strategy")
    tampered = json.loads(strategy.manifest_bytes())
    tampered["source_files"][0]["sha256"] = "0" * 64

    # Acquire raises, code bundle integrity error and pytest at an explicit test reference
    # bundle manifests round trip and reject tampering context boundary so cleanup remains
    # scoped.
    with pytest.raises(CodeBundleIntegrityError, match="code digest"):
        exact_code_bundle_manifest_from_bytes(canonical_json_bytes(tampered))


def test_sniping_universe_bundle_pins_non_mayhem_policy_v2() -> None:
    # Select the declaration rather than trusting the runtime component config alone.
    universe = next(item for item in PUMPFUN_SNIPING_BUNDLE_DECLARATIONS if item.role == "universe")

    assert json.loads(universe.canonical_contract) == {"policy": PUMPFUN_SNIPING_UNIVERSE_POLICY_ID}


def test_source_change_updates_own_bundle_transitive_engine_and_logical_identity(
    tmp_path: Path,
) -> None:
    # Execute the test source change updates own bundle transitive engine and logical
    # identity workflow in explicit, reviewable steps.
    installed = ReferenceBundleRegistry()
    copied_root = _copy_allowlisted_sources(installed, tmp_path / "backtest")
    registry = ReferenceBundleRegistry(copied_root)
    first_closure = registry.snapshot()
    first_spec = _spec(first_closure)
    # Assemble runtime once so the test source change updates own bundle transitive engine
    # and logical identity workflow shares one value.
    runtime = ReferenceRuntimeComponentsResolver(first_spec.runtime_lock_id, registry)

    resolved = runtime.resolve(first_spec)
    assert tuple(item.role for item in resolved.receipts) == tuple(
        item.role for item in first_closure.manifests
    )

    # Assemble strategy path once so the test source change updates own bundle transitive
    # engine and logical identity workflow shares one value.
    strategy_path = copied_root / "plugins" / "strategies" / "first_swap.py"
    strategy_path.write_bytes(strategy_path.read_bytes() + b"\n# changed package bytes\n")
    second_closure = registry.snapshot()
    second_spec = _spec(second_closure)

    assert (
        # Keep the first closure expectation tied to bundle id, manifest for and strategy
        # in this scenario.
        first_closure.manifest_for("strategy").bundle_id
        != second_closure.manifest_for("strategy").bundle_id
    )
    assert (
        first_closure.manifest_for("engine").bundle_id
        # Keep the second closure expectation tied to bundle id, manifest for and engine
        # in this scenario.
        != second_closure.manifest_for("engine").bundle_id
    )
    assert (
        first_closure.manifest_for("risk").bundle_id
        == second_closure.manifest_for("risk").bundle_id
        # Verify the bundle id, manifest for and risk relationship before this scenario is
        # accepted.
    )
    assert first_spec.dependency_merkle_root != second_spec.dependency_merkle_root
    assert first_spec.logical_run_id != second_spec.logical_run_id
    with pytest.raises(RuntimePluginResolutionError, match="installed exact source bytes"):
        runtime.resolve(first_spec)

    # Assemble inference path once so the test source change updates own bundle transitive
    # engine and logical identity workflow shares one value.
    inference_path = copied_root / "adapters" / "ml" / "numpy" / "embedded.py"
    inference_path.write_bytes(inference_path.read_bytes() + b"\n# changed inference bytes\n")
    third_closure = registry.snapshot()
    third_spec = _spec(third_closure)
    assert (
        # Keep the second closure expectation tied to bundle id, manifest for and
        # inference in this scenario.
        second_closure.manifest_for("inference").bundle_id
        != third_closure.manifest_for("inference").bundle_id
    )
    assert (
        second_closure.manifest_for("engine").bundle_id
        # Keep the third closure expectation tied to bundle id, manifest for and engine in
        # this scenario.
        != third_closure.manifest_for("engine").bundle_id
    )
    assert (
        second_closure.manifest_for("strategy").bundle_id
        == third_closure.manifest_for("strategy").bundle_id
        # Verify the bundle id, manifest for and strategy relationship before this scenario is
        # accepted.
    )
    assert second_spec.logical_run_id != third_spec.logical_run_id


def test_missing_source_and_incomplete_transitive_closure_fail_closed(tmp_path: Path) -> None:
    # Execute the test missing source and incomplete transitive closure fail closed
    # workflow in explicit, reviewable steps.
    installed = ReferenceBundleRegistry()
    copied_root = _copy_allowlisted_sources(installed, tmp_path / "backtest")
    registry = ReferenceBundleRegistry(copied_root)
    complete = registry.snapshot()
    (copied_root / "plugins" / "risk" / "static.py").unlink()

    # Acquire raises, reference bundle integrity error and pytest at an explicit test
    # missing source and incomplete transitive closure fail closed context boundary so
    # cleanup remains scoped.
    with pytest.raises(ReferenceBundleIntegrityError, match="unavailable"):
        registry.snapshot()
    with pytest.raises(CodeBundleIntegrityError, match="unresolved dependency"):
        ExactCodeBundleClosure((complete.manifest_for("engine"),))


def test_registry_accepts_an_explicit_new_role_without_role_specific_code(tmp_path: Path) -> None:
    # Execute the test registry accepts an explicit new role without role specific code
    # workflow in explicit, reviewable steps.
    source = tmp_path / "package"
    (source / "plugins").mkdir(parents=True)
    (source / "plugins" / "custom.py").write_text("VALUE = 1\n", encoding="utf-8")
    declaration = ReferenceBundleDeclaration.create(
        role="custom",
        # Pass contract explicitly so create receives a reviewable custom and contract
        # input in test registry accepts an explicit new role without role specific code.
        contract={"contract": "custom-v1"},
        source_paths=("plugins/custom.py",),
    )

    closure = ReferenceBundleRegistry(source, declarations=(declaration,)).snapshot()

    assert tuple(item.role for item in closure.manifests) == ("custom",)


# Define copy allowlisted sources as one focused operation with an explicit boundary.
def _copy_allowlisted_sources(registry: ReferenceBundleRegistry, target: Path) -> Path:
    # Execute the copy allowlisted sources workflow in explicit, reviewable steps.
    for relative_path in sorted(
        {path for declaration in registry.declarations for path in declaration.source_paths}
    ):
        # Process sorted, path and declaration inside the bounded copy allowlisted sources
        # loop.
        source = registry.package_root.joinpath(*relative_path.split("/"))
        destination = target.joinpath(*relative_path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return target


# Define spec as one focused operation with an explicit boundary.
def _spec(closure: ExactCodeBundleClosure) -> ResolvedRunSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    configs: dict[str, dict[str, object]] = {
        "clock": {"duration_mapping": "ceil-to-next-boundary-v1"},
        "engine": {"maximum_dynamic_items": 10_000},
        "execution": {"fee_bps": 30, "mode": ExecutionMode.SHADOW_STATE_REPLAY.value},
        "inference": ExactInferencePolicy.disabled().document(),
        # Keep the latency component named inside the configs contract.
        "latency": {"observation_slots": 0, "order_slots": 0},
        "protocol:reference_amm": {"version": 1},
        "risk": {"maximum_order_input_atomic": 1_000},
        "scheduler": {"phase_table": "canonical-v1"},
        "strategy": {
            # Keep the amount in atomic component named inside the configs contract.
            "amount_in_atomic": 100,
            "bought_asset_id": "TOKEN",
            "minimum_amount_out_atomic": 0,
            "pool_id": "pool",
            "sold_asset_id": "SOL",
            # Complete the configs group only after its semantic components are visible.
        },
        "universe": {"policy": "point-in-time-observed-assets-v1"},
        "valuation:price_source": {"policy": "none-v1"},
    }
    components = tuple(
        # Keep the create and resolved component create step visible while building
        # components.
        ResolvedComponent.create(
            role=manifest.role,
            bundle_id=manifest.bundle_id,
            config=configs[manifest.role],
            api_version=manifest.api_version,
            # Complete create only after its role and bundle id inputs are visible in spec.
        )
        for manifest in closure.manifests
    )
    return ResolvedRunSpec.create(
        network_id=SOLANA_MAINNET_NETWORK_ID,
        # Pass position schema id explicitly so create receives a reviewable 1 and 2 input
        # in spec.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        dataset_revision_id=DatasetRevisionId("1" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=SnapshotId("3" * 64),
        replay_semantics_id=ContentDigest("4" * 64),
        # Include replay input in the completed spec result.
        replay_input=ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET),
        components=components,
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=42,
        # Complete create only after its 1 and 2 inputs are visible in spec.
    )
