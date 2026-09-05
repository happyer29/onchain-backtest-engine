# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from backtest.adapters.artifacts.localfs import (
    # Include data root layout so the localfs dependency remains explicit.
    DataRootLayout,
    LocalArtifactRepository,
    LocalCompletionReceiptStore,
)
from backtest.adapters.catalog.sqlite import SQLiteArtifactCatalog, SQLiteJobQueue

# Import canonical json at the visible module dependency boundary.
from backtest.application.canonical_json import resolved_job_spec_hex
from backtest.application.completion import (
    AttemptCompletionReceipt,
    CompletionOutput,
    CompletionReceiptConflictError,
    # Include completion receipt error so the completion dependency remains explicit.
    CompletionReceiptError,
    CompletionReceiptNotFoundError,
    CompletionVerificationError,
)
from backtest.application.models import (
    # Include artifact draft so the models dependency remains explicit.
    ArtifactDraft,
    ArtifactKind,
    AttemptState,
    CommittedArtifact,
    JobAttempt,
    # Include job type so the models dependency remains explicit.
    JobType,
    ResolvedJobSpec,
    ResourceCapacity,
)
from backtest.application.use_cases.complete_job_attempt import (
    # Include complete job attempt so the complete job attempt dependency remains
    # explicit.
    CompleteJobAttempt,
    CompleteJobAttemptRequest,
)
from backtest.domain.identifiers import ArtifactId, AttemptId, ContentDigest


def _running_attempt(queue: SQLiteJobQueue) -> JobAttempt:
    # Execute the running attempt workflow in explicit, reviewable steps.
    payload = b'{"fixture":"completion"}'
    digest = ContentDigest(sha256(payload).hexdigest())
    spec = ResolvedJobSpec(
        spec_version=1,
        spec_id=ContentDigest(
            # Keep the resolved job spec hex and value resolved_job_spec_hex step visible
            # while building spec.
            resolved_job_spec_hex(
                spec_version=1,
                job_type=JobType.RUN_BACKTEST.value,
                payload_digest_hex=digest.hex,
                input_artifact_hexes=(),
                # Complete resolved_job_spec_hex only after its value and run backtest inputs
                # are visible in running attempt.
            )
        ),
        job_type=JobType.RUN_BACKTEST,
        canonical_payload=payload,
        payload_digest=digest,
        # Complete ResolvedJobSpec only after its value and hex inputs are visible in running
        # attempt.
    )
    queue.submit(spec, "completion")
    attempt = queue.claim_next("supervisor", ResourceCapacity(1_000_000, 1))
    assert attempt is not None
    return queue.transition(
        # Pass attempt explicitly so transition receives a reviewable attempt id and state
        # version input in running attempt.
        attempt.attempt_id,
        attempt.state_version,
        AttemptState.RUNNING,
    )


def _output(repository: LocalArtifactRepository) -> CommittedArtifact:
    # Execute the output workflow in explicit, reviewable steps.
    writer = repository.stage(
        ArtifactDraft(
            kind=ArtifactKind.RUN,
            build_key=ContentDigest("1" * 64),
        )
        # Complete stage only after its 1 and run inputs are visible in output.
    )
    with writer.open_binary("summary.json") as stream:
        stream.write(b"{}")
    manifest = (
        b'{"execution_attempt_id":"'
        + ("2" * 64).encode()
        + b'","logical_run_id":"'
        + ("3" * 64).encode()
        + b'","version":1}'
    )
    return writer.commit(manifest, identity_manifest_bytes=manifest)


def _receipt(
    # Keep the attempt input explicit in the receipt contract.
    attempt: JobAttempt,
    artifact: CommittedArtifact,
) -> AttemptCompletionReceipt:
    # Execute the receipt workflow in explicit, reviewable steps.
    return AttemptCompletionReceipt(
        version=1,
        attempt_id=attempt.attempt_id,
        resolved_spec_id=attempt.spec.spec_id,
        result_artifact_id=artifact.artifact_id,
        # Pass outputs explicitly so AttemptCompletionReceipt receives a reviewable
        # attempt id and spec id input in receipt.
        outputs=(
            CompletionOutput(
                artifact_id=artifact.artifact_id,
                manifest_digest=artifact.manifest_digest,
            ),
            # Complete AttemptCompletionReceipt only after its attempt id and spec id inputs
            # are visible in receipt.
        ),
    )


