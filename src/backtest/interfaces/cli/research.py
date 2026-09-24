"""Research CLI transport; all IO and execution stays behind the injected backend."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import wraps
from pathlib import Path

# Only transport annotations are needed at runtime; the composition factory is injected.
from typing import TYPE_CHECKING, Annotated

import typer

from backtest.application.models import JobType

# This module imports no adapters, bootstrap, runtime, SQL or filesystem readers.
from backtest.application.research import ResearchMode, ResearchTable
from backtest.application.research_pages import cursor_after, page_cursor
from backtest.domain.identifiers import ArtifactId

if TYPE_CHECKING:
    from backtest.interfaces.cli.main import CliBackendFactory


# Error mapping wraps transport commands, not analytical operations or subprocess execution.
def _safe[**P](function: Callable[P, None]) -> Callable[P, None]:
    """Reuse the established finite CLI error mapper without exposing source tracebacks."""

    @wraps(function)
    def invoke(*args: P.args, **kwargs: P.kwargs) -> None:
        """Preserve the real Typer signature while translating known safe terminal errors."""
        from backtest.interfaces.cli.main import _KNOWN_ERRORS, _fail

        try:
            function(*args, **kwargs)
        except _KNOWN_ERRORS as error:
            _fail(error)

    # Returning the wrapper keeps command discovery independent of any configured backend.
    return invoke


def register_research_commands(cli: typer.Typer, factory: CliBackendFactory) -> None:
    """Register one cohesive group without another spec-building implementation."""

    group = typer.Typer(no_args_is_help=True, help="Observed wallet activity and co-buy research.")
    cli.add_typer(group, name="research")

    # Acquisition exposes only block bounds and deployment-local configuration selection.
    @group.command("prepare")
    @_safe
    def prepare(
        from_block: int,
        to_block: int,
        # Config paths are CLI-local inputs and never enter research semantic identity.
        config: Annotated[Path, typer.Option()] = Path("configs/local-16gb.toml"),
        capabilities: Annotated[Path | None, typer.Option()] = None,
    ) -> None:
        """Prepare a fresh bounded observational snapshot using the configured source."""

        backend = factory(config, capabilities, require_capabilities=True)
        command = backend.research_use_cases().resolve_prepare(from_block, to_block)
        artifact = backend.execute_research(JobType.PREPARE_RESEARCH, command.canonical_bytes())
        typer.echo(json.dumps({"artifact_id": artifact.artifact_id.hex, "kind": artifact.kind}))

    # Analysis requires committed local data and runs under existing controller authority.
    @group.command("analyze")
    @_safe
    def analyze(
        snapshot_id: str,
        config: Annotated[Path, typer.Option()] = Path("configs/local-16gb.toml"),
        # The inclusive reported-time window changes the immutable analysis recipe.
        window_seconds: Annotated[int, typer.Option(min=0, max=3600)] = 60,
        # These filters affect the recipe; physical execution tuning is not accepted here.
        minimum_shared_mints: Annotated[int, typer.Option(min=1)] = 2,
        wallet: Annotated[list[str] | None, typer.Option()] = None,
        # Token filtering is part of the immutable recipe, shared with the web form.
        mode: Annotated[ResearchMode, typer.Option()] = ResearchMode.NON_MAYHEM,
    ) -> None:
        """Analyze an exact local snapshot; repeat --wallet to restrict the signer set."""

        backend = factory(config, None)
        command = backend.research_use_cases().resolve_analysis(
            ArtifactId(snapshot_id),
            window_seconds=window_seconds,
            minimum_shared_mints=minimum_shared_mints,
            # Canonical address ordering and full-key validation belong to the use case.
            wallets=tuple(wallet or ()),
            mode=mode,
        )
        # Existing direct execution owns retries, cancellation, admission and receipts.
        artifact = backend.execute_research(JobType.ANALYZE_WALLETS, command.canonical_bytes())
        typer.echo(json.dumps({"artifact_id": artifact.artifact_id.hex, "kind": artifact.kind}))

    # Metadata inspection is bounded and does not open a remote source connection.
    @group.command("show")
    @_safe
    def show(
        artifact_id: str, config: Annotated[Path, typer.Option()] = Path("configs/local-16gb.toml")
    ) -> None:
        """Print bounded verified metadata and honest source-quality limitations."""

        service = factory(config, None).research_use_cases()
        typer.echo(json.dumps(service.summary(ArtifactId(artifact_id)), indent=2))

    # CLI pagination uses the same exact view scope and cursor format as the API.
    @group.command("rows")
    @_safe
    def rows(
        artifact_id: str,
        table: ResearchTable,
        # Deployment configuration selects local authority; it is not a table location.
        config: Annotated[Path, typer.Option()] = Path("configs/local-16gb.toml"),
        cursor: Annotated[str | None, typer.Option()] = None,
        # Explicit page and pair bounds prevent unbounded terminal data exports.
        limit: Annotated[int, typer.Option(min=1, max=200)] = 25,
        pair: Annotated[int | None, typer.Option(min=0)] = None,
    ) -> None:
        """Read a bounded table page; evidence requires --pair from the pair's row_id."""

        artifact = ArtifactId(artifact_id)
        service = factory(config, None).research_use_cases()
        after = cursor_after(cursor, artifact, table, pair)
        values = service.page(artifact, table, after=after, limit=limit, pair=pair)
        next_cursor = None
        # Cursor scope is identical to API pagination and never accepts a physical path.
        if values and len(values) == limit:
            next_cursor = page_cursor(artifact, table, pair, int(values[-1]["row_id"]))
        typer.echo(json.dumps({"rows": values, "next_cursor": next_cursor}, indent=2))
