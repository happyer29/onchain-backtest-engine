# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Any, cast

import pytest

# Import supervise jobs at the visible module dependency boundary.
from backtest.application.use_cases.supervise_jobs import SingleHostSupervisor
from backtest.bootstrap import serve


# Keep the supervisor contract and validation rules together.
class _Supervisor:
    def __init__(self, *, cycle_error: BaseException | None = None) -> None:
        # Execute the supervisor init workflow in explicit, reviewable steps.
        self.cycle_error = cycle_error
        self.cycle_observed = Event()
        self.reconciliations = 0
        self.cycles = 0
        self.shutdowns = 0

    # Define supervisor reconcile startup as one focused operation with an explicit
    # boundary.
    def reconcile_startup(self) -> None:
        self.reconciliations += 1

    def run_cycle(self) -> None:
        # Execute the supervisor run cycle workflow in explicit, reviewable steps.
        self.cycles += 1
        self.cycle_observed.set()
        if self.cycle_error is not None:
            raise self.cycle_error

    def shutdown(self) -> None:
        # Assemble self shutdowns once so the supervisor shutdown workflow shares one
        # value.
        self.shutdowns += 1


def _install_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
    run: Callable[[Any], None],
) -> list[dict[str, object]]:
    # Execute the install uvicorn workflow in explicit, reviewable steps.
    configurations: list[dict[str, object]] = []

    def config(app: Any, **values: object) -> dict[str, object]:
        # Execute the config workflow in explicit, reviewable steps.
        document = {"app": app, **values}
        configurations.append(document)
        return document

    # Keep the server contract and validation rules together.
    class Server:
        def __init__(self, configuration: object) -> None:
            # Execute the server init workflow in explicit, reviewable steps.
            self.configuration = configuration
            self.should_exit = False

        def run(self) -> None:
            run(self)

    monkeypatch.setattr(serve.uvicorn, "Config", config)
    # Invoke setattr for server and uvicorn as a visible install uvicorn step.
    monkeypatch.setattr(serve.uvicorn, "Server", Server)
    return configurations


def test_control_server_runs_one_supervisor_loop_and_shuts_it_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test control server runs one supervisor loop and shuts it down workflow
    # in explicit, reviewable steps.
    supervisor = _Supervisor()

    def run(server: object) -> None:
        # Execute the run workflow in explicit, reviewable steps.
        del server
        assert supervisor.cycle_observed.wait(2)

    configurations = _install_uvicorn(monkeypatch, run)

    serve.run_control_server(
        object(),
        # Pass supervisor explicitly to run_control_server for 1 and object.
        supervisor=cast(SingleHostSupervisor, supervisor),
        host="127.0.0.1",
        port=8124,
        cycle_interval_seconds=0.01,
    )

    # Verify supervisor.reconciliations == 1 before this scenario is accepted.
    assert supervisor.reconciliations == 1
    assert supervisor.cycles >= 1
    assert supervisor.shutdowns == 1
    assert configurations == [
        {
            # Keep the access log expectation tied to configurations, access log and app
            # in this scenario.
            "access_log": True,
            "app": configurations[0]["app"],
            "host": "127.0.0.1",
            "log_level": "info",
            "port": 8124,
            # Keep the workers expectation tied to configurations, access log and app in
            # this scenario.
            "workers": 1,
        }
    ]


def test_supervisor_loop_failure_stops_server_and_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    # Close the test supervisor loop failure stops server and is reported signature after its
    # explicit inputs.
) -> None:
    # Execute the test supervisor loop failure stops server and is reported workflow in
    # explicit, reviewable steps.
    failure = RuntimeError("scheduler failed")
    supervisor = _Supervisor(cycle_error=failure)

    def run(server: Any) -> None:
        # Execute the run workflow in explicit, reviewable steps.
        assert supervisor.cycle_observed.wait(2)
        assert server.should_exit is True

    _install_uvicorn(monkeypatch, run)

    with pytest.raises(serve.SupervisorLoopError) as caught:
        # Keep raises, supervisor loop error and pytest active only for the bounded test
        # supervisor loop failure stops server and is reported operation.
        serve.run_control_server(
            object(),
            supervisor=cast(SingleHostSupervisor, supervisor),
            host="127.0.0.1",
            port=8124,
            # Pass cycle interval seconds explicitly so run_control_server receives a
            # reviewable 1 and object input in test supervisor loop failure stops server
            # and is reported.
            cycle_interval_seconds=0.01,
        )

    assert caught.value.__cause__ is failure
    assert supervisor.shutdowns == 1


def test_server_failure_is_re_raised_after_supervisor_shutdown(
    # Keep the monkeypatch input explicit in the test server failure is re raised after
    # supervisor shutdown contract.
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the test server failure is re raised after supervisor shutdown workflow in
    # explicit, reviewable steps.
    supervisor = _Supervisor()
    failure = LookupError("bind failed")

    def run(server: object) -> None:
        # Execute the run workflow in explicit, reviewable steps.
        del server
        assert supervisor.cycle_observed.wait(2)
        raise failure

    _install_uvicorn(monkeypatch, run)

    with pytest.raises(LookupError) as caught:
        # Keep raises, lookup error and pytest active only for the bounded test server
        # failure is re raised after supervisor shutdown operation.
        serve.run_control_server(
            object(),
            supervisor=cast(SingleHostSupervisor, supervisor),
            host="127.0.0.1",
            port=8124,
            # Pass cycle interval seconds explicitly so run_control_server receives a
            # reviewable 1 and object input in test server failure is re raised after
            # supervisor shutdown.
            cycle_interval_seconds=0.01,
        )

    assert caught.value is failure
    assert supervisor.shutdowns == 1


def test_control_server_rejects_non_positive_cycle_interval() -> None:
    # Execute the test control server rejects non positive cycle interval workflow in
    # explicit, reviewable steps.
    supervisor = _Supervisor()

    with pytest.raises(ValueError, match="interval must be positive"):
        # Keep raises, value error and pytest active only for the bounded test control
        # server rejects non positive cycle interval operation.
        serve.run_control_server(
            object(),
            supervisor=cast(SingleHostSupervisor, supervisor),
            host="127.0.0.1",
            port=8124,
            # Pass cycle interval seconds explicitly so run_control_server receives a
            # reviewable 1 and object input in test control server rejects non positive
            # cycle interval.
            cycle_interval_seconds=0,
        )

    assert supervisor.reconciliations == 0
