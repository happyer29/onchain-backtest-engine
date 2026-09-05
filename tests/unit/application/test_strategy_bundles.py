# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from hashlib import sha256

import pytest

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository

# Import strategy bundles at the visible module dependency boundary.
from backtest.adapters.artifacts.strategy_bundles import (
    LocalStrategyBundleStore,
    StrategyBundleIntegrityError,
)
from backtest.application.strategy_bundles import (
    # Include strategy bundle manifest so the strategy bundles dependency remains
    # explicit.
    StrategyBundleManifest,
    StrategyResourceClass,
    strategy_bundle_manifest_from_bytes,
)
from backtest.domain.execution import ExecutionMode

# Import fidelity at the visible module dependency boundary.
from backtest.domain.fidelity import FidelityRequirement, IdentityFidelity, OrderingFidelity
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import ContentDigest, RuntimeLockId


def _manifest(code: bytes) -> StrategyBundleManifest:
    # Execute the manifest workflow in explicit, reviewable steps.
    return StrategyBundleManifest(
        api_version=1,
        code_digest=ContentDigest(sha256(code).hexdigest()),
        package_format="inert-wheel-archive-v1",
        config_schema_json=canonical_json_bytes(
            # Open the properties and required payload explicitly for canonical_json_bytes
            # within manifest.
            {
                "properties": {"threshold_ppm": {"minimum": 0, "type": "integer"}},
                "required": ["threshold_ppm"],
                "type": "object",
            }
            # Complete canonical_json_bytes only after its properties and required inputs are
            # visible in manifest.
        ),
        default_config_json=canonical_json_bytes({"threshold_ppm": 500_000}),
        requirements=("solana.swaps.v1",),
        dependency_lock_digest=domain_digest("test.lock", {}),
        runtime_compatibility_id=RuntimeLockId(domain_digest("test.runtime", {}).hex),
        # Include tests digest in the completed manifest result.
        tests_digest=domain_digest("test.tests", {}),
        golden_metadata_digest=domain_digest("test.golden", {}),
        subscriptions=("SWAP",),
        minimum_fidelity=FidelityRequirement(
            identity=IdentityFidelity.EXACT,
            # Pass ordering explicitly so FidelityRequirement receives a reviewable exact
            # and transaction exact input in manifest.
            ordering=OrderingFidelity.TRANSACTION_EXACT,
        ),
        supported_execution_modes=(ExecutionMode.SHADOW_STATE_REPLAY,),
        estimated_dynamic_state_bytes=4096,
        resource_class=StrategyResourceClass.LIGHT,
        # Complete StrategyBundleManifest only after its inert-wheel-archive-v1 and properties
        # inputs are visible in manifest.
    )


def test_strategy_manifest_round_trip_is_exact_and_secret_free() -> None:
    # Execute the test strategy manifest round trip is exact and secret free workflow in
    # explicit, reviewable steps.
    manifest = _manifest(b"wheel bytes")
    assert strategy_bundle_manifest_from_bytes(manifest.manifest_bytes()) == manifest

    value = json.loads(manifest.manifest_bytes())
    value["default_config"]["api_key"] = "forbidden"
    with pytest.raises(ValueError, match="credential"):
        # Invoke strategy_bundle_manifest_from_bytes for canonical json bytes and value as
        # a visible test strategy manifest round trip is exact and secret free step.
        strategy_bundle_manifest_from_bytes(canonical_json_bytes(value))


def test_local_strategy_bundle_is_content_addressed_but_not_dynamically_loaded(
    tmp_path: object,
) -> None:
    # Execute the test local strategy bundle is content addressed but not dynamically
    # loaded workflow in explicit, reviewable steps.
    from pathlib import Path

    code = b"exact inert strategy wheel bytes"
    store = LocalStrategyBundleStore(LocalArtifactRepository(Path(str(tmp_path))))
    published = store.publish(_manifest(code), code)
    reopened = store.open(published.bundle_id)

    # Verify reopened == published before this scenario is accepted.
    assert reopened == published
    assert reopened.manifest.load_policy == "composition-root-allowlist-only-v1"
    assert reopened.bundle_id.hex == reopened.artifact.artifact_id.hex


def test_strategy_publisher_rejects_code_substitution(tmp_path: object) -> None:
    # Execute the test strategy publisher rejects code substitution workflow in explicit,
    # reviewable steps.
    from pathlib import Path

    store = LocalStrategyBundleStore(LocalArtifactRepository(Path(str(tmp_path))))
    with pytest.raises(StrategyBundleIntegrityError, match="digest"):
        store.publish(_manifest(b"expected"), b"substituted")
