"""One-process lifecycle for one ASGI server and one local supervisor loop."""

from __future__ import annotations

from socket import socket
from threading import Event, Thread
from typing import Any

import uvicorn

# Import supervise jobs at the visible module dependency boundary.
from backtest.application.use_cases.supervise_jobs import SingleHostSupervisor


class SupervisorLoopError(RuntimeError):
    """The local controller cannot safely keep serving after its scheduler failed."""


def run_control_server(
    app: Any,
    *,
    supervisor: SingleHostSupervisor,
    host: str,
    # Keep the port input explicit in the run control server contract.
    port: int,
    cycle_interval_seconds: float,
    bound_sockets: tuple[socket, ...] = (),
    shutdown_event: Event | None = None,
) -> None:
    # Execute the run control server workflow in explicit, reviewable steps.
    if cycle_interval_seconds <= 0:
        raise ValueError("supervisor cycle interval must be positive")
    supervisor.reconcile_startup()
    server = uvicorn.Server(
        uvicorn.Config(
            # Pass app explicitly so Config receives a reviewable info and app input in
            # run control server.
            app,
            host=host,
            port=port,
            access_log=True,
            log_level="info",
            # Pass workers explicitly so Config receives a reviewable info and app input
            # in run control server.
            workers=1,
        )
    )
    stop = shutdown_event or Event()
    failures: list[BaseException] = []

    # Define supervise as one focused operation with an explicit boundary.
    def supervise() -> None:
        # Execute the supervise workflow in explicit, reviewable steps.
        try:
            # Perform the protected supervise operation before explicit failure handling.
            while not stop.is_set():
                # Keep the not stop.is_set() loop body bounded within supervise.
                supervisor.run_cycle()
                stop.wait(cycle_interval_seconds)
        except BaseException as error:
            # Translate the BaseException failure through the supervise boundary.
            failures.append(error)
            stop.set()
        finally:
            server.should_exit = True

    thread = Thread(
        # Pass target explicitly so Thread receives a reviewable backtest-single-host-
        # supervisor and supervise input in run control server.
        target=supervise,
        name="backtest-single-host-supervisor",
        daemon=False,
    )
    thread.start()
    # Assemble server failure once so the run control server workflow shares one value.
    server_failure: BaseException | None = None
    try:
        # Perform the protected run control server operation before explicit failure
        # handling.
        if bound_sockets:
            server.run(sockets=list(bound_sockets))
        else:
            server.run()
    except BaseException as error:
        # Assemble server failure once so the run control server workflow shares one
        # value.
        server_failure = error
    finally:
        # Handle the cleanup path after the protected run control server operation.
        stop.set()
        thread.join(timeout=max(10.0, cycle_interval_seconds * 4))
        if thread.is_alive():
            raise SupervisorLoopError("local supervisor did not stop within its grace period")
        supervisor.shutdown()
    # Guard this path with server_failure is not None before applying effects.
    if server_failure is not None:
        raise server_failure
    if failures:
        raise SupervisorLoopError("local supervisor loop failed") from failures[0]


__all__ = ["SupervisorLoopError", "run_control_server"]
