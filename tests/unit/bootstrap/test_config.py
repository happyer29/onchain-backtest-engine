# Declare this module's dependencies and contracts before execution.
from pathlib import Path

import pytest

from backtest.application.run_results import RunBackend
from backtest.bootstrap import config as bootstrap_config
from backtest.bootstrap.config import (
    # Include backup settings so the config dependency remains explicit.
    BackupSettings,
    ConfigError,
    ControlSettings,
    ReplaySettings,
    ResourceSettings,
    # Include source settings so the config dependency remains explicit.
    SourceSettings,
    load_settings,
)


def test_default_control_is_loopback() -> None:
    assert load_settings().control.host == "127.0.0.1"


# Define test non loopback control bind is rejected as one focused operation with an
# explicit boundary.
def test_non_loopback_control_bind_is_rejected() -> None:
    # Execute the test non loopback control bind is rejected workflow in explicit,
    # reviewable steps.
    with pytest.raises(ConfigError, match="loopback"):
        ControlSettings(host="0.0.0.0")


def test_config_keeps_only_secret_reference() -> None:
    # Execute the test config keeps only secret reference workflow in explicit, reviewable
    # steps.
    settings = load_settings(Path("configs/local-16gb.toml"))

    assert settings.source.secret_ref == "BACKTEST_INDEXER_PASSWORD"
    assert "password" not in repr(settings.source).lower()
    assert settings.planning.max_days == 7
    assert settings.planning.staging_reserve_gb == 4
    # Verify the max total blocks, planning and settings relationship before this scenario
    # is accepted.
    assert settings.planning.max_total_blocks == 2_000_000
    assert settings.planning.max_query_memory_mb == 4_096
    assert settings.resources.disk_emergency_watermark_gb == 16
    assert settings.resources.max_aggregate_child_memory_mb == 8_192
    assert settings.resources.max_builder_memory_mb == 6_144
    # Verify the builder peak private memory mb, resources and settings relationship
    # before this scenario is accepted.
    assert settings.resources.builder_peak_private_memory_mb == 7_168
    assert settings.resources.run_peak_private_memory_mb == 3_072
    assert settings.resources.page_cache_floor_mb == 2_048
    assert settings.retention.trash_grace_seconds == 86_400
    assert settings.backup.target_root is None
    # Verify the document, backend and output buffer rows relationship before this
    # scenario is accepted.
    assert settings.replay.to_run_physical_settings().document() == {
        "backend": "reference-python-v1",
        "output_buffer_rows": 8_192,
        "reader_batch_rows": 65_536,
        "reader_readahead": 1,
        # Keep the schema expectation tied to document, backend and output buffer rows in
        # this scenario.
        "schema": "backtest.run-physical-settings/v2",
        "threads": 1,
    }


@pytest.mark.parametrize(
    ("profile", "aggregate_memory_mb", "parallel_runs", "tmp_quota_gb"),
    # Open the profile and aggregate memory mb payload explicitly for parametrize within
    # test shipped single host profiles are strict and self consistent.
    (
        ("local-16gb.toml", 8_192, 1, 32),
        ("local-32gb.toml", 16_384, 2, 64),
        ("local-windows-wsl2-16gb.toml", 8_192, 1, 32),
    ),
)
# Define test shipped single host profiles are strict and self consistent as one focused
# operation with an explicit boundary.
def test_shipped_single_host_profiles_are_strict_and_self_consistent(
    profile: str,
    aggregate_memory_mb: int,
    parallel_runs: int,
    tmp_quota_gb: int,
    # Close the test shipped single host profiles are strict and self consistent signature
    # after its explicit inputs.
) -> None:
    # Execute the test shipped single host profiles are strict and self consistent
    # workflow in explicit, reviewable steps.
    settings = load_settings(Path("configs") / profile)

    assert settings.resources.max_aggregate_child_memory_mb == aggregate_memory_mb
    assert settings.resources.max_parallel_runs == parallel_runs
    assert settings.resources.tmp_quota_gb == tmp_quota_gb
    assert settings.resources.run_peak_private_memory_mb * parallel_runs <= aggregate_memory_mb
    # Verify the tmp quota gb, max run tmp gb and parallel runs relationship before this
    # scenario is accepted.
    assert settings.resources.max_run_tmp_gb * parallel_runs <= tmp_quota_gb
    assert settings.resources.native_threads_per_process == settings.replay.threads == 1
    assert settings.control.host in {"127.0.0.1", "::1", "localhost"}
    assert settings.source.secret_ref == "BACKTEST_INDEXER_PASSWORD"
    assert not settings.source.allow_insecure_remote_http
    # Verify the password, lower and repr relationship before this scenario is accepted.
    assert "password" not in repr(settings.source).lower()


@pytest.mark.parametrize("readahead", (0, 3, 8, True))
def test_replay_profile_rejects_unsupported_readahead(readahead: int) -> None:
    # Execute the test replay profile rejects unsupported readahead workflow in explicit,
    # reviewable steps.
    with pytest.raises(ConfigError, match="unsupported physical settings"):
        ReplaySettings(reader_readahead=readahead)


