"""Controller-owned restart reconciliation for rebuildable artifact indexes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.artifacts.localfs.scanner import LocalCommittedArtifactScanner
from backtest.adapters.catalog.sqlite.artifact_catalog import SQLiteArtifactCatalog
from backtest.application.catalog_models import ArtifactInventory
from backtest.application.models import ArtifactKind
from backtest.domain.identifiers import ArtifactId
from backtest.runtime.file_locks import FileLock, LockMode

_RECENT_RUN_PAGE_WITH_LOOKAHEAD = 51
_MAX_VERIFICATION_SEED_ARTIFACTS = 128


class CatalogReconciliationError(RuntimeError):
    """Filesystem and rebuildable catalog could not reach one safe clean cut."""


class LocalArtifactCatalogReconciler:
    """Reuse only clean unchanged metadata; otherwise re-hash every committed byte."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        catalog: SQLiteArtifactCatalog,
    ) -> None:
        self._artifacts = artifacts
        self._catalog = catalog

    @contextmanager
    def controller_session(self) -> Iterator[None]:
        """Bracket one controller lifetime with durable unclean/clean evidence."""

        # The controller lock is held by the caller before this writer admission lock.
        with self._writer_lock():
            scanner = LocalCommittedArtifactScanner(self._artifacts)
            inventory = scanner.inventory()
            reusable = self._catalog.begin_reconciliation_session(inventory)
            # Only an exact CLEAN receipt permits omitting full payload verification.
            if not reusable:
                self._full_rebuild_locked()
            else:
                # Receipt reuse may warm only evidence from this exact inventory scan.
                self._seed_recent_run_closure(scanner, inventory)

        # Only a normally completed controller lifetime may publish CLEAN evidence.
        completed = False
        try:
            yield
            completed = True
        finally:
            # An exceptional exit intentionally leaves durable UNCLEAN evidence.
            if completed:
                self._finish_clean()

    def reconcile_once(self) -> None:
        """Prepare direct read-only CLI use while controller probe authority is held."""

        with self.controller_session():
            pass

    def _finish_clean(self) -> None:
        """Rebuild if anything escaped incremental indexing before clean shutdown."""

        with self._writer_lock():
            scanner = LocalCommittedArtifactScanner(self._artifacts)
            inventory = scanner.inventory()
            if not self._catalog.finish_reconciliation_session(inventory):
                self._full_rebuild_locked()
                inventory = scanner.inventory()
                if not self._catalog.finish_reconciliation_session(inventory):
                    raise CatalogReconciliationError(
                        "catalog remained inconsistent after full reconciliation"
                    )

    def _full_rebuild_locked(self) -> None:
        """Rebuild only from descriptors accepted by full repository verification."""

        scanner = LocalCommittedArtifactScanner(self._artifacts)
        discovered = scanner.scan()
        self._catalog.rebuild_index(discovered)

    def _seed_recent_run_closure(
        self,
        scanner: LocalCommittedArtifactScanner,
        inventory: ArtifactInventory,
    ) -> None:
        """Warm the bounded first-page Run set and its direct verified lineage."""

        # Exact reusable empty inventory implies the catalog projection is empty too.
        if not inventory.entries:
            return
        # One lookahead row matches the largest public first page without eager history.
        recent = self._catalog.list_runs(
            limit=_RECENT_RUN_PAGE_WITH_LOOKAHEAD,
            offset=0,
        )
        # Selection uses authenticated inventory descriptors, never a catalog path.
        inventory_by_id = {
            entry.descriptor.artifact_id.hex: entry.descriptor for entry in inventory.entries
        }
        access_order: dict[str, ArtifactId] = {}
        # The cap includes direct inputs so a large lineage cannot enlarge the seed set.
        for run_entry in recent:
            # QueryRuns opens the Run first, followed by its direct descriptor inputs.
            descriptor = inventory_by_id.get(run_entry.artifact_id.hex)
            if descriptor is None or descriptor.kind is not ArtifactKind.RUN:
                raise CatalogReconciliationError("recent Run is absent from exact inventory")
            for artifact_id in (descriptor.artifact_id, *descriptor.input_artifact_ids):
                # Preserve first-use order while sharing inputs across recent Runs.
                if artifact_id.hex not in access_order:
                    access_order[artifact_id.hex] = artifact_id
                if len(access_order) >= _MAX_VERIFICATION_SEED_ARTIFACTS:
                    break
            # Stop before inspecting another Run once the existing LRU capacity is filled.
            if len(access_order) >= _MAX_VERIFICATION_SEED_ARTIFACTS:
                break

        # Reverse insertion keeps the artifacts read first resident under LRU pressure.
        scanner._seed_verification_cache(
            inventory,
            tuple(reversed(tuple(access_order.values()))),
        )

    def _writer_lock(self) -> FileLock:
        """Serialize startup scans with all normal publishers in normative order."""

        return FileLock(
            self._artifacts.locks_root / "writer.lock",
            mode=LockMode.EXCLUSIVE,
        )


__all__ = ["CatalogReconciliationError", "LocalArtifactCatalogReconciler"]