def test_receipt_publish_is_durable_idempotent_and_immutable(tmp_path: Path) -> None:
    # Execute the test receipt publish is durable idempotent and immutable workflow in
    # explicit, reviewable steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    attempt = _running_attempt(queue)
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _output(repository)
    store = LocalCompletionReceiptStore(DataRootLayout(tmp_path / "var"))
    # Assemble receipt once so the test receipt publish is durable idempotent and
    # immutable workflow shares one value.
    receipt = _receipt(attempt, artifact)

    first_digest = store.publish(receipt)
    second_digest = store.publish(receipt)

    assert first_digest == second_digest
    assert store.load(attempt.attempt_id) == receipt
    # Assemble conflicting once so the test receipt publish is durable idempotent and
    # immutable workflow shares one value.
    conflicting = AttemptCompletionReceipt(
        version=receipt.version,
        attempt_id=receipt.attempt_id,
        resolved_spec_id=ContentDigest("2" * 64),
        result_artifact_id=receipt.result_artifact_id,
        # Pass outputs explicitly so AttemptCompletionReceipt receives a reviewable 2 and
        # version input in test receipt publish is durable idempotent and immutable.
        outputs=receipt.outputs,
    )
    with pytest.raises(CompletionReceiptConflictError):
        store.publish(conflicting)


def test_success_service_requires_receipt_and_verified_exact_output(tmp_path: Path) -> None:
    # Execute the test success service requires receipt and verified exact output workflow
    # in explicit, reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    attempt = _running_attempt(queue)
    repository = LocalArtifactRepository(tmp_path / "var")
    catalog = SQLiteArtifactCatalog(database, repository)
    # Assemble receipts once so the test success service requires receipt and verified
    # exact output workflow shares one value.
    receipts = LocalCompletionReceiptStore(DataRootLayout(tmp_path / "var"))
    complete = CompleteJobAttempt(queue, catalog, receipts, repository)

    with pytest.raises(CompletionReceiptNotFoundError):
        complete.execute(CompleteJobAttemptRequest(attempt))

    artifact = _output(repository)
    # Invoke publish for receipt and attempt as a visible test success service requires
    # receipt and verified exact output step.
    receipts.publish(_receipt(attempt, artifact))
    succeeded = complete.execute(CompleteJobAttemptRequest(attempt))

    assert succeeded.state is AttemptState.SUCCEEDED
    assert catalog.find_committed(artifact.artifact_id) == artifact
    stored = queue.get_job(attempt.job_id)
    # Verify stored is not None before this scenario is accepted.
    assert stored is not None
    assert stored.state is AttemptState.SUCCEEDED


def test_receipt_spec_must_match_current_attempt(tmp_path: Path) -> None:
    # Execute the test receipt spec must match current attempt workflow in explicit,
    # reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    attempt = _running_attempt(queue)
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _output(repository)
    # Assemble catalog once so the test receipt spec must match current attempt workflow
    # shares one value.
    catalog = SQLiteArtifactCatalog(database, repository)
    catalog.index_committed(artifact)
    receipts = LocalCompletionReceiptStore(DataRootLayout(tmp_path / "var"))
    receipts.publish(
        AttemptCompletionReceipt(
            # Pass version explicitly so AttemptCompletionReceipt receives a reviewable 2
            # and attempt id input in test receipt spec must match current attempt.
            version=1,
            attempt_id=attempt.attempt_id,
            resolved_spec_id=ContentDigest("2" * 64),
            result_artifact_id=artifact.artifact_id,
            outputs=(CompletionOutput(artifact.artifact_id, artifact.manifest_digest),),
            # Complete AttemptCompletionReceipt only after its 2 and attempt id inputs are
            # visible in test receipt spec must match current attempt.
        )
    )

    with pytest.raises(CompletionVerificationError, match="resolved spec"):
        CompleteJobAttempt(queue, catalog, receipts).execute(CompleteJobAttemptRequest(attempt))

    stored = queue.get_job(attempt.job_id)
    # Verify stored is not None before this scenario is accepted.
    assert stored is not None
    assert stored.state is AttemptState.RUNNING