def test_replay_profile_uses_only_installed_backend_enum() -> None:
    # Execute the test replay profile uses only installed backend enum workflow in
    # explicit, reviewable steps.
    assert (
        ReplaySettings(
            backend=RunBackend.NUMPY_MMAP_FIRST_SWAP_EXACT,
            reader_readahead=2,
        ).backend
        # Keep the run backend expectation tied to backend, numpy mmap first swap exact
        # and run backend in this scenario.
        is RunBackend.NUMPY_MMAP_FIRST_SWAP_EXACT
    )


def test_emergency_watermark_cannot_exceed_start_watermark() -> None:
    # Execute the test emergency watermark cannot exceed start watermark workflow in
    # explicit, reviewable steps.
    with pytest.raises(ConfigError, match="emergency watermark"):
        # Keep raises, config error and pytest active only for the bounded test emergency
        # watermark cannot exceed start watermark operation.
        ResourceSettings(
            disk_low_watermark_gb=8,
            disk_emergency_watermark_gb=9,
        )


def test_child_and_tmp_demands_cannot_exceed_aggregate_host_limits() -> None:
    # Execute the test child and tmp demands cannot exceed aggregate host limits workflow
    # in explicit, reviewable steps.
    with pytest.raises(ConfigError, match="aggregate ceiling"):
        # Keep raises, config error and pytest active only for the bounded test child and
        # tmp demands cannot exceed aggregate host limits operation.
        ResourceSettings(
            max_aggregate_child_memory_mb=1_000,
            max_builder_memory_mb=1_001,
        )

    with pytest.raises(ConfigError, match="temporary quota"):
        # Invoke ResourceSettings as a visible step within the test child and tmp demands
        # cannot exceed aggregate host limits workflow.
        ResourceSettings(tmp_quota_gb=1, max_run_tmp_gb=2)

    assert ResourceSettings(tmp_quota_gb=1).max_run_tmp_gb == 1


def test_parallel_sweep_demands_must_fit_aggregate_host_limits() -> None:
    # Execute the test parallel sweep demands must fit aggregate host limits workflow in
    # explicit, reviewable steps.
    with pytest.raises(ConfigError, match="sweep private-memory"):
        # Keep raises, config error and pytest active only for the bounded test parallel
        # sweep demands must fit aggregate host limits operation.
        ResourceSettings(
            max_parallel_runs=2,
            run_peak_private_memory_mb=5_000,
        )

    with pytest.raises(ConfigError, match="sweep temporary"):
        # Keep raises, config error and pytest active only for the bounded test parallel
        # sweep demands must fit aggregate host limits operation.
        ResourceSettings(
            max_parallel_runs=2,
            tmp_quota_gb=1,
        )


def test_backup_paths_are_configured_as_one_restore_drill_pair() -> None:
    # Execute the test backup paths are configured as one restore drill pair workflow in
    # explicit, reviewable steps.
    with pytest.raises(ConfigError, match="configured together"):
        BackupSettings(target_root=Path("external"))

    with pytest.raises(ConfigError, match="must not overlap"):
        # Keep raises, config error and pytest active only for the bounded test backup
        # paths are configured as one restore drill pair operation.
        BackupSettings(
            target_root=Path("external"),
            restore_verify_parent=Path("external"),
            target_encryption_verified=True,
        )

    # Acquire raises, config error and pytest at an explicit test backup paths are
    # configured as one restore drill pair context boundary so cleanup remains scoped.
    with pytest.raises(ConfigError, match="encryption"):
        # Keep raises, config error and pytest active only for the bounded test backup
        # paths are configured as one restore drill pair operation.
        BackupSettings(
            target_root=Path("external"),
            restore_verify_parent=Path("restore-drills"),
        )


def test_remote_source_credentials_require_verified_transport() -> None:
    # Public plaintext remains rejected when the new local opt-in is absent.
    with pytest.raises(ConfigError, match="verified TLS"):
        SourceSettings(host="203.0.113.7", secure=False)

    # TLS remains an admitted remote mode without any warning or exception.
    tls_settings = SourceSettings(host="203.0.113.7", secure=True)
    assert tls_settings.secure

    # An explicitly verified private tunnel is the other protected mode.
    tunnel_settings = SourceSettings(
        host="10.0.0.7",
        secure=False,
        verified_private_tunnel=True,
    )
    # Verify the verified private tunnel and tunnel settings relationship before this
    # scenario is accepted.
    assert tunnel_settings.verified_private_tunnel


def test_insecure_remote_opt_in_defaults_to_false() -> None:
    # Shipped and programmatic defaults must preserve the original rejection.
    assert not SourceSettings().allow_insecure_remote_http


