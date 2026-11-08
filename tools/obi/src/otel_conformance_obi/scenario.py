# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""The scenario side of ``otel-conformance-obi run``, for Python scenarios.

A scenario calls :func:`wait_at_gate` before its workload, the way a Go
scenario calls ``scenario.WaitAtGate``.
"""

from __future__ import annotations

import os

from otel_conformance_obi import GATE_RELEASE, GATE_VARIABLE


def wait_at_gate() -> None:
    """Read the named pipe in ``OTEL_CONFORMANCE_GATE`` until the launcher
    closes it, and fail unless the launcher released the gate first. Return at
    once when the variable is unset."""
    path = os.environ.get(GATE_VARIABLE)
    if not path:
        return
    try:
        with open(path, "rb") as gate:
            received = gate.read()
    except OSError as error:
        raise RuntimeError(f"waiting at the gate: {error}") from error
    if received != GATE_RELEASE:
        raise RuntimeError("the launcher closed the gate without releasing it")
