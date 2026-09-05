"""Local host configuration kept outside logical experiment identities."""

from __future__ import annotations

import os
import re
import tomllib
import warnings

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from backtest.application.run_results import RunBackend, RunPhysicalSettings

DEFAULT_CONFIG_ENV: Final = "BACKTEST_CONFIG"


# Keep the config error contract and validation rules together.
class ConfigError(ValueError):
    """Raised for invalid local host configuration."""


class InsecureRemoteSourceWarning(RuntimeWarning):
    """Warn that a deployment explicitly accepted plaintext source transport."""


INSECURE_REMOTE_SOURCE_WARNING: Final = (
    "Plaintext remote source transport is explicitly enabled; credentials, "
    "queries, and response bytes are not protected in transit."
)


@dataclass(frozen=True, slots=True)
# Keep the path settings contract and validation rules together.
class PathSettings:
    data_root: Path = Path("var")


# Keep the resource settings contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResourceSettings:
    max_aggregate_child_memory_mb: int = 8_192
    max_builder_memory_mb: int = 6_144
    builder_peak_private_memory_mb: int = 7_168
    # Declare run peak private memory mb explicitly in the resource settings contract.
    run_peak_private_memory_mb: int = 3_072
    max_parallel_runs: int = 1
    tmp_quota_gb: int = 32
    max_run_tmp_gb: int = 1
    max_run_output_gb: int = 4
    # Declare disk low watermark gb explicitly in the resource settings contract.
    disk_low_watermark_gb: int = 32
    disk_emergency_watermark_gb: int = 16
    native_threads_per_process: int = 1
    memory_safety_reserve_mb: int = 1_024
    page_cache_floor_mb: int = 2_048
    # Declare host staging output reserve mb explicitly in the resource settings contract.
    host_staging_output_reserve_mb: int = 512
    fixed_shared_overhead_mb: int = 256
    memory_breach_samples: int = 2
    swap_activity_samples: int = 3

    def __post_init__(self) -> None:
        # Execute the resource settings post init workflow in explicit, reviewable steps.
        values = (
            self.max_aggregate_child_memory_mb,
            self.max_builder_memory_mb,
            self.builder_peak_private_memory_mb,
            self.run_peak_private_memory_mb,
            # Keep the self component named inside the values contract.
            self.max_parallel_runs,
            self.tmp_quota_gb,
            self.max_run_tmp_gb,
            self.max_run_output_gb,
            self.disk_low_watermark_gb,
            # Keep the self component named inside the values contract.
            self.disk_emergency_watermark_gb,
            self.native_threads_per_process,
            self.memory_safety_reserve_mb,
            self.page_cache_floor_mb,
            self.host_staging_output_reserve_mb,
            # Keep the self component named inside the values contract.
            self.fixed_shared_overhead_mb,
            self.memory_breach_samples,
            self.swap_activity_samples,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            # Fail the resource settings post init path with ConfigError for resource
            # limits must be integers when value, values and isinstance is true; do not
            # continue ambiguously.
            raise ConfigError("resource limits must be integers")
        if min(values) <= 0:
            raise ConfigError("resource limits must be positive")
        if max(self.builder_peak_private_memory_mb, self.run_peak_private_memory_mb) > (
            self.max_aggregate_child_memory_mb
            # Evaluate the complete resource settings post init max aggregate child memory mb,
            # builder peak private memory mb and run peak private memory mb condition before
            # guarded effects.
        ):
            raise ConfigError("one child memory demand cannot exceed the aggregate ceiling")
        if (
            self.run_peak_private_memory_mb * self.max_parallel_runs
            > self.max_aggregate_child_memory_mb
            # Evaluate the complete resource settings post init max aggregate child memory mb,
            # run peak private memory mb and max parallel runs condition before guarded
            # effects.
        ):
            # Handle the resource settings post init max aggregate child memory mb, run
            # peak private memory mb and max parallel runs condition as a distinct block.
            raise ConfigError(
                "parallel sweep private-memory demand cannot exceed the aggregate ceiling"
            )
        if self.max_builder_memory_mb >= self.builder_peak_private_memory_mb:
            # Handle the resource settings post init max builder memory mb and builder
            # peak private memory mb condition as a distinct block.
            raise ConfigError(
                "builder peak private memory must include overhead above its internal limit"
            )
        if self.disk_emergency_watermark_gb > self.disk_low_watermark_gb:
            raise ConfigError("disk emergency watermark cannot exceed the low watermark")
        # Evaluate the complete resource settings post init max run tmp gb and tmp quota
        # gb condition before guarded effects.
        if self.max_run_tmp_gb > self.tmp_quota_gb:
            raise ConfigError("run temporary quota cannot exceed the host temporary quota")
        if self.max_run_tmp_gb * self.max_parallel_runs > self.tmp_quota_gb:
            # Handle the resource settings post init tmp quota gb, max run tmp gb and max
            # parallel runs condition as a distinct block.
            raise ConfigError(
                "parallel sweep temporary demand cannot exceed the host temporary quota"
            )


@dataclass(frozen=True, slots=True)
class RetentionSettings:
    """Host-owned GC limits; a command or API request cannot weaken them."""

    minimum_artifact_age_seconds: int = 86_400
    trash_grace_seconds: int = 86_400
    maximum_sweep_gb: int = 32

    def __post_init__(self) -> None:
        # Execute the retention settings post init workflow in explicit, reviewable steps.
        values = (
            self.minimum_artifact_age_seconds,
            self.trash_grace_seconds,
            self.maximum_sweep_gb,
        )
        # Evaluate the complete retention settings post init value, values and isinstance
        # condition before guarded effects.
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ConfigError("retention limits must be integers")
        if self.minimum_artifact_age_seconds < 0 or self.trash_grace_seconds < 0:
            raise ConfigError("retention grace periods must be non-negative")
        if self.maximum_sweep_gb <= 0:
            # Fail the retention settings post init path with ConfigError for maximum
            # sweep gb must be positive when maximum sweep gb is true; do not continue
            # ambiguously.
            raise ConfigError("maximum_sweep_gb must be positive")


@dataclass(frozen=True, slots=True)
class BackupSettings:
    """Configured external durability and isolated restore-drill locations."""

    target_root: Path | None = None
    restore_verify_parent: Path | None = None
    allow_same_device_for_drill: bool = False
    target_encryption_verified: bool = False

    def __post_init__(self) -> None:
        # Execute the backup settings post init workflow in explicit, reviewable steps.
        if (self.target_root is None) != (self.restore_verify_parent is None):
            # Handle the backup settings post init target root and restore verify parent
            # condition as a distinct block.
            raise ConfigError(
                "backup target_root and restore_verify_parent must be configured together"
            )
        if self.target_root is not None and self.restore_verify_parent is not None:
            # Handle the backup settings post init target root and restore verify parent
            # condition as a distinct block.
            target = self.target_root.absolute()
            restore_parent = self.restore_verify_parent.absolute()
            if (
                target == restore_parent
                or target.is_relative_to(restore_parent)
                # Keep restore parent visible while evaluating the target, restore parent
                # and is relative to guard.
                or restore_parent.is_relative_to(target)
            ):
                raise ConfigError("backup and restore verification locations must not overlap")
            if not self.target_encryption_verified and not self.allow_same_device_for_drill:
                raise ConfigError("external backup target encryption must be verified explicitly")


# Apply dataclass semantics to the following planning settings contract.
@dataclass(frozen=True, slots=True)
class PlanningSettings:
    """Host-owned ceilings that remote/API requests cannot raise."""

    max_remote_gb: int = 16
    max_local_gb: int = 16
    max_days: int = 7
    staging_reserve_gb: int = 4
    max_total_blocks: int = 2_000_000
    # Declare max total shards explicitly in the planning settings contract.
    max_total_shards: int = 4_096
    max_shard_blocks: int = 250_000
    max_query_execution_seconds: int = 300
    max_query_memory_mb: int = 4_096
    max_query_result_rows: int = 10_000_000

    # Define planning settings post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the planning settings post init workflow in explicit, reviewable steps.
        values = (
            self.max_remote_gb,
            self.max_local_gb,
            self.max_days,
            self.staging_reserve_gb,
            # Keep the self component named inside the values contract.
            self.max_total_blocks,
            self.max_total_shards,
            self.max_shard_blocks,
            self.max_query_execution_seconds,
            self.max_query_memory_mb,
            # Keep the self component named inside the values contract.
            self.max_query_result_rows,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ConfigError("planning limits must be integers")
        if min(values) <= 0:
            # Fail the planning settings post init path with ConfigError for planning
            # limits must be positive when values is true; do not continue ambiguously.
            raise ConfigError("planning limits must be positive")


# Keep the control settings contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ControlSettings:
    host: str = "127.0.0.1"
    port: int = 8_080
    progress_interval_ms: int = 500
    # Declare max request mb explicitly in the control settings contract.
    max_request_mb: int = 2
    secure_cookie: bool = False

    def __post_init__(self) -> None:
        # Execute the control settings post init workflow in explicit, reviewable steps.
        if self.host not in {"127.0.0.1", "::1", "localhost"}:
            raise ConfigError("Control API must bind to loopback in the local profile")
        if not 1 <= self.port <= 65_535:
            raise ConfigError("control port must be between 1 and 65535")
        if self.progress_interval_ms <= 0 or self.max_request_mb <= 0:
            # Fail the control settings post init path with ConfigError for control limits
            # must be positive when progress interval ms and max request mb is true; do
            # not continue ambiguously.
            raise ConfigError("control limits must be positive")


@dataclass(frozen=True, slots=True)
class ReplaySettings:
    """Host defaults for one physical run attempt; never logical semantics."""

    backend: RunBackend = RunBackend.REFERENCE_PYTHON
    reader_batch_rows: int = 65_536
    reader_readahead: int = 1
    output_buffer_rows: int = 8_192
    threads: int = 1

    # Define replay settings post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the replay settings post init workflow in explicit, reviewable steps.
        try:
            self.to_run_physical_settings()
        except (TypeError, ValueError) as error:
            raise ConfigError("[replay] contains unsupported physical settings") from error

    def to_run_physical_settings(self) -> RunPhysicalSettings:
        # Execute the replay settings to run physical settings workflow in explicit,
        # reviewable steps.
        return RunPhysicalSettings(
            backend=self.backend,
            reader_batch_rows=self.reader_batch_rows,
            reader_readahead=self.reader_readahead,
            output_buffer_rows=self.output_buffer_rows,
            # Pass threads explicitly so RunPhysicalSettings receives a reviewable backend
            # and reader batch rows input in replay settings to run physical settings.
            threads=self.threads,
        )


@dataclass(frozen=True, slots=True)
class SourceSettings:
    """Deployment-local connection settings for the read-only source."""

    # These labels select one physical source and are never run semantics.
    source_id: str = "default-indexer"
    host: str = "127.0.0.1"
    port: int = 8_123
    database: str = "default"
    username: str = "default"

    # Even the environment-variable name is omitted from repr/log output.  It
    # is not a credential, but redacting it keeps configuration dumps from
    # revealing secret-management conventions.
    secret_ref: str = field(default="BACKTEST_INDEXER_PASSWORD", repr=False)
    capabilities_file: Path | None = None
    projections_file: Path | None = None

    # Transport assertions are mutually constrained below; safe defaults do
    # not infer protection from a private-looking address.
    secure: bool = False
    verified_private_tunnel: bool = False
    allow_insecure_remote_http: bool = False

    def __post_init__(self) -> None:
        # Source labels are operational metadata, but malformed tokens must
        # still fail before any adapter can construct a connection.
        for value, label in (
            (self.source_id, "source_id"),
            (self.host, "source host"),
            # Database and user labels share the same token restrictions.
            (self.database, "source database"),
            (self.username, "source username"),
        ):
            # Process source id, host and database inside the bounded source settings post
            # init loop.
            if not value or value != value.strip() or "\x00" in value:
                raise ConfigError(f"{label} must be non-empty, trimmed and NUL-free")

        # A host field cannot smuggle a URL, path, or whitespace into the
        # adapter-owned connection builder.
        host_is_url_or_path = "://" in self.host or "/" in self.host
        host_has_whitespace = any(character.isspace() for character in self.host)
        if host_is_url_or_path or host_has_whitespace:
            raise ConfigError("source host must be a hostname or IP address, not a URL")
        if not 1 <= self.port <= 65_535:
            # Fail the source settings post init path with ConfigError for source port
            # must be between 1 and 65535 when port is true; do not continue ambiguously.
            raise ConfigError("source port must be between 1 and 65535")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.secret_ref) is None:
            raise ConfigError("source secret_ref must be a valid environment variable name")

        # The plaintext escape hatch is intentionally narrow: it cannot be
        # confused with TLS, a private tunnel, or an ordinary loopback setup.
        loopback = _is_loopback_host(self.host)
        if self.allow_insecure_remote_http and self.secure:
            raise ConfigError("allow_insecure_remote_http cannot be combined with secure=true")

        # A verified tunnel and accepted public plaintext risk are distinct,
        # mutually exclusive deployment claims.
        if self.allow_insecure_remote_http and self.verified_private_tunnel:
            # Handle the source settings post init allow insecure remote http and verified
            # private tunnel condition as a distinct block.
            raise ConfigError(
                "allow_insecure_remote_http cannot be combined with verified_private_tunnel=true"
            )

        # Loopback HTTP needs no public-transport exception and must not create
        # a misleading warning or configuration precedent.
        if self.allow_insecure_remote_http and loopback:
            raise ConfigError("allow_insecure_remote_http is only valid for a non-loopback source")

        # Remote plaintext remains fail-closed unless the deployment makes
        # exactly one explicit transport-risk assertion.
        remote_plaintext = not self.secure and not self.verified_private_tunnel and not loopback

        # The exception is never inferred from the endpoint or credential.
        if remote_plaintext and not self.allow_insecure_remote_http:
            # Handle the source settings post init remote plaintext and allow insecure
            # remote http condition as a distinct block.
            raise ConfigError(
                "remote source credentials require verified TLS or a verified private tunnel"
            )

        # This constant message deliberately excludes endpoint, identity, and
        # secret-reference values so warnings are safe to retain in logs.
        if self.allow_insecure_remote_http:
            # Emit at construction so direct use and TOML loading share one
            # observable enforcement point.
            warnings.warn(
                INSECURE_REMOTE_SOURCE_WARNING,
                InsecureRemoteSourceWarning,
                stacklevel=2,
            )

    # Define source settings password as one focused operation with an explicit boundary.
    def password(self, environ: dict[str, str] | None = None) -> str:
        # Execute the source settings password workflow in explicit, reviewable steps.
        source = os.environ if environ is None else environ
        try:
            return source[self.secret_ref]
        except KeyError as error:
            raise ConfigError("configured source secret is unavailable") from error


# Define is loopback host as one focused operation with an explicit boundary.
def _is_loopback_host(value: str) -> bool:
    # Execute the is loopback host workflow in explicit, reviewable steps.
    normalized = value.casefold().removesuffix(".")
    return normalized in {"127.0.0.1", "::1", "localhost"}


# Keep the settings contract and validation rules together.
@dataclass(frozen=True, slots=True)
class Settings:
    paths: PathSettings = field(default_factory=PathSettings)
    resources: ResourceSettings = field(default_factory=ResourceSettings)
    planning: PlanningSettings = field(default_factory=PlanningSettings)
    # Declare retention explicitly in the settings contract.
    retention: RetentionSettings = field(default_factory=RetentionSettings)
    backup: BackupSettings = field(default_factory=BackupSettings)
    replay: ReplaySettings = field(default_factory=ReplaySettings)
    control: ControlSettings = field(default_factory=ControlSettings)
    source: SourceSettings = field(default_factory=SourceSettings)

    # Define settings post init as one focused operation with an explicit boundary.
    def __post_init__(self) -> None:
        # Execute the settings post init workflow in explicit, reviewable steps.
        if self.replay.threads != self.resources.native_threads_per_process:
            raise ConfigError("replay threads must equal the configured native_threads_per_process")


def _section(data: object, name: str) -> dict[str, object]:
    # Execute the section workflow in explicit, reviewable steps.
    if data is None:
        return {}
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise ConfigError(f"[{name}] must be a TOML table")
    return data


# Define string as one focused operation with an explicit boundary.
def _string(section: dict[str, object], key: str, default: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    return value


def _integer(section: dict[str, object], key: str, default: int) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    value = section.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{key} must be an integer")
    return value


def _boolean(section: dict[str, object], key: str, default: bool) -> bool:
    # Execute the boolean workflow in explicit, reviewable steps.
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value


def _run_backend(section: dict[str, object]) -> RunBackend:
    # Execute the run backend workflow in explicit, reviewable steps.
    raw = _string(section, "backend", RunBackend.REFERENCE_PYTHON.value)
    try:
        return RunBackend(raw)
    except ValueError as error:
        raise ConfigError("replay backend is not installed") from error


# Define validate replay section as one focused operation with an explicit boundary.
def _validate_replay_section(section: dict[str, object]) -> None:
    # Execute the validate replay section workflow in explicit, reviewable steps.
    supported = {"backend", "batch_rows", "readahead", "output_buffer_rows", "threads"}
    if unknown := set(section).difference(supported):
        raise ConfigError(f"[replay] contains unsupported keys: {', '.join(sorted(unknown))}")


def _validate_planning_section(section: dict[str, object]) -> None:
    # Execute the validate planning section workflow in explicit, reviewable steps.
    supported = {
        "max_remote_gb",
        "max_local_gb",
        "max_days",
        "staging_reserve_gb",
        # Keep the max total blocks component named inside the supported contract.
        "max_total_blocks",
        "max_total_shards",
        "max_shard_blocks",
        "max_query_execution_seconds",
        "max_query_memory_mb",
        # Keep the max query result rows component named inside the supported contract.
        "max_query_result_rows",
    }
    if unknown := set(section).difference(supported):
        raise ConfigError(f"[planning] contains unsupported keys: {', '.join(sorted(unknown))}")


def _validate_source_section(section: dict[str, object]) -> None:
    # Execute the validate source section workflow in explicit, reviewable steps.
    supported = {
        "source_id",
        "host",
        "port",
        "database",
        # Keep the username component named inside the supported contract.
        "username",
        "secret_ref",
        "capabilities_file",
        "projections_file",
        "secure",
        # Keep the verified private tunnel component named inside the supported contract.
        "verified_private_tunnel",
        "allow_insecure_remote_http",
    }
    if unknown := set(section).difference(supported):
        # Report only key names: a rejected credential-shaped value must never
        # be copied into an exception or log record.
        raise ConfigError(f"[source] contains unsupported keys: {', '.join(sorted(unknown))}")


def _optional_path(section: dict[str, object], key: str) -> Path | None:
    # Execute the optional path workflow in explicit, reviewable steps.
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConfigError(f"{key} must be a non-empty path string")
    # Return the completed optional path result without a hidden fallback.
    return Path(value)


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from TOML without reading the referenced secret value."""

    selected = path
    if selected is None and (configured := os.environ.get(DEFAULT_CONFIG_ENV)):
        selected = Path(configured)
    if selected is None:
        return Settings()

    # Acquire open, rb and selected at an explicit load settings context boundary so
    # cleanup remains scoped.
    with selected.open("rb") as stream:
        raw = tomllib.load(stream)

    paths = _section(raw.get("paths"), "paths")
    resources = _section(raw.get("resources"), "resources")
    planning = _section(raw.get("planning"), "planning")
    # Invoke _validate_planning_section for planning as a visible load settings step.
    _validate_planning_section(planning)
    retention = _section(raw.get("retention"), "retention")
    backup = _section(raw.get("backup"), "backup")
    replay = _section(raw.get("replay"), "replay")
    _validate_replay_section(replay)
    # Assemble control once so the load settings workflow shares one value.
    control = _section(raw.get("control"), "control")
    source = _section(raw.get("source"), "source")
    _validate_source_section(source)

    return Settings(
        paths=PathSettings(data_root=Path(_string(paths, "data_root", "var"))),
        # Include resources in the completed load settings result.
        resources=ResourceSettings(
            max_aggregate_child_memory_mb=_integer(
                resources,
                "max_aggregate_child_memory_mb",
                8_192,
                # Complete _integer only after its max aggregate child memory mb and resources
                # inputs are visible in load settings.
            ),
            max_builder_memory_mb=_integer(resources, "max_builder_memory_mb", 6_144),
            builder_peak_private_memory_mb=_integer(
                resources,
                "builder_peak_private_memory_mb",
                # Pass 168 explicitly so _integer receives a reviewable builder peak
                # private memory mb and resources input in load settings.
                7_168,
            ),
            run_peak_private_memory_mb=_integer(
                resources,
                "run_peak_private_memory_mb",
                # Pass 072 explicitly so _integer receives a reviewable run peak private
                # memory mb and resources input in load settings.
                3_072,
            ),
            max_parallel_runs=_integer(resources, "max_parallel_runs", 1),
            tmp_quota_gb=_integer(resources, "tmp_quota_gb", 32),
            max_run_tmp_gb=_integer(resources, "max_run_tmp_gb", 1),
            # Include max run output gb in the completed load settings result.
            max_run_output_gb=_integer(resources, "max_run_output_gb", 4),
            disk_low_watermark_gb=_integer(resources, "disk_low_watermark_gb", 32),
            disk_emergency_watermark_gb=_integer(
                resources,
                "disk_emergency_watermark_gb",
                # Keep integer, resources and disk emergency watermark gb visible while
                # completing _integer within load settings.
                16,
            ),
            native_threads_per_process=_integer(resources, "native_threads_per_process", 1),
            memory_safety_reserve_mb=_integer(
                resources,
                # Pass memory safety reserve mb explicitly so _integer receives a
                # reviewable memory safety reserve mb and resources input in load
                # settings.
                "memory_safety_reserve_mb",
                1_024,
            ),
            page_cache_floor_mb=_integer(resources, "page_cache_floor_mb", 2_048),
            host_staging_output_reserve_mb=_integer(
                # Pass resources explicitly so _integer receives a reviewable host staging
                # output reserve mb and resources input in load settings.
                resources,
                "host_staging_output_reserve_mb",
                512,
            ),
            fixed_shared_overhead_mb=_integer(
                # Pass resources explicitly so _integer receives a reviewable fixed shared
                # overhead mb and resources input in load settings.
                resources,
                "fixed_shared_overhead_mb",
                256,
            ),
            memory_breach_samples=_integer(resources, "memory_breach_samples", 2),
            # Include swap activity samples in the completed load settings result.
            swap_activity_samples=_integer(resources, "swap_activity_samples", 3),
        ),
        planning=PlanningSettings(
            max_remote_gb=_integer(planning, "max_remote_gb", 16),
            max_local_gb=_integer(planning, "max_local_gb", 16),
            # Include max days in the completed load settings result.
            max_days=_integer(planning, "max_days", 7),
            staging_reserve_gb=_integer(planning, "staging_reserve_gb", 4),
            max_total_blocks=_integer(planning, "max_total_blocks", 2_000_000),
            max_total_shards=_integer(planning, "max_total_shards", 4_096),
            max_shard_blocks=_integer(planning, "max_shard_blocks", 250_000),
            # Include max query execution seconds in the completed load settings result.
            max_query_execution_seconds=_integer(
                planning,
                "max_query_execution_seconds",
                300,
            ),
            # Include max query memory mb in the completed load settings result.
            max_query_memory_mb=_integer(planning, "max_query_memory_mb", 4_096),
            max_query_result_rows=_integer(
                planning,
                "max_query_result_rows",
                10_000_000,
                # Complete _integer only after its max query result rows and planning inputs
                # are visible in load settings.
            ),
        ),
        retention=RetentionSettings(
            minimum_artifact_age_seconds=_integer(
                retention,
                # Pass minimum artifact age seconds explicitly so _integer receives a
                # reviewable minimum artifact age seconds and retention input in load
                # settings.
                "minimum_artifact_age_seconds",
                86_400,
            ),
            trash_grace_seconds=_integer(retention, "trash_grace_seconds", 86_400),
            maximum_sweep_gb=_integer(retention, "maximum_sweep_gb", 32),
            # Complete RetentionSettings only after its minimum artifact age seconds and trash
            # grace seconds inputs are visible in load settings.
        ),
        backup=BackupSettings(
            target_root=_optional_path(backup, "target_root"),
            restore_verify_parent=_optional_path(backup, "restore_verify_parent"),
            allow_same_device_for_drill=_boolean(
                # Pass backup explicitly so _boolean receives a reviewable allow same
                # device for drill and backup input in load settings.
                backup,
                "allow_same_device_for_drill",
                False,
            ),
            target_encryption_verified=_boolean(
                # Pass backup explicitly so _boolean receives a reviewable target
                # encryption verified and backup input in load settings.
                backup,
                "target_encryption_verified",
                False,
            ),
        ),
        # Include replay in the completed load settings result.
        replay=ReplaySettings(
            backend=_run_backend(replay),
            reader_batch_rows=_integer(replay, "batch_rows", 65_536),
            reader_readahead=_integer(replay, "readahead", 1),
            output_buffer_rows=_integer(replay, "output_buffer_rows", 8_192),
            # Include threads in the completed load settings result.
            threads=_integer(replay, "threads", 1),
        ),
        control=ControlSettings(
            host=_string(control, "host", "127.0.0.1"),
            port=_integer(control, "port", 8_080),
            # Include progress interval ms in the completed load settings result.
            progress_interval_ms=_integer(control, "progress_interval_ms", 500),
            max_request_mb=_integer(control, "max_request_mb", 2),
            secure_cookie=_boolean(control, "secure_cookie", False),
        ),
        source=SourceSettings(
            # Include source id in the completed load settings result.
            source_id=_string(source, "source_id", "default-indexer"),
            host=_string(source, "host", "127.0.0.1"),
            port=_integer(source, "port", 8_123),
            database=_string(source, "database", "default"),
            username=_string(source, "username", "default"),
            # Include secret ref in the completed load settings result.
            secret_ref=_string(source, "secret_ref", "BACKTEST_INDEXER_PASSWORD"),
            capabilities_file=_optional_path(source, "capabilities_file"),
            projections_file=_optional_path(source, "projections_file"),
            secure=_boolean(source, "secure", False),
            verified_private_tunnel=_boolean(
                # Pass source explicitly so _boolean receives a reviewable verified
                # private tunnel and source input in load settings.
                source,
                "verified_private_tunnel",
                False,
            ),
            # Explicit parsing keeps malformed truthy strings fail-closed.
            allow_insecure_remote_http=_boolean(
                source,
                "allow_insecure_remote_http",
                False,
            ),
            # Complete SourceSettings only after its source id and default-indexer inputs are
            # visible in load settings.
        ),
    )
