# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from otel_conformance_obi import GATE_VARIABLE
from otel_conformance_obi.scenario import wait_at_gate

fifo_only = pytest.mark.skipif(
    not hasattr(os, "mkfifo"), reason="the gate is a named pipe"
)


class Launcher:
    def __init__(self, gate: Path, release: bytes) -> None:
        self.holding = threading.Event()
        self.release = threading.Event()
        self._gate = gate
        self._payload = release
        self._thread = threading.Thread(target=self._hold, daemon=True)
        self._thread.start()

    def _hold(self) -> None:
        with open(self._gate, "wb") as pipe:
            self.holding.set()
            self.release.wait(timeout=5)
            pipe.write(self._payload)

    def finished(self) -> bool:
        self._thread.join(timeout=5)
        return not self._thread.is_alive()


def waiting_scenario() -> tuple[threading.Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def scenario() -> None:
        try:
            wait_at_gate()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=scenario, daemon=True)
    thread.start()
    return thread, errors


def test_no_gate_returns_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GATE_VARIABLE, raising=False)
    wait_at_gate()


@fifo_only
def test_a_released_gate_lets_the_scenario_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = tmp_path / "gate"
    os.mkfifo(gate)
    monkeypatch.setenv(GATE_VARIABLE, str(gate))
    scenario, errors = waiting_scenario()
    launcher = Launcher(gate, b"1")
    assert launcher.holding.wait(timeout=5)
    scenario.join(timeout=0.2)
    assert scenario.is_alive()
    launcher.release.set()
    scenario.join(timeout=5)
    assert not scenario.is_alive()
    assert errors == []
    assert launcher.finished()


@fifo_only
def test_a_gate_closed_without_release_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = tmp_path / "gate"
    os.mkfifo(gate)
    monkeypatch.setenv(GATE_VARIABLE, str(gate))
    scenario, errors = waiting_scenario()
    launcher = Launcher(gate, b"")
    launcher.release.set()
    scenario.join(timeout=5)
    assert not scenario.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "without releasing" in str(errors[0])
    assert launcher.finished()


def test_an_unreachable_gate_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GATE_VARIABLE, str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="waiting at the gate"):
        wait_at_gate()
