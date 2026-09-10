"""Bounded display projections over an exact run's retained market history."""

from dataclasses import dataclass
from enum import StrEnum

# Chart coordinates preserve chain identity independently of second-resolution labels.
from backtest.domain.chain import ChainPosition
from backtest.domain.identifiers import AccountId, ArtifactId, AssetId, ContentDigest, SnapshotId

MARKET_CAP_CHART_SCHEMA = "pumpfun-copy-market-cap/v1"
MARKET_CAP_POLICY = "post-transaction-total-supply-market-cap-lamports-floor/v1"
# Small synchronous reads have explicit ceilings; larger analysis needs a separate job.
MAX_MARKET_CHART_EVENTS = 50_000
MAX_MARKET_CHART_POINTS = 4_000
MAX_MARKET_CHART_MARKERS = 6


class MarketChartQueryError(RuntimeError):
    """Closed safe query errors contain no paths, source data, or raw exceptions."""

    def __init__(self, code: str) -> None:
        # Query failures never become a fabricated zero-valued chart.
        if code not in {
            "MARKET_CHART_UNAVAILABLE",
            "MARKET_CHART_LIMIT_EXCEEDED",
            "MARKET_CHART_BUSY",
            "COPY_POSITION_NOT_FOUND",
            # A closed vocabulary is safe to project into API error responses.
        }:
            raise ValueError("unsupported market chart error")
        self.code = code
        super().__init__(code)


# Lifecycle is a display boundary, independent of execution attempt status.
class MarketLifecycle(StrEnum):
    """An inactive curve terminates executable historical price continuity."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    MIGRATED = "MIGRATED"


@dataclass(frozen=True, slots=True)
class MarketCapState:
    """Protocol-produced full-supply capitalization, rounded down to one quote atom."""

    market_cap_atomic: int
    lifecycle: MarketLifecycle
    signing_wallet: AccountId | None = None

    def __post_init__(self) -> None:
        # Display math is still checked integer math, with no implicit unit conversion.
        if type(self.market_cap_atomic) is not int or not 0 <= self.market_cap_atomic < 1 << 128:
            raise ValueError("market capitalization must be UInt128")
        # A valid number alone cannot imply that the curve is still active.
        if not isinstance(self.lifecycle, MarketLifecycle):
            raise TypeError("market lifecycle must be explicit")


@dataclass(frozen=True, slots=True)
class MarketCapPoint:
    """One complete historical transaction, or the final proven clock boundary."""

    position: ChainPosition
    block_time_ns: int
    market_cap_atomic: int
    lifecycle: MarketLifecycle

    def __post_init__(self) -> None:
        # Block labels never invent subsecond source timing or instruction boundaries.
        if self.position.transaction_index < 0 or self.position.event_index is not None:
            raise ValueError("chart point requires a transaction boundary")
        # The source clock, not extraction time, supplies every timestamp.
        if type(self.block_time_ns) is not int or not 0 <= self.block_time_ns < 1 << 63:
            raise ValueError("chart block time must fit nonnegative Int64")
        MarketCapState(self.market_cap_atomic, self.lifecycle)


@dataclass(frozen=True, slots=True)
class CopyChartMarker:
    """Signal and actual attempt outcomes retain their distinct effective coordinates."""

    kind: str
    status: str
    attempt: int | None
    point: MarketCapPoint
    # A failed attempt remains a failure even when an active historical price exists.
    failure_code: str | None = None

    def __post_init__(self) -> None:
        # The bounded marker vocabulary cannot label a reference quote as a fill.
        if self.kind not in {"SIGNAL", "BUY", "SELL"}:
            raise ValueError("unsupported chart marker kind")
        # A leader signal is observed history and has no own-order attempt number.
        if self.kind == "SIGNAL":
            if self.status != "OBSERVED_SOURCE" or self.attempt is not None or self.failure_code:
                raise ValueError("invalid source signal marker")
            return
        # Entry is attempt zero; exits keep their original one-through-four ordinals.
        if type(self.attempt) is not int or not 0 <= self.attempt <= 4:
            raise ValueError("invalid chart attempt number")
        if (self.attempt == 0) != (self.kind == "BUY"):
            raise ValueError("chart attempt side mismatch")
        # Submitted or pending orders cannot appear in a completed chart.
        if self.status not in {"FILLED", "FAILED", "REJECTED"}:
            raise ValueError("invalid chart attempt status")
        # Inactive-state prices may be shown as terminal history, never as actual fills.
        if self.status == "FILLED":
            if self.failure_code is not None or self.point.lifecycle is not MarketLifecycle.ACTIVE:
                raise ValueError("filled marker has a failure or inactive curve")
        # Every unsuccessful attempt retains an inspectable reason.
        elif not self.failure_code:
            raise ValueError("failed marker requires a failure code")


@dataclass(frozen=True, slots=True)
class CopyMarketChart:
    """A response is bound to one run, one recorded position and its exact snapshot."""

    run_artifact_id: ArtifactId
    position_id: ContentDigest
    snapshot_id: SnapshotId
    asset_id: AssetId
    # Market cap is full supply times marginal curve price, denominated in SOL atoms.
    quote_asset_id: AssetId
    points: tuple[MarketCapPoint, ...]
    markers: tuple[CopyChartMarker, ...]

    def __post_init__(self) -> None:
        # Transport never carries an unbounded series or omits the requested signal.
        if not 1 <= len(self.points) <= MAX_MARKET_CHART_POINTS:
            raise ValueError("invalid market chart point count")
        if not 2 <= len(self.markers) <= MAX_MARKET_CHART_MARKERS:
            raise ValueError("invalid market chart marker count")
        # The signal is mandatory even when the own buy was rejected.
        if self.quote_asset_id != AssetId("SOL") or self.markers[0].kind != "SIGNAL":
            raise ValueError("invalid copy market chart identity")
        # Equal source seconds are valid; chain boundaries remain strictly ordered.
        keys = tuple(point.position.boundary_ordinal for point in self.points)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("market chart is not strictly chain ordered")
        # Time labels can repeat, but cannot regress along the chain.
        times = tuple(point.block_time_ns for point in self.points)
        if times != tuple(sorted(times)):
            raise ValueError("market chart time regressed")
        # All marks use the same network and lie within the proven chart interval.
        for point in (*self.points, *(marker.point for marker in self.markers)):
            self.points[0].position.require_same_chain(point.position)
            if not keys[0] <= point.position.boundary_ordinal <= keys[-1]:
                raise ValueError("market marker falls outside chart coverage")