def test_completion_rejects_receipt_manifest_mismatch(tmp_path: Path) -> None:
    # Execute the test completion rejects receipt manifest mismatch workflow in explicit,
    # reviewable steps.
    database = tmp_path / "catalog.sqlite"
    queue = SQLiteJobQueue(database)
    attempt = _running_attempt(queue)
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _output(repository)
    # Assemble catalog once so the test completion rejects receipt manifest mismatch
    # workflow shares one value.
    catalog = SQLiteArtifactCatalog(database, repository)
    catalog.index_committed(artifact)
    receipts = LocalCompletionReceiptStore(DataRootLayout(tmp_path / "var"))
    receipts.publish(
        AttemptCompletionReceipt(
            # Pass version explicitly so AttemptCompletionReceipt receives a reviewable f
            # and attempt id input in test completion rejects receipt manifest mismatch.
            version=1,
            attempt_id=attempt.attempt_id,
            resolved_spec_id=attempt.spec.spec_id,
            result_artifact_id=artifact.artifact_id,
            outputs=(CompletionOutput(artifact.artifact_id, ContentDigest("f" * 64)),),
            # Complete AttemptCompletionReceipt only after its f and attempt id inputs are
            # visible in test completion rejects receipt manifest mismatch.
        )
    )

    with pytest.raises(CompletionVerificationError, match="manifest digest"):
        CompleteJobAttempt(queue, catalog, receipts).execute(CompleteJobAttemptRequest(attempt))


def test_corrupt_receipt_is_never_accepted(tmp_path: Path) -> None:
    # Execute the test corrupt receipt is never accepted workflow in explicit, reviewable
    # steps.
    queue = SQLiteJobQueue(tmp_path / "catalog.sqlite")
    attempt = _running_attempt(queue)
    repository = LocalArtifactRepository(tmp_path / "var")
    artifact = _output(repository)
    layout = DataRootLayout(tmp_path / "var")
    # Assemble receipts once so the test corrupt receipt is never accepted workflow shares
    # one value.
    receipts = LocalCompletionReceiptStore(layout)
    receipts.publish(_receipt(attempt, artifact))
    layout.job_receipt(attempt.attempt_id).write_bytes(b'{"truncated":')

    with pytest.raises(CompletionReceiptError, match="valid JSON"):
        receipts.load(attempt.attempt_id)


# Define test receipt rejects duplicate output with digest display prefix as one focused
# operation with an explicit boundary.
def test_receipt_rejects_duplicate_output_with_digest_display_prefix() -> None:
    # Execute the test receipt rejects duplicate output with digest display prefix
    # workflow in explicit, reviewable steps.
    artifact_id = "a" * 64

    with pytest.raises(ValueError, match="duplicate output"):
        # Keep raises, value error and pytest active only for the bounded test receipt
        # rejects duplicate output with digest display prefix operation.
        AttemptCompletionReceipt(
            version=1,
            attempt_id=AttemptId("attempt"),
            resolved_spec_id=ContentDigest("b" * 64),
            result_artifact_id=ArtifactId(artifact_id),
            # Pass outputs explicitly so AttemptCompletionReceipt receives a reviewable
            # attempt and b input in test receipt rejects duplicate output with digest
            # display prefix.
            outputs=(
                CompletionOutput(
                    ArtifactId(artifact_id),
                    ContentDigest("c" * 64),
                ),
                # Pass completion output explicitly to AttemptCompletionReceipt for
                # attempt and b.
                CompletionOutput(
                    ArtifactId(f"sha256:{artifact_id}"),
                    ContentDigest("c" * 64),
                ),
            ),
            # Complete AttemptCompletionReceipt only after its attempt and b inputs are
            # visible in test receipt rejects duplicate output with digest display prefix.
        )
