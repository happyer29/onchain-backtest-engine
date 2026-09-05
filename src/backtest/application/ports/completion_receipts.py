"""Port for authoritative local attempt-completion receipts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backtest.application.completion import AttemptCompletionReceipt
from backtest.application.models import CommittedArtifact
from backtest.domain.identifiers import AttemptId, ContentDigest


# Keep the completion receipt store contract and validation rules together.
@runtime_checkable
class CompletionReceiptStore(Protocol):
    def publish(self, receipt: AttemptCompletionReceipt) -> ContentDigest: ...

    def load(self, attempt_id: AttemptId) -> AttemptCompletionReceipt | None: ...


@runtime_checkable
# Keep the committed output observer contract and validation rules together.
class CommittedOutputObserver(Protocol):
    """Supervisor-side projection of already verified immutable outputs."""

    def observe(self, outputs: tuple[CommittedArtifact, ...]) -> None: ...


__all__ = ["CommittedOutputObserver", "CompletionReceiptStore"]
