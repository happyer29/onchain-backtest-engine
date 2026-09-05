"""Execute independent resolved runs and normalize arbitrary completion order."""

from __future__ import annotations

from backtest.application.attempt_identity import queued_sweep_entry_attempt_nonce
from backtest.application.ports.sweeps import IndependentRunExecutor, SweepOutputStore
from backtest.application.sweeps import ResolvedSweepSpec, SweepEntryResult, SweepResult
from backtest.application.use_cases.run_backtest import RunBacktestRequest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import ContentDigest


class SweepExecutionError(RuntimeError):
    """The executor omitted, duplicated or substituted a resolved attempt."""


class RunSweep:
    def __init__(
        self,
        executor: IndependentRunExecutor,
        outputs: SweepOutputStore,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the run sweep init workflow in explicit, reviewable steps.
        self._executor = executor
        self._outputs = outputs

    def execute(
        self,
        spec: ResolvedSweepSpec,
        # Close the execute signature after its explicit inputs.
        *,
        attempt_namespace: ContentDigest | None = None,
    ) -> SweepResult:
        # Execute the run sweep execute workflow in explicit, reviewable steps.
        requests = tuple(
            RunBacktestRequest(
                entry.resolved_spec,
                queued_sweep_entry_attempt_nonce(
                    entry.attempt_nonce,
                    # Pass entry explicitly so queued_sweep_entry_attempt_nonce receives a
                    # reviewable attempt nonce and entry id input in run sweep execute.
                    entry.entry_id,
                    attempt_namespace,
                ),
                entry.physical_settings,
            )
            # Pass entry explicitly so tuple receives a reviewable resolved spec and
            # physical settings input in run sweep execute.
            for entry in spec.entries
        )
        expected = {
            request.resolved_spec.execution_attempt_id(
                request.attempt_nonce,
                # Pass request explicitly so execution_attempt_id receives a reviewable
                # attempt nonce and identity digest input in run sweep execute.
                request.physical_settings.identity_digest,
            ): entry
            for request, entry in zip(requests, spec.entries, strict=True)
        }
        raw_results = self._executor.execute_all(requests)
        # Guard this path with len(raw_results) != len(expected) before applying effects.
        if len(raw_results) != len(expected):
            raise SweepExecutionError("sweep executor returned the wrong result count")
        seen = set()
        normalized: list[SweepEntryResult] = []
        for result in raw_results:
            # Process raw_results inside the bounded run sweep execute loop.
            if result.execution_attempt_id in seen:
                raise SweepExecutionError("sweep executor returned a duplicate attempt")
            seen.add(result.execution_attempt_id)
            try:
                entry = expected[result.execution_attempt_id]
            # Translate key error through the run sweep execute boundary without hiding
            # other errors.
            except KeyError as error:
                # Translate the KeyError failure through the run sweep execute boundary.
                raise SweepExecutionError(
                    "sweep executor substituted an unknown attempt"
                ) from error
            if result.logical_run_id != entry.resolved_spec.logical_run_id:
                raise SweepExecutionError("sweep result logical identity differs from its entry")
            # Invoke append for entry id and logical run id as a visible run sweep execute
            # step.
            normalized.append(
                SweepEntryResult(
                    entry_id=entry.entry_id,
                    logical_run_id=result.logical_run_id,
                    execution_attempt_id=result.execution_attempt_id,
                    # Pass canonical result hash explicitly so SweepEntryResult receives a
                    # reviewable entry id and logical run id input in run sweep execute.
                    canonical_result_hash=result.canonical_result_hash,
                    run_artifact=result.artifact,
                    comparison=result.comparison,
                    physical_settings=result.physical_settings,
                    canonicality=result.canonicality,
                    # Pass warnings explicitly so SweepEntryResult receives a reviewable
                    # entry id and logical run id input in run sweep execute.
                    warnings=result.warnings,
                )
            )
        if seen != set(expected):
            raise SweepExecutionError("sweep executor omitted an expected attempt")
        # Assemble entries once so the run sweep execute workflow shares one value.
        entries = tuple(sorted(normalized, key=lambda item: item.entry_id.hex))
        artifact = self._outputs.publish(spec, entries)
        return SweepResult(spec.sweep_spec_id, spec.comparison_metrics, entries, artifact)


__all__ = ["RunSweep", "SweepExecutionError"]