def test_explicit_insecure_remote_source_warns_without_connection_details() -> None:
    # Distinct marker values make accidental warning/repr disclosure visible.
    endpoint = "203.0.113.19"
    username = "private-reader-name"
    secret_ref = "PRIVATE_INDEXER_CREDENTIAL"

    # The warning is observable at construction time, but its payload is a
    # constant risk notice rather than a configuration dump.
    with pytest.warns(
        bootstrap_config.InsecureRemoteSourceWarning,
        match="Plaintext remote",
    ) as caught:
        # Keep warns, insecure remote source warning and pytest active only for the
        # bounded test explicit insecure remote source warns without connection details
        # operation.
        settings = SourceSettings(
            host=endpoint,
            username=username,
            secret_ref=secret_ref,
            allow_insecure_remote_http=True,
            # Complete SourceSettings only after its endpoint and username inputs are visible
            # in test explicit insecure remote source warns without connection details.
        )

    # The accepted operational mode is retained without exposing any secret
    # management or connection detail in the warning.
    warning_text = str(caught[0].message)
    assert settings.allow_insecure_remote_http
    assert endpoint not in warning_text
    assert username not in warning_text
    assert secret_ref not in warning_text

    # SourceSettings still redacts the environment-variable reference in repr.
    assert secret_ref not in repr(settings)


def test_insecure_remote_opt_in_rejects_tls_combination() -> None:
    # TLS already protects transport, so the plaintext-risk claim conflicts.
    with pytest.raises(ConfigError, match="allow_insecure_remote_http"):
        # Keep raises, config error and pytest active only for the bounded test insecure
        # remote opt in rejects tls combination operation.
        SourceSettings(
            host="203.0.113.23",
            secure=True,
            allow_insecure_remote_http=True,
        )


# Define test insecure remote opt in rejects tunnel combination as one focused operation
# with an explicit boundary.
def test_insecure_remote_opt_in_rejects_tunnel_combination() -> None:
    # A verified tunnel cannot simultaneously be declared public plaintext.
    with pytest.raises(ConfigError, match="allow_insecure_remote_http"):
        # Keep raises, config error and pytest active only for the bounded test insecure
        # remote opt in rejects tunnel combination operation.
        SourceSettings(
            host="203.0.113.23",
            verified_private_tunnel=True,
            allow_insecure_remote_http=True,
        )


# Define test insecure remote opt in rejects loopback as one focused operation with an
# explicit boundary.
def test_insecure_remote_opt_in_rejects_loopback() -> None:
    # Local loopback HTTP is safe from remote interception and needs no opt-in.
    with pytest.raises(ConfigError, match="allow_insecure_remote_http"):
        SourceSettings(host="127.0.0.1", allow_insecure_remote_http=True)


def test_load_settings_parses_explicit_insecure_remote_opt_in(tmp_path: Path) -> None:
    # Execute the test load settings parses explicit insecure remote opt in workflow in
    # explicit, reviewable steps.
    config_path = tmp_path / "insecure-source.toml"

    # The file contains no credential; only a reference would be valid in a
    # real deployment configuration.
    config_path.write_text(
        """
[source]
host = "203.0.113.29"
secure = false
verified_private_tunnel = false
allow_insecure_remote_http = true
""".strip(),
        encoding="utf-8",
    )

    # TOML loading constructs the same validated settings and therefore emits
    # the same explicit risk signal as direct construction.
    with pytest.warns(
        bootstrap_config.InsecureRemoteSourceWarning,
        match="not protected in transit",
    ):
        settings = load_settings(config_path)

    # Verify the allow insecure remote http, source and settings relationship before this
    # scenario is accepted.
    assert settings.source.allow_insecure_remote_http


def test_source_section_rejects_password_key_without_disclosing_value(
    tmp_path: Path,
) -> None:
    # Execute the test source section rejects password key without disclosing value
    # workflow in explicit, reviewable steps.
    config_path = tmp_path / "source-with-password.toml"
    sentinel = "credential-value-must-not-appear"
    config_path.write_text(
        f'''\n[source]\npassword = "{sentinel}"\n'''.strip(),
        encoding="utf-8",
        # Complete write_text only after its [source] password = " and " inputs are visible in
        # test source section rejects password key without disclosing value.
    )

    with pytest.raises(ConfigError, match=r"\[source\].*password") as caught:
        load_settings(config_path)

    assert sentinel not in str(caught.value)


@pytest.mark.parametrize(
    # Open the field and value payload explicitly for parametrize within test source
    # tokens fail closed.
    ("field", "value"),
    (
        ("source_id", " "),
        ("host", "http://indexer.example"),
        ("database", ""),
        # Open the field and value payload explicitly for parametrize within test source
        # tokens fail closed.
        ("username", "bad\x00name"),
        ("secret_ref", "NOT-AN-ENV-NAME"),
    ),
)
def test_source_tokens_fail_closed(field: str, value: str) -> None:
    # Execute the test source tokens fail closed workflow in explicit, reviewable steps.
    with pytest.raises(ConfigError):
        SourceSettings(**{field: value})


def test_missing_source_secret_error_does_not_disclose_secret_reference() -> None:
    # Execute the test missing source secret error does not disclose secret reference
    # workflow in explicit, reviewable steps.
    settings = SourceSettings(secret_ref="PRIVATE_INDEXER_CREDENTIAL")

    with pytest.raises(ConfigError) as caught:
        settings.password({})

    assert "PRIVATE_INDEXER_CREDENTIAL" not in str(caught.value)
